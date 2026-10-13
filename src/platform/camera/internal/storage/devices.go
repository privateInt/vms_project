package storage

import (
	"context"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"

	"github.com/jackc/pgx/v5"
	"vms.local/platform/camera/internal/contracts"
)

const deviceColumns = "device_id, display_name, device_kind, version, created_at, updated_at"

func scanDevice(row pgx.Row) (contracts.Device, error) {
	d := contracts.Device{SchemaVersion: "v1"}
	err := row.Scan(&d.DeviceID, &d.DisplayName, &d.DeviceKind, &d.Version, &d.CreatedAt, &d.UpdatedAt)
	d.CreatedAt = d.CreatedAt.UTC()
	d.UpdatedAt = d.UpdatedAt.UTC()
	return d, err
}
func hashText(b []byte) string { h := sha256.Sum256(b); return hex.EncodeToString(h[:]) }

// All callers must supply an authenticated principal, not an HTTP header value.
// A fixed shared development principal is used until IAM is introduced.
func (s *Store) CreateDevice(ctx context.Context, principal, key string, input contracts.DeviceCreate) (contracts.Device, bool, error) {
	if principal == "" || !contracts.ValidIdempotencyKey(key) || len(input.Validate()) != 0 {
		return contracts.Device{}, false, failure("CONTRACT_INVALID", nil)
	}
	canonical, _ := json.Marshal(input)
	requestHash, keyHash := hashText(canonical), hashText([]byte(key))
	lockBytes, _ := json.Marshal([]string{principal, "POST", "/api/v1/devices", keyHash})
	lock := sha256.Sum256(lockBytes)
	var result contracts.Device
	replayed := false
	err := s.WithTx(ctx, func(tx pgx.Tx) error {
		if _, e := tx.Exec(ctx, "SELECT pg_advisory_xact_lock($1)", int64(binary.BigEndian.Uint64(lock[:8]))); e != nil {
			return failure("DATABASE_UNAVAILABLE", e)
		}
		var previousHash string
		var previous []byte
		e := tx.QueryRow(ctx, `SELECT request_hash,response_body FROM camera.device_create_requests WHERE principal=$1 AND method='POST' AND path='/api/v1/devices' AND key_hash=$2`, principal, keyHash).Scan(&previousHash, &previous)
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
		result, e = scanDevice(tx.QueryRow(ctx, "INSERT INTO camera.devices(device_id,display_name,device_kind) VALUES ($1,$2,$3) RETURNING "+deviceColumns, input.DeviceID, input.DisplayName, input.DeviceKind))
		if e != nil {
			wrapped := failure("DATABASE_UNAVAILABLE", e).(*Error)
			if wrapped.SQLState == "23505" {
				return failure("DEVICE_EXISTS", nil)
			}
			return wrapped
		}
		response, e := json.Marshal(result)
		if e != nil {
			return failure("DATABASE_UNAVAILABLE", e)
		}
		_, e = tx.Exec(ctx, `INSERT INTO camera.device_create_requests(principal,method,path,key_hash,request_hash,response_body) VALUES ($1,'POST','/api/v1/devices',$2,$3,$4::jsonb)`, principal, keyHash, requestHash, string(response))
		if e != nil {
			return failure("DATABASE_UNAVAILABLE", e)
		}
		return nil
	})
	if err != nil {
		return contracts.Device{}, false, err
	}
	return result, replayed, nil
}

func (s *Store) GetDevice(ctx context.Context, id string) (contracts.Device, error) {
	d, err := scanDevice(s.pool.QueryRow(ctx, "SELECT "+deviceColumns+" FROM camera.devices WHERE device_id=$1 AND deleted_at IS NULL", id))
	if errors.Is(err, pgx.ErrNoRows) {
		return d, failure("DEVICE_NOT_FOUND", nil)
	}
	if err != nil {
		return d, failure("DATABASE_UNAVAILABLE", err)
	}
	return d, nil
}

func (s *Store) ListDevices(ctx context.Context, after string, limit int) ([]contracts.Device, bool, error) {
	if limit < 1 || limit > 200 || (after != "" && !contracts.ValidDeviceID(after)) {
		return nil, false, failure("CONTRACT_INVALID", nil)
	}
	rows, err := s.pool.Query(ctx, "SELECT "+deviceColumns+" FROM camera.devices WHERE deleted_at IS NULL AND device_id > $1 COLLATE \"C\" ORDER BY device_id COLLATE \"C\" LIMIT $2", after, limit+1)
	if err != nil {
		return nil, false, failure("DATABASE_UNAVAILABLE", err)
	}
	defer rows.Close()
	items := make([]contracts.Device, 0)
	for rows.Next() {
		d, e := scanDevice(rows)
		if e != nil {
			return nil, false, failure("DATABASE_UNAVAILABLE", e)
		}
		items = append(items, d)
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

// Read-only validation for API startup/readiness. Migration is a separate command.
func (s *Store) checkMigrationReady(ctx context.Context) error {
	expected, err := loadMigrations(migrationFiles)
	if err != nil {
		return err
	}
	rows, err := s.pool.Query(ctx, "SELECT version,name,checksum FROM camera.schema_migrations ORDER BY version")
	if err != nil {
		return failure("DATABASE_SCHEMA_NOT_READY", err)
	}
	i := 0
	for rows.Next() {
		var version int
		var name, checksum string
		if err = rows.Scan(&version, &name, &checksum); err != nil {
			rows.Close()
			return failure("DATABASE_SCHEMA_NOT_READY", err)
		}
		if i >= len(expected) || version != i+1 || name != expected[i].name || checksum != expected[i].checksum {
			rows.Close()
			return failure("DATABASE_SCHEMA_NOT_READY", nil)
		}
		i++
	}
	err = rows.Err()
	rows.Close()
	if err != nil || i != len(expected) {
		return failure("DATABASE_SCHEMA_NOT_READY", err)
	}
	return nil
}

func (s *Store) CheckReady(ctx context.Context) error {
	if err := s.checkMigrationReady(ctx); err != nil {
		return err
	}
	var allowed bool
	err := s.pool.QueryRow(ctx, `SELECT has_table_privilege(current_user,'camera.devices','SELECT') AND has_table_privilege(current_user,'camera.devices','INSERT') AND has_table_privilege(current_user,'camera.device_create_requests','SELECT') AND has_table_privilege(current_user,'camera.device_create_requests','INSERT') AND has_table_privilege(current_user,'camera.video_sources','SELECT') AND has_table_privilege(current_user,'camera.video_sources','INSERT') AND has_table_privilege(current_user,'camera.stream_profiles','SELECT') AND has_table_privilege(current_user,'camera.stream_profiles','INSERT') AND has_table_privilege(current_user,'camera.source_create_requests','SELECT') AND has_table_privilege(current_user,'camera.source_create_requests','INSERT') AND has_table_privilege(current_user,'camera.device_update_requests','SELECT') AND has_table_privilege(current_user,'camera.device_update_requests','INSERT') AND has_column_privilege(current_user,'camera.devices','display_name','UPDATE') AND has_column_privilege(current_user,'camera.devices','version','UPDATE') AND has_column_privilege(current_user,'camera.devices','updated_at','UPDATE') AND has_table_privilege(current_user,'camera.source_update_requests','SELECT') AND has_table_privilege(current_user,'camera.source_update_requests','INSERT') AND has_column_privilege(current_user,'camera.video_sources','display_name','UPDATE') AND has_column_privilege(current_user,'camera.video_sources','version','UPDATE') AND has_column_privilege(current_user,'camera.video_sources','updated_at','UPDATE') AND has_column_privilege(current_user,'camera.video_sources','deleted_at','UPDATE') AND has_table_privilege(current_user,'camera.source_delete_requests','SELECT') AND has_table_privilege(current_user,'camera.source_delete_requests','INSERT') AND has_column_privilege(current_user,'camera.devices','deleted_at','UPDATE') AND has_table_privilege(current_user,'camera.device_delete_requests','SELECT') AND has_table_privilege(current_user,'camera.device_delete_requests','INSERT') AND has_function_privilege(current_user,'camera.device_has_active_credentials(text)','EXECUTE')`).Scan(&allowed)
	if err != nil || !allowed {
		return failure("DATABASE_PERMISSIONS_NOT_READY", err)
	}
	return nil
}
