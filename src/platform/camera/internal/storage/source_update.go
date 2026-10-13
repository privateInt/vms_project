package storage

import (
	"context"
	"crypto/sha256"
	"encoding/binary"
	"encoding/json"
	"errors"
	"math"

	"github.com/jackc/pgx/v5"
	"vms.local/platform/camera/internal/contracts"
)

// UpdateSource atomically commits a version-checked rename and its successful
// response including ordered profiles. Replays never rewind the current source.
func (s *Store) UpdateSource(ctx context.Context, principal, key, id string, input contracts.SourceUpdate) (contracts.VideoSource, bool, error) {
	if principal == "" || !contracts.ValidIdempotencyKey(key) || !contracts.ValidDeviceID(id) || id == "validate" || len(input.Validate()) != 0 {
		return contracts.VideoSource{}, false, failure("CONTRACT_INVALID", nil)
	}
	path := "/api/v1/sources/" + id
	canonical, _ := json.Marshal(input)
	requestHash, keyHash := hashText(canonical), hashText([]byte(key))
	lockBytes, _ := json.Marshal([]string{principal, "PATCH", path, keyHash})
	lock := sha256.Sum256(lockBytes)
	var result contracts.VideoSource
	replayed := false
	err := s.WithTx(ctx, func(tx pgx.Tx) error {
		if _, err := tx.Exec(ctx, "SELECT pg_advisory_xact_lock($1)", int64(binary.BigEndian.Uint64(lock[:8]))); err != nil {
			return failure("DATABASE_UNAVAILABLE", err)
		}
		var previousHash string
		var previous []byte
		err := tx.QueryRow(ctx, `SELECT request_hash,response_body FROM camera.source_update_requests
WHERE principal=$1 AND method='PATCH' AND path=$2 AND key_hash=$3`, principal, path, keyHash).Scan(&previousHash, &previous)
		if err == nil {
			if previousHash != requestHash {
				return failure("IDEMPOTENCY_CONFLICT", nil)
			}
			if err = json.Unmarshal(previous, &result); err != nil {
				return failure("DATABASE_UNAVAILABLE", err)
			}
			replayed = true
			return nil
		}
		if !errors.Is(err, pgx.ErrNoRows) {
			return failure("DATABASE_UNAVAILABLE", err)
		}
		var version int64
		err = tx.QueryRow(ctx, "SELECT version FROM camera.video_sources WHERE source_id=$1 AND deleted_at IS NULL FOR UPDATE", id).Scan(&version)
		if errors.Is(err, pgx.ErrNoRows) {
			return failure("SOURCE_NOT_FOUND", nil)
		}
		if err != nil {
			return failure("DATABASE_UNAVAILABLE", err)
		}
		if version != input.ExpectedVersion {
			return failure("SOURCE_VERSION_CONFLICT", nil)
		}
		if version == math.MaxInt64 {
			return failure("SOURCE_VERSION_EXHAUSTED", nil)
		}
		changed, err := tx.Exec(ctx, `UPDATE camera.video_sources
SET display_name=$2,version=version+1,updated_at=GREATEST(clock_timestamp(),updated_at)
WHERE source_id=$1 AND version=$3 AND deleted_at IS NULL`, id, input.DisplayName, input.ExpectedVersion)
		if err != nil {
			return failure("DATABASE_UNAVAILABLE", err)
		}
		if changed.RowsAffected() != 1 {
			return failure("SOURCE_VERSION_CONFLICT", nil)
		}
		// Profiles are read with the source in one SQL snapshot. Future profile
		// writers must share this source-row lock before changing its declaration.
		result, err = scanSource(tx.QueryRow(ctx, sourceSelect, id))
		if err != nil {
			return failure("DATABASE_UNAVAILABLE", err)
		}
		body, err := json.Marshal(result)
		if err != nil {
			return failure("DATABASE_UNAVAILABLE", err)
		}
		_, err = tx.Exec(ctx, `INSERT INTO camera.source_update_requests
(principal,method,path,key_hash,request_hash,response_body) VALUES ($1,'PATCH',$2,$3,$4,$5::jsonb)`, principal, path, keyHash, requestHash, string(body))
		if err != nil {
			return failure("DATABASE_UNAVAILABLE", err)
		}
		return nil
	})
	if err != nil {
		return contracts.VideoSource{}, false, err
	}
	return result, replayed, nil
}
