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

type SourceUsage uint8

const (
	SourceUsageUnknown SourceUsage = iota
	SourceUsageUnused
	SourceUsageInUse
)

// SourceDeleteGuard is a trusted server-side admission check, never client input.
// It runs with the active source row locked in this transaction. It must use tx,
// must not commit/rollback or change the source declaration/profiles, and must
// reject pending cleanup or uncertain usage.
// Future usage creators must share this lock (or equivalent atomic admission).
// A remote observation alone cannot protect against a new concurrent consumer.
// This storage unit supplies NO default "unused" guard. The HTTP unit must first
// verify its registry-only release has no session/consumer/adapter creators.
type SourceDeleteGuard func(context.Context, pgx.Tx, string) (SourceUsage, error)

// DeleteSource preserves the row/profiles/history and atomically journals the
// first successful tombstone. Replays do not check usage again or mutate data.
func (s *Store) DeleteSource(ctx context.Context, principal, key, id string, input contracts.SourceDelete, guard SourceDeleteGuard) (contracts.SourceDeletion, bool, error) {
	if principal == "" || !contracts.ValidIdempotencyKey(key) || !contracts.ValidDeviceID(id) || id == "validate" || len(input.Validate()) != 0 {
		return contracts.SourceDeletion{}, false, failure("CONTRACT_INVALID", nil)
	}
	path := "/api/v1/sources/" + id
	canonical, _ := json.Marshal(input)
	requestHash, keyHash := hashText(canonical), hashText([]byte(key))
	lockBytes, _ := json.Marshal([]string{principal, "DELETE", path, keyHash})
	lock := sha256.Sum256(lockBytes)
	var result contracts.SourceDeletion
	replayed := false
	err := s.WithTx(ctx, func(tx pgx.Tx) error {
		if _, err := tx.Exec(ctx, "SELECT pg_advisory_xact_lock($1)", int64(binary.BigEndian.Uint64(lock[:8]))); err != nil {
			return failure("DATABASE_UNAVAILABLE", err)
		}
		var previousHash string
		var previous []byte
		err := tx.QueryRow(ctx, `SELECT request_hash,response_body FROM camera.source_delete_requests
WHERE principal=$1 AND method='DELETE' AND path=$2 AND key_hash=$3`, principal, path, keyHash).Scan(&previousHash, &previous)
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
		if guard == nil {
			return failure("SOURCE_USAGE_UNAVAILABLE", nil)
		}
		usage, err := guard(ctx, tx, id)
		if err != nil {
			return failure("SOURCE_USAGE_UNAVAILABLE", err)
		}
		switch usage {
		case SourceUsageInUse:
			return failure("SOURCE_IN_USE", nil)
		case SourceUsageUnused:
		default:
			return failure("SOURCE_USAGE_UNAVAILABLE", nil)
		}
		// Evaluate the clock once; both timestamps must match, even when an
		// earlier writer stored an updated_at later than the current clock.
		err = tx.QueryRow(ctx, `WITH stamp AS MATERIALIZED (
 SELECT GREATEST(clock_timestamp(),updated_at) AS at FROM camera.video_sources WHERE source_id=$1
)
UPDATE camera.video_sources SET deleted_at=stamp.at,updated_at=stamp.at,version=version+1
FROM stamp WHERE source_id=$1 AND version=$2 AND deleted_at IS NULL
RETURNING source_id,version,deleted_at`, id, input.ExpectedVersion).Scan(&result.SourceID, &result.Version, &result.DeletedAt)
		if err != nil {
			return failure("DATABASE_UNAVAILABLE", err)
		}
		result.SchemaVersion = "v1"
		result.DeletedAt = result.DeletedAt.UTC()
		body, err := json.Marshal(result)
		if err != nil {
			return failure("DATABASE_UNAVAILABLE", err)
		}
		_, err = tx.Exec(ctx, `INSERT INTO camera.source_delete_requests
(principal,method,path,key_hash,request_hash,response_body) VALUES ($1,'DELETE',$2,$3,$4,$5::jsonb)`, principal, path, keyHash, requestHash, string(body))
		if err != nil {
			return failure("DATABASE_UNAVAILABLE", err)
		}
		return nil
	})
	if err != nil {
		return contracts.SourceDeletion{}, false, err
	}
	return result, replayed, nil
}
