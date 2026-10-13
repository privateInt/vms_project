package storage

import (
	"context"
	"crypto/sha256"
	"embed"
	"encoding/hex"
	"fmt"
	"io/fs"
	"sort"

	"github.com/jackc/pgx/v5"
)

//go:embed migrations/*.sql
var migrationFiles embed.FS

type migration struct{ name, sql, checksum string }
type MigrationResult struct {
	Applied int `json:"applied"`
	Version int `json:"version"`
}

func loadMigrations(files fs.FS) ([]migration, error) {
	paths, err := fs.Glob(files, "migrations/*.sql")
	if err != nil || len(paths) == 0 {
		return nil, failure("MIGRATION_FILES_INVALID", err)
	}
	sort.Strings(paths)
	var result []migration
	for i, path := range paths {
		prefix := fmt.Sprintf("migrations/%04d_", i+1)
		if len(path) <= len(prefix)+4 || path[:len(prefix)] != prefix {
			return nil, failure("MIGRATION_ORDER_INVALID", nil)
		}
		body, err := fs.ReadFile(files, path)
		if err != nil {
			return nil, failure("MIGRATION_FILES_INVALID", err)
		}
		hash := sha256.Sum256(body)
		result = append(result, migration{name: path, sql: string(body), checksum: hex.EncodeToString(hash[:])})
	}
	return result, nil
}

func (s *Store) Migrate(ctx context.Context) (MigrationResult, error) {
	migrations, err := loadMigrations(migrationFiles)
	if err != nil {
		return MigrationResult{}, err
	}
	return s.migrate(ctx, migrations)
}

// One transaction and a DB-scoped transaction lock serialize this schema's DDL.
// Existing migration content is immutable; append a new numbered file to change it.
func (s *Store) migrate(ctx context.Context, migrations []migration) (MigrationResult, error) {
	result := MigrationResult{}
	err := s.WithTx(ctx, func(tx pgx.Tx) error {
		if _, err := tx.Exec(ctx, "SELECT pg_advisory_xact_lock(1447908163, 1)"); err != nil {
			return failure("MIGRATION_LOCK_FAILED", err)
		}
		if _, err := tx.Exec(ctx, `CREATE SCHEMA IF NOT EXISTS camera;
CREATE TABLE IF NOT EXISTS camera.schema_migrations (
 version integer PRIMARY KEY CHECK (version > 0), name text NOT NULL,
 checksum text NOT NULL CHECK (checksum ~ '^[0-9a-f]{64}$'),
 applied_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);`); err != nil {
			return failure("MIGRATION_BOOTSTRAP_FAILED", err)
		}
		rows, err := tx.Query(ctx, "SELECT version, name, checksum FROM camera.schema_migrations ORDER BY version")
		if err != nil {
			return failure("MIGRATION_HISTORY_FAILED", err)
		}
		count := 0
		for rows.Next() {
			var version int
			var name, checksum string
			if err = rows.Scan(&version, &name, &checksum); err != nil {
				rows.Close()
				return failure("MIGRATION_HISTORY_FAILED", err)
			}
			if version != count+1 || version > len(migrations) || name != migrations[version-1].name || checksum != migrations[version-1].checksum {
				rows.Close()
				return failure("MIGRATION_HISTORY_MISMATCH", nil)
			}
			count++
		}
		err = rows.Err()
		rows.Close()
		if err != nil {
			return failure("MIGRATION_HISTORY_FAILED", err)
		}
		for i := count; i < len(migrations); i++ {
			m := migrations[i]
			if _, err := tx.Exec(ctx, m.sql); err != nil {
				return failure("MIGRATION_APPLY_FAILED", err)
			}
			if _, err := tx.Exec(ctx, "INSERT INTO camera.schema_migrations(version, name, checksum) VALUES ($1,$2,$3)", i+1, m.name, m.checksum); err != nil {
				return failure("MIGRATION_HISTORY_FAILED", err)
			}
			result.Applied++
		}
		result.Version = len(migrations)
		return nil
	})
	if err != nil {
		return MigrationResult{}, err
	}
	return result, nil
}
