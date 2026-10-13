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

// UpdateDevice atomically commits a version-checked rename and its successful
// response. Replays return that snapshot even after later device changes.
func (s *Store) UpdateDevice(ctx context.Context, principal, key, id string, input contracts.DeviceUpdate) (contracts.Device, bool, error) {
	if principal == "" || !contracts.ValidIdempotencyKey(key) || !contracts.ValidDeviceID(id) || len(input.Validate()) != 0 {
		return contracts.Device{}, false, failure("CONTRACT_INVALID", nil)
	}
	path := "/api/v1/devices/" + id
	canonical, _ := json.Marshal(input)
	requestHash, keyHash := hashText(canonical), hashText([]byte(key))
	lockBytes, _ := json.Marshal([]string{principal, "PATCH", path, keyHash})
	lock := sha256.Sum256(lockBytes)
	var result contracts.Device
	replayed := false
	err := s.WithTx(ctx, func(tx pgx.Tx) error {
		if _, err := tx.Exec(ctx, "SELECT pg_advisory_xact_lock($1)", int64(binary.BigEndian.Uint64(lock[:8]))); err != nil {
			return failure("DATABASE_UNAVAILABLE", err)
		}
		var previousHash string
		var previous []byte
		err := tx.QueryRow(ctx, `SELECT request_hash,response_body FROM camera.device_update_requests
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
		current, err := scanDevice(tx.QueryRow(ctx, "SELECT "+deviceColumns+" FROM camera.devices WHERE device_id=$1 AND deleted_at IS NULL FOR UPDATE", id))
		if errors.Is(err, pgx.ErrNoRows) {
			return failure("DEVICE_NOT_FOUND", nil)
		}
		if err != nil {
			return failure("DATABASE_UNAVAILABLE", err)
		}
		if current.Version != input.ExpectedVersion {
			return failure("DEVICE_VERSION_CONFLICT", nil)
		}
		if current.Version == math.MaxInt64 {
			return failure("DEVICE_VERSION_EXHAUSTED", nil)
		}
		result, err = scanDevice(tx.QueryRow(ctx, `UPDATE camera.devices
SET display_name=$2,version=version+1,updated_at=GREATEST(clock_timestamp(),updated_at)
WHERE device_id=$1 AND version=$3 AND deleted_at IS NULL RETURNING `+deviceColumns, id, input.DisplayName, input.ExpectedVersion))
		if errors.Is(err, pgx.ErrNoRows) {
			return failure("DEVICE_VERSION_CONFLICT", nil)
		}
		if err != nil {
			return failure("DATABASE_UNAVAILABLE", err)
		}
		body, err := json.Marshal(result)
		if err != nil {
			return failure("DATABASE_UNAVAILABLE", err)
		}
		_, err = tx.Exec(ctx, `INSERT INTO camera.device_update_requests
(principal,method,path,key_hash,request_hash,response_body) VALUES ($1,'PATCH',$2,$3,$4,$5::jsonb)`, principal, path, keyHash, requestHash, string(body))
		if err != nil {
			return failure("DATABASE_UNAVAILABLE", err)
		}
		return nil
	})
	if err != nil {
		return contracts.Device{}, false, err
	}
	return result, replayed, nil
}
