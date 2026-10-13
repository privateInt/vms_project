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

type DeviceUsage uint8

const (
	DeviceUsageUnknown DeviceUsage = iota
	DeviceUsageUnused
	DeviceUsageInUse
)

// DeviceDeleteGuard is a trusted server-side admission check, never client input.
// It runs with the active device row locked in this transaction. It must use tx,
// must not commit/rollback or change the device, children or profiles, and must
// reject pending cleanup or uncertain usage.
// Future usage creators must share this lock (or equivalent atomic admission).
// A remote observation alone cannot protect against a new concurrent consumer.
// This storage unit supplies NO default "unused" guard. The HTTP unit must first
// verify its registry-only release has no session/consumer/adapter creators.
type DeviceDeleteGuard func(context.Context, pgx.Tx, string) (DeviceUsage, error)

// DeleteDevice preserves the parent/children/profiles/history and atomically journals the
// first successful tombstone. Replays do not check usage again or mutate data.
func (s *Store) DeleteDevice(ctx context.Context, principal, key, id string, input contracts.DeviceDelete, guard DeviceDeleteGuard) (contracts.DeviceDeletion, bool, error) {
	if principal == "" || !contracts.ValidIdempotencyKey(key) || !contracts.ValidDeviceID(id) || len(input.Validate()) != 0 {
		return contracts.DeviceDeletion{}, false, failure("CONTRACT_INVALID", nil)
	}
	path := "/api/v1/devices/" + id
	canonical, _ := json.Marshal(input)
	requestHash, keyHash := hashText(canonical), hashText([]byte(key))
	lockBytes, _ := json.Marshal([]string{principal, "DELETE", path, keyHash})
	lock := sha256.Sum256(lockBytes)
	var result contracts.DeviceDeletion
	replayed := false
	err := s.WithTx(ctx, func(tx pgx.Tx) error {
		if _, err := tx.Exec(ctx, "SELECT pg_advisory_xact_lock($1)", int64(binary.BigEndian.Uint64(lock[:8]))); err != nil {
			return failure("DATABASE_UNAVAILABLE", err)
		}
		var previousHash string
		var previous []byte
		err := tx.QueryRow(ctx, `SELECT request_hash,response_body FROM camera.device_delete_requests
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
		// Share CreateSource's device lock. The following parent and child reads
		// are separate READ COMMITTED statements after lock acquisition.
		if _, err = tx.Exec(ctx, "SELECT pg_advisory_xact_lock(1447908164,hashtext($1))", id); err != nil {
			return failure("DATABASE_UNAVAILABLE", err)
		}
		var version int64
		err = tx.QueryRow(ctx, "SELECT version FROM camera.devices WHERE device_id=$1 AND deleted_at IS NULL FOR UPDATE", id).Scan(&version)
		if errors.Is(err, pgx.ErrNoRows) {
			return failure("DEVICE_NOT_FOUND", nil)
		}
		if err != nil {
			return failure("DATABASE_UNAVAILABLE", err)
		}
		if version != input.ExpectedVersion {
			return failure("DEVICE_VERSION_CONFLICT", nil)
		}
		if version == math.MaxInt64 {
			return failure("DEVICE_VERSION_EXHAUSTED", nil)
		}
		var activeChildren bool
		if err = tx.QueryRow(ctx, "SELECT EXISTS(SELECT 1 FROM camera.video_sources WHERE device_id=$1 AND deleted_at IS NULL)", id).Scan(&activeChildren); err != nil {
			return failure("DATABASE_UNAVAILABLE", err)
		}
		if activeChildren {
			return failure("DEVICE_HAS_ACTIVE_SOURCES", nil)
		}
		var activeCredentials bool
		if err = tx.QueryRow(ctx, "SELECT camera.device_has_active_credentials($1)", id).Scan(&activeCredentials); err != nil {
			return failure("DATABASE_UNAVAILABLE", err)
		}
		if activeCredentials {
			return failure("DEVICE_IN_USE", nil)
		}
		if guard == nil {
			return failure("DEVICE_USAGE_UNAVAILABLE", nil)
		}
		usage, err := guard(ctx, tx, id)
		if err != nil {
			return failure("DEVICE_USAGE_UNAVAILABLE", err)
		}
		switch usage {
		case DeviceUsageInUse:
			return failure("DEVICE_IN_USE", nil)
		case DeviceUsageUnused:
		default:
			return failure("DEVICE_USAGE_UNAVAILABLE", nil)
		}
		// Evaluate the clock once; both timestamps must match, even when an
		// earlier writer stored an updated_at later than the current clock.
		err = tx.QueryRow(ctx, `WITH stamp AS MATERIALIZED (
 SELECT GREATEST(clock_timestamp(),updated_at) AS at FROM camera.devices WHERE device_id=$1
)
UPDATE camera.devices SET deleted_at=stamp.at,updated_at=stamp.at,version=version+1
FROM stamp WHERE device_id=$1 AND version=$2 AND deleted_at IS NULL
RETURNING device_id,version,deleted_at`, id, input.ExpectedVersion).Scan(&result.DeviceID, &result.Version, &result.DeletedAt)
		if err != nil {
			return failure("DATABASE_UNAVAILABLE", err)
		}
		result.SchemaVersion = "v1"
		result.DeletedAt = result.DeletedAt.UTC()
		body, err := json.Marshal(result)
		if err != nil {
			return failure("DATABASE_UNAVAILABLE", err)
		}
		_, err = tx.Exec(ctx, `INSERT INTO camera.device_delete_requests
(principal,method,path,key_hash,request_hash,response_body) VALUES ($1,'DELETE',$2,$3,$4,$5::jsonb)`, principal, path, keyHash, requestHash, string(body))
		if err != nil {
			return failure("DATABASE_UNAVAILABLE", err)
		}
		return nil
	})
	if err != nil {
		return contracts.DeviceDeletion{}, false, err
	}
	return result, replayed, nil
}
