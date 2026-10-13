package storage

import (
	"context"
	"io"
	"os"
	"strings"

	"github.com/jackc/pgx/v5"
)

// DatabaseURL reads one explicit source. An absent setting preserves foundation mode.
func DatabaseURL() (string, bool, error) {
	value, direct := os.LookupEnv("CAMERA_DATABASE_URL")
	path, file := os.LookupEnv("CAMERA_DATABASE_URL_FILE")
	if direct && file {
		return "", true, failure("DATABASE_CONFIG_AMBIGUOUS", nil)
	}
	if !file {
		return value, direct, nil
	}
	if path == "" {
		return "", true, failure("DATABASE_SECRET_INVALID", nil)
	}
	f, err := os.Open(path)
	if err != nil {
		return "", true, failure("DATABASE_SECRET_UNAVAILABLE", nil)
	}
	defer f.Close()
	info, err := f.Stat()
	if err != nil || !info.Mode().IsRegular() {
		return "", true, failure("DATABASE_SECRET_INVALID", nil)
	}
	b, err := io.ReadAll(io.LimitReader(f, 8193))
	if err != nil || len(b) > 8192 {
		return "", true, failure("DATABASE_SECRET_INVALID", nil)
	}
	value = strings.TrimSuffix(strings.TrimSuffix(string(b), "\n"), "\r")
	if value == "" || strings.ContainsAny(value, "\r\n") {
		return "", true, failure("DATABASE_SECRET_INVALID", nil)
	}
	return value, true, nil
}

// ProvisionRegistryRuntime grants registry access and only mutable device/source columns.
// Bootstrap creates the fixed runtime role separately from the schema owner.
func (s *Store) ProvisionRegistryRuntime(ctx context.Context) error {
	return s.WithTx(ctx, func(tx pgx.Tx) error {
		_, err := tx.Exec(ctx, `GRANT USAGE ON SCHEMA camera TO camera_runtime;
GRANT SELECT ON camera.schema_migrations TO camera_runtime;
GRANT SELECT, INSERT ON camera.devices, camera.device_create_requests, camera.video_sources, camera.stream_profiles, camera.source_create_requests, camera.device_update_requests, camera.source_update_requests, camera.source_delete_requests, camera.device_delete_requests TO camera_runtime;
GRANT UPDATE (display_name, version, updated_at, deleted_at) ON camera.devices TO camera_runtime;
GRANT UPDATE (display_name, version, updated_at, deleted_at) ON camera.video_sources TO camera_runtime;
GRANT EXECUTE ON FUNCTION camera.device_has_active_credentials(text) TO camera_runtime;`)
		if err != nil {
			return failure("DATABASE_RUNTIME_GRANT_FAILED", err)
		}
		return nil
	})
}
