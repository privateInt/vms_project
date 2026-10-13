package storage

import (
	"context"
	"crypto/sha256"
	"embed"
	"encoding/hex"
	"encoding/json"
	"regexp"
	"time"

	"github.com/jackc/pgx/v5"
)

// Schema 9 is deliberately separate from legacy schema 8 migrations. Existing
// rehearsal/registry entry points cannot silently select the admission target.
//
//go:embed admission_migrations/0009_credential_admission.sql
var admissionMigrationFiles embed.FS

const admissionMigrationName = "admission_migrations/0009_credential_admission.sql"

func loadAdmissionMigrations() ([]migration, error) {
	ms, err := loadMigrations(migrationFiles)
	if err != nil || len(ms) != 8 {
		return nil, failure("ADMISSION_MIGRATIONS_INVALID", nil)
	}
	body, err := admissionMigrationFiles.ReadFile(admissionMigrationName)
	if err != nil {
		return nil, failure("ADMISSION_MIGRATIONS_INVALID", nil)
	}
	hash := sha256.Sum256(body)
	return append(ms, migration{name: admissionMigrationName, sql: string(body), checksum: hex.EncodeToString(hash[:])}), nil
}

// Hash format v1: UTF-8 compact JSON array, no trailing newline; entries ordered
// by version; keys in version,name,checksum order. Checksums hash exact SQL bytes.
func admissionMigrationsHash(ms []migration) string {
	type entry struct {
		Version  int    `json:"version"`
		Name     string `json:"name"`
		Checksum string `json:"checksum"`
	}
	rows := make([]entry, len(ms))
	for i, m := range ms {
		rows[i] = entry{i + 1, m.name, m.checksum}
	}
	raw, _ := json.Marshal(rows)
	digest := sha256.Sum256(raw)
	return hex.EncodeToString(digest[:])
}

func CredentialAdmissionMigrationsSHA256() (string, error) {
	ms, err := loadAdmissionMigrations()
	if err != nil {
		return "", err
	}
	return admissionMigrationsHash(ms), nil
}

// MigrateCredentialAdmission is an explicit owner-only administrative target.
// It creates an EMPTY marker table; it never invents/replaces an incarnation,
// changes external authority, enrolls a key or authorizes credential traffic.
func (s *Store) MigrateCredentialAdmission(ctx context.Context) (MigrationResult, error) {
	ms, err := loadAdmissionMigrations()
	if err != nil {
		return MigrationResult{}, err
	}
	return s.migrate(ctx, ms)
}

// ProvisionCredentialAdmissionReaders grants only inspection of schema/history
// and the marker. Credentials/budget permissions remain a separate operation.
func (s *Store) ProvisionCredentialAdmissionReaders(ctx context.Context) error {
	_, err := s.pool.Exec(ctx, `GRANT USAGE ON SCHEMA camera TO camera_credential_writer, camera_credential_budget;
GRANT SELECT ON camera.schema_migrations, camera.credential_admission_database TO camera_credential_writer, camera_credential_budget;`)
	if err != nil {
		return failure("ADMISSION_DATABASE_UNAVAILABLE", nil)
	}
	return nil
}

// CredentialAdmissionDatabase is a DB subset of the external approved record.
// Expected values must come from the locked authority in the runtime
// guard, never from the DB itself or an HTTP caller.
type CredentialAdmissionDatabase struct {
	DeploymentID       string
	Generation         int64
	OperationID        string
	DatabaseID         string
	DatabaseName       string
	SchemaVersion      int
	MigrationSetSHA256 string
}

var admissionUUID = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`)
var admissionDatabaseName = regexp.MustCompile(`^[A-Za-z_][A-Za-z0-9_]{0,62}$`)

func (e CredentialAdmissionDatabase) valid(hash string) bool {
	return admissionUUID.MatchString(e.DeploymentID) && e.Generation > 0 &&
		admissionUUID.MatchString(e.OperationID) && admissionUUID.MatchString(e.DatabaseID) &&
		admissionDatabaseName.MatchString(e.DatabaseName) && e.SchemaVersion == 9 && e.MigrationSetSHA256 == hash
}

// CheckCredentialAdmissionDatabase reads one repeatable-read, read-only snapshot
// using an actual fixed role. It consumes no encryption budget and returns only
// a fixed error, without private driver causes. This is NOT a runtime admission
// guard: callers must still hold a valid external shared lease for the entire
// credential operation, check both endpoints/keys/budgets and fence restores.
func (s *Store) CheckCredentialAdmissionDatabase(ctx context.Context, expected CredentialAdmissionDatabase, role string) error {
	denied := func() error { return failure("ADMISSION_DATABASE_UNAVAILABLE", nil) }
	ms, err := loadAdmissionMigrations()
	if err != nil || !expected.valid(admissionMigrationsHash(ms)) ||
		(role != "camera_credential_writer" && role != "camera_credential_budget") ||
		s == nil || s.pool == nil {
		return denied()
	}
	cfg := s.pool.Config().ConnConfig
	if cfg.User != role || cfg.Database != expected.DatabaseName {
		return denied()
	}
	tx, err := s.pool.BeginTx(ctx, pgx.TxOptions{IsoLevel: pgx.RepeatableRead, AccessMode: pgx.ReadOnly})
	if err != nil {
		return denied()
	}
	defer func() {
		cleanup, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = tx.Rollback(cleanup)
	}()
	if err = checkCredentialAdmissionDatabaseTx(ctx, tx, expected, role, ms); err != nil {
		return denied()
	}
	if tx.Commit(ctx) != nil {
		return denied()
	}
	return nil
}

// Shared by the endpoint binding check so actual transport and SQL identity
// are inspected on the very same acquired connection/snapshot.
func checkCredentialAdmissionDatabaseTx(ctx context.Context, tx pgx.Tx, expected CredentialAdmissionDatabase, role string, ms []migration) error {
	denied := func() error { return failure("ADMISSION_DATABASE_UNAVAILABLE", nil) }
	var err error
	var session, current, database string
	var safeRole bool
	err = tx.QueryRow(ctx, `SELECT session_user::text,current_user::text,current_database()::text,
rolcanlogin AND NOT (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls)
FROM pg_catalog.pg_roles WHERE rolname=current_user`).Scan(&session, &current, &database, &safeRole)
	if err != nil || session != role || current != role || database != expected.DatabaseName || !safeRole {
		return denied()
	}
	var allowed bool
	err = tx.QueryRow(ctx, `SELECT has_table_privilege(current_user,'camera.credential_admission_database','SELECT')
AND NOT has_schema_privilege(current_user,'camera','CREATE')
AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_class WHERE oid IN
('camera.credential_admission_database'::regclass,'camera.schema_migrations'::regclass) AND
(has_table_privilege(current_user,oid,'DELETE,TRUNCATE,TRIGGER,REFERENCES') OR pg_has_role(current_user,relowner,'MEMBER')))
AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_attribute WHERE attrelid IN
('camera.credential_admission_database'::regclass,'camera.schema_migrations'::regclass)
AND attnum>0 AND NOT attisdropped AND
(has_column_privilege(current_user,attrelid,attnum,'INSERT') OR has_column_privilege(current_user,attrelid,attnum,'UPDATE')))`).Scan(&allowed)
	if err != nil || !allowed {
		return denied()
	}
	rows, err := tx.Query(ctx, "SELECT version,name,checksum FROM camera.schema_migrations ORDER BY version")
	if err != nil {
		return denied()
	}
	i := 0
	for rows.Next() {
		var version int
		var name, checksum string
		if rows.Scan(&version, &name, &checksum) != nil || i >= len(ms) || version != i+1 || name != ms[i].name || checksum != ms[i].checksum {
			rows.Close()
			return denied()
		}
		i++
	}
	err = rows.Err()
	rows.Close()
	if err != nil || i != len(ms) {
		return denied()
	}
	rows, err = tx.Query(ctx, `SELECT singleton,deployment_id,generation,operation_id,database_id,database_name,schema_version,migration_set_sha256
FROM camera.credential_admission_database`)
	if err != nil {
		return denied()
	}
	var actual CredentialAdmissionDatabase
	var singleton int
	if !rows.Next() || rows.Scan(&singleton, &actual.DeploymentID, &actual.Generation, &actual.OperationID, &actual.DatabaseID, &actual.DatabaseName, &actual.SchemaVersion, &actual.MigrationSetSHA256) != nil {
		rows.Close()
		return denied()
	}
	extra := rows.Next()
	err = rows.Err()
	rows.Close()
	if singleton != 1 || extra || err != nil || actual != expected {
		return denied()
	}
	return nil
}
