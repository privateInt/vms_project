package storage

import (
	"context"
	"crypto/sha256"
	"encoding/binary"
	"encoding/json"
	"errors"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"vms.local/platform/camera/internal/contracts"
)

// One SQL statement reads metadata and ordered profiles from the same snapshot.
const sourceSelectBase = `SELECT s.source_id,s.device_id,s.channel_key,s.display_name,s.transport,s.input_mode,s.motion_mode,s.version,s.created_at,s.updated_at,
(SELECT jsonb_agg(jsonb_build_object('profile_id',p.profile_id,'codec',p.codec,'width',p.width,'height',p.height,'fps',p.fps) ORDER BY p.position) FROM camera.stream_profiles p WHERE p.source_id=s.source_id)
FROM camera.video_sources s`

const sourceSelect = sourceSelectBase + ` WHERE s.source_id=$1 AND s.deleted_at IS NULL`

func scanSource(row pgx.Row) (contracts.VideoSource, error) {
	s := contracts.VideoSource{SchemaVersion: "v1"}
	var profiles []byte
	err := row.Scan(&s.SourceID, &s.DeviceID, &s.ChannelKey, &s.DisplayName, &s.Transport, &s.InputMode, &s.MotionMode, &s.Version, &s.CreatedAt, &s.UpdatedAt, &profiles)
	if err != nil {
		return s, err
	}
	if err = json.Unmarshal(profiles, &s.Profiles); err != nil || len(s.Profiles) == 0 {
		return s, failure("DATABASE_UNAVAILABLE", err)
	}
	s.CreatedAt = s.CreatedAt.UTC()
	s.UpdatedAt = s.UpdatedAt.UTC()
	return s, nil
}

func (s *Store) CreateSource(ctx context.Context, principal, key string, input contracts.SourceCreate) (contracts.VideoSource, bool, error) {
	if principal == "" || !contracts.ValidIdempotencyKey(key) || len(input.Validate()) != 0 {
		return contracts.VideoSource{}, false, failure("CONTRACT_INVALID", nil)
	}
	canonical, _ := json.Marshal(input)
	requestHash, keyHash := hashText(canonical), hashText([]byte(key))
	lockBytes, _ := json.Marshal([]string{principal, "POST", "/api/v1/sources", keyHash})
	lock := sha256.Sum256(lockBytes)
	var result contracts.VideoSource
	replayed := false
	err := s.WithTx(ctx, func(tx pgx.Tx) error {
		if _, e := tx.Exec(ctx, "SELECT pg_advisory_xact_lock($1)", int64(binary.BigEndian.Uint64(lock[:8]))); e != nil {
			return failure("DATABASE_UNAVAILABLE", e)
		}
		var previousHash string
		var previous []byte
		e := tx.QueryRow(ctx, `SELECT request_hash,response_body FROM camera.source_create_requests WHERE principal=$1 AND method='POST' AND path='/api/v1/sources' AND key_hash=$2`, principal, keyHash).Scan(&previousHash, &previous)
		if e == nil {
			if previousHash != requestHash {
				return failure("IDEMPOTENCY_CONFLICT", nil)
			}
			if e = json.Unmarshal(previous, &result); e != nil {
				return failure("DATABASE_UNAVAILABLE", e)
			}
			replayed = true
			return nil
		}
		if !errors.Is(e, pgx.ErrNoRows) {
			return failure("DATABASE_UNAVAILABLE", e)
		}
		// Device deletion shares this domain lock before checking children and
		// changing the parent. Source creation needs no additional UPDATE grant.
		if _, e = tx.Exec(ctx, "SELECT pg_advisory_xact_lock(1447908164,hashtext($1))", input.DeviceID); e != nil {
			return failure("DATABASE_UNAVAILABLE", e)
		}
		var parent bool
		if e = tx.QueryRow(ctx, "SELECT EXISTS(SELECT 1 FROM camera.devices WHERE device_id=$1 AND deleted_at IS NULL)", input.DeviceID).Scan(&parent); e != nil {
			return failure("DATABASE_UNAVAILABLE", e)
		}
		if !parent {
			return failure("DEVICE_UNAVAILABLE", nil)
		}
		_, e = tx.Exec(ctx, `INSERT INTO camera.video_sources(source_id,device_id,channel_key,display_name,transport,input_mode,motion_mode,primary_profile_id) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)`, input.SourceID, input.DeviceID, input.ChannelKey, input.DisplayName, input.Transport, input.InputMode, input.MotionMode, input.Profiles[0].ProfileID)
		if e != nil {
			var pg *pgconn.PgError
			if errors.As(e, &pg) {
				if pg.Code == "23505" && pg.ConstraintName == "source_channel_unique" {
					return failure("SOURCE_CHANNEL_EXISTS", nil)
				}
				if pg.Code == "23505" {
					return failure("SOURCE_EXISTS", nil)
				}
				if pg.Code == "23503" {
					return failure("DEVICE_UNAVAILABLE", nil)
				}
			}
			return failure("DATABASE_UNAVAILABLE", e)
		}
		for i, p := range input.Profiles {
			if _, e = tx.Exec(ctx, `INSERT INTO camera.stream_profiles(source_id,profile_id,position,codec,width,height,fps) VALUES ($1,$2,$3,$4,$5,$6,$7)`, input.SourceID, p.ProfileID, i+1, p.Codec, p.Width, p.Height, p.FPS); e != nil {
				return failure("DATABASE_UNAVAILABLE", e)
			}
		}
		result, e = scanSource(tx.QueryRow(ctx, sourceSelect, input.SourceID))
		if e != nil {
			return failure("DATABASE_UNAVAILABLE", e)
		}
		response, e := json.Marshal(result)
		if e != nil {
			return failure("DATABASE_UNAVAILABLE", e)
		}
		_, e = tx.Exec(ctx, `INSERT INTO camera.source_create_requests(principal,method,path,key_hash,request_hash,response_body) VALUES ($1,'POST','/api/v1/sources',$2,$3,$4::jsonb)`, principal, keyHash, requestHash, string(response))
		if e != nil {
			return failure("DATABASE_UNAVAILABLE", e)
		}
		return nil
	})
	if err != nil {
		return contracts.VideoSource{}, false, err
	}
	return result, replayed, nil
}

func (s *Store) GetSource(ctx context.Context, id string) (contracts.VideoSource, error) {
	value, err := scanSource(s.pool.QueryRow(ctx, sourceSelect, id))
	if errors.Is(err, pgx.ErrNoRows) {
		return value, failure("SOURCE_NOT_FOUND", nil)
	}
	if err != nil {
		return value, failure("DATABASE_UNAVAILABLE", err)
	}
	return value, nil
}

// A single SQL snapshot contains each source and its ordered profiles. Seek by
// immutable source ID so deletions do not shift positions like an offset would.
func (s *Store) ListSources(ctx context.Context, after, deviceID string, limit int) ([]contracts.VideoSource, bool, error) {
	if limit < 1 || limit > 200 || (after != "" && !contracts.ValidDeviceID(after)) || (deviceID != "" && !contracts.ValidDeviceID(deviceID)) {
		return nil, false, failure("CONTRACT_INVALID", nil)
	}
	rows, err := s.pool.Query(ctx, sourceSelectBase+` WHERE s.deleted_at IS NULL AND s.source_id > $1 COLLATE "C"
AND ($2 = '' OR s.device_id = $2) ORDER BY s.source_id COLLATE "C" LIMIT $3`, after, deviceID, limit+1)
	if err != nil {
		return nil, false, failure("DATABASE_UNAVAILABLE", err)
	}
	defer rows.Close()
	items := make([]contracts.VideoSource, 0)
	for rows.Next() {
		item, e := scanSource(rows)
		if e != nil {
			return nil, false, failure("DATABASE_UNAVAILABLE", e)
		}
		items = append(items, item)
	}
	if err = rows.Err(); err != nil {
		return nil, false, failure("DATABASE_UNAVAILABLE", err)
	}
	more := len(items) > limit
	if more {
		items = items[:limit]
	}
	return items, more, nil
}
