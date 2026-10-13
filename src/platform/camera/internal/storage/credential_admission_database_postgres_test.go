package storage

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"github.com/jackc/pgx/v5/pgxpool"
)

func putAdmissionMarker(t *testing.T, owner *Store, ctx context.Context, e CredentialAdmissionDatabase) {
	t.Helper()
	_, err := owner.pool.Exec(ctx, `INSERT INTO camera.credential_admission_database
(singleton,deployment_id,generation,operation_id,database_id,database_name,schema_version,migration_set_sha256)
VALUES (1,$1,$2,$3,$4,$5,$6,$7)`, e.DeploymentID, e.Generation, e.OperationID, e.DatabaseID, e.DatabaseName, e.SchemaVersion, e.MigrationSetSHA256)
	if err != nil {
		t.Fatal(err)
	}
}

func admissionStores(t *testing.T) (*Store, *Store, *Store, context.Context, CredentialAdmissionDatabase) {
	t.Helper()
	nativeCredentialRequired(t)
	owner, ctx := testStore(t)
	if _, err := owner.Migrate(ctx); err != nil {
		t.Fatal(err)
	}
	writer := credentialRoleStore(t, owner, ctx, "camera_credential_writer")
	budget := credentialRoleStore(t, owner, ctx, "camera_credential_budget")
	if _, err := owner.MigrateCredentialAdmission(ctx); err != nil {
		t.Fatal(err)
	}
	if err := owner.ProvisionCredentialAdmissionReaders(ctx); err != nil {
		t.Fatal(err)
	}
	return owner, writer, budget, ctx, admissionDatabaseFixture(t)
}

func TestNativeAdmissionDatabaseUpgradeAndPreservation(t *testing.T) {
	owner, ctx := testStore(t)
	if r, err := owner.Migrate(ctx); err != nil || r.Version != 8 {
		t.Fatal(r, err)
	}
	if _, err := owner.pool.Exec(ctx, seed); err != nil {
		t.Fatal(err)
	}
	if _, err := owner.pool.Exec(ctx, `INSERT INTO camera.credential_encryption_budgets(key_id,uses,enabled) VALUES ('enc-1111111111111111',42,false)`); err != nil {
		t.Fatal(err)
	}
	r, err := owner.MigrateCredentialAdmission(ctx)
	if err != nil || r.Version != 9 || r.Applied != 1 {
		t.Fatal(r, err)
	}
	var count int
	var uses int64
	var enabled bool
	if err = owner.pool.QueryRow(ctx, `SELECT count(*) FROM camera.credential_admission_database`).Scan(&count); err != nil || count != 0 {
		t.Fatal("automatic marker created", err)
	}
	putAdmissionMarker(t, owner, ctx, admissionDatabaseFixture(t))
	r, err = owner.MigrateCredentialAdmission(ctx)
	if err != nil || r.Applied != 0 || r.Version != 9 {
		t.Fatal(r, err)
	}
	if err = owner.pool.QueryRow(ctx, `SELECT count(*) FROM camera.devices`).Scan(&count); err != nil || count != 1 {
		t.Fatal("device history lost", err)
	}
	if err = owner.pool.QueryRow(ctx, `SELECT count(*) FROM camera.video_sources WHERE source_id='s1' AND device_id='d1'`).Scan(&count); err != nil || count != 1 {
		t.Fatal("source history lost", err)
	}
	if err = owner.pool.QueryRow(ctx, `SELECT count(*) FROM camera.stream_profiles WHERE source_id='s1' AND profile_id='main'`).Scan(&count); err != nil || count != 1 {
		t.Fatal("profile history lost", err)
	}
	if err = owner.pool.QueryRow(ctx, `SELECT uses,enabled FROM camera.credential_encryption_budgets`).Scan(&uses, &enabled); err != nil || uses != 42 || enabled {
		t.Fatal("budget changed", err)
	}
	if err = owner.pool.QueryRow(ctx, `SELECT count(*) FROM camera.credential_admission_database`).Scan(&count); err != nil || count != 1 {
		t.Fatal("marker lost", err)
	}
	if _, err = owner.Migrate(ctx); err == nil {
		t.Fatal("legacy target accepted schema9")
	}
	if err = owner.CheckReady(ctx); err == nil {
		t.Fatal("legacy runtime accepted schema9")
	}
	// A fresh isolated DB can select the explicit target too; legacy callers
	// still cannot select it accidentally.
	if _, err = owner.pool.Exec(ctx, "DROP SCHEMA camera CASCADE"); err != nil {
		t.Fatal(err)
	}
	if r, err = owner.MigrateCredentialAdmission(ctx); err != nil || r.Applied != 9 || r.Version != 9 {
		t.Fatal(r, err)
	}
	// Schema 9 DDL and its history entry must roll back together.
	if _, err = owner.pool.Exec(ctx, "DROP SCHEMA camera CASCADE"); err != nil {
		t.Fatal(err)
	}
	if _, err = owner.Migrate(ctx); err != nil {
		t.Fatal(err)
	}
	ms, _ := loadAdmissionMigrations()
	ms[8].sql += "\nSELECT 1/0;"
	if _, err = owner.migrate(ctx, ms); err == nil {
		t.Fatal("broken schema9 accepted")
	}
	var absent bool
	if err = owner.pool.QueryRow(ctx, "SELECT to_regclass('camera.credential_admission_database') IS NULL").Scan(&absent); err != nil || !absent {
		t.Fatal("partial schema9 survived", err)
	}
	if r, err = owner.MigrateCredentialAdmission(ctx); err != nil || r.Applied != 1 {
		t.Fatal(r, err)
	}
}

func TestNativeAdmissionDatabaseMarkerConstraints(t *testing.T) {
	owner, ctx := testStore(t)
	if _, err := owner.MigrateCredentialAdmission(ctx); err != nil {
		t.Fatal(err)
	}
	putAdmissionMarker(t, owner, ctx, admissionDatabaseFixture(t))
	for _, sql := range []string{
		`UPDATE camera.credential_admission_database SET singleton=2`,
		`UPDATE camera.credential_admission_database SET generation=0`,
		`UPDATE camera.credential_admission_database SET generation=-1`,
		`UPDATE camera.credential_admission_database SET schema_version=8`,
		`UPDATE camera.credential_admission_database SET deployment_id='11111111-1111-1111-8111-111111111111'`,
		`UPDATE camera.credential_admission_database SET operation_id='22222222-2222-4222-0222-222222222222'`,
		`UPDATE camera.credential_admission_database SET database_id='AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA'`,
		`UPDATE camera.credential_admission_database SET database_name='unsafe/name'`,
		`UPDATE camera.credential_admission_database SET migration_set_sha256='private-value'`,
		`INSERT INTO camera.credential_admission_database SELECT * FROM camera.credential_admission_database`,
	} {
		if _, err := owner.pool.Exec(ctx, sql); err == nil {
			t.Fatal("invalid marker accepted")
		}
	}
}

func TestNativeAdmissionDatabaseActualRolesAndBinding(t *testing.T) {
	owner, writer, budget, ctx, expected := admissionStores(t)
	if err := writer.CheckCredentialAdmissionDatabase(ctx, expected, "camera_credential_writer"); err == nil {
		t.Fatal("empty marker accepted")
	}
	putAdmissionMarker(t, owner, ctx, expected)
	for _, v := range []struct {
		s    *Store
		role string
	}{{writer, "camera_credential_writer"}, {budget, "camera_credential_budget"}} {
		for i := 0; i < 2; i++ {
			if err := v.s.CheckCredentialAdmissionDatabase(ctx, expected, v.role); err != nil {
				t.Fatal(err)
			}
		}
		for _, query := range []string{`UPDATE camera.credential_admission_database SET generation=2`, `DELETE FROM camera.credential_admission_database`, `TRUNCATE camera.credential_admission_database`, `INSERT INTO camera.credential_admission_database SELECT * FROM camera.credential_admission_database`, `ALTER TABLE camera.credential_admission_database ADD COLUMN bad text`} {
			if _, err := v.s.pool.Exec(ctx, query); err == nil {
				t.Fatal("runtime changed marker")
			}
		}
	}
	if err := budget.CheckCredentialAdmissionDatabase(ctx, expected, "camera_credential_writer"); err == nil {
		t.Fatal("wrong authenticated role accepted")
	}
	if err := owner.CheckCredentialAdmissionDatabase(ctx, expected, "camera_credential_writer"); err == nil {
		t.Fatal("owner accepted as runtime")
	}
	if _, err := owner.pool.Exec(ctx, "GRANT camera_credential_writer TO camera_credential_budget"); err != nil {
		t.Fatal(err)
	}
	cfg := budget.pool.Config()
	cfg.ConnConfig.RuntimeParams["role"] = "camera_credential_writer"
	changedPool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		t.Fatal(err)
	}
	changed := &Store{pool: changedPool}
	if err = changed.CheckCredentialAdmissionDatabase(ctx, expected, "camera_credential_budget"); err == nil {
		t.Fatal("SET ROLE session accepted")
	}
	changed.Close()
	if _, err = owner.pool.Exec(ctx, "REVOKE camera_credential_writer FROM camera_credential_budget"); err != nil {
		t.Fatal(err)
	}
	cases := map[string]func(*CredentialAdmissionDatabase){
		"database":    func(e *CredentialAdmissionDatabase) { e.DatabaseName = "other" },
		"deployment":  func(e *CredentialAdmissionDatabase) { e.DeploymentID = "44444444-4444-4444-8444-444444444444" },
		"operation":   func(e *CredentialAdmissionDatabase) { e.OperationID = "44444444-4444-4444-8444-444444444444" },
		"generation":  func(e *CredentialAdmissionDatabase) { e.Generation++ },
		"incarnation": func(e *CredentialAdmissionDatabase) { e.DatabaseID = "44444444-4444-4444-8444-444444444444" },
		"checksum":    func(e *CredentialAdmissionDatabase) { e.MigrationSetSHA256 = strings.Repeat("f", 64) },
	}
	for name, change := range cases {
		t.Run(name, func(t *testing.T) {
			e := expected
			change(&e)
			if writer.CheckCredentialAdmissionDatabase(ctx, e, "camera_credential_writer") == nil {
				t.Fatal("mismatch accepted")
			}
		})
	}
}

func TestNativeAdmissionDatabaseHistoryAndGrantLoss(t *testing.T) {
	owner, writer, _, ctx, expected := admissionStores(t)
	putAdmissionMarker(t, owner, ctx, expected)
	check := func(want bool) {
		t.Helper()
		err := writer.CheckCredentialAdmissionDatabase(ctx, expected, "camera_credential_writer")
		if (err == nil) != want {
			t.Fatalf("ready=%v err=%v", want, err)
		}
	}
	check(true)
	for _, pair := range [][2]string{
		{`GRANT UPDATE(generation) ON camera.credential_admission_database TO camera_credential_writer`, `REVOKE UPDATE(generation) ON camera.credential_admission_database FROM camera_credential_writer`},
		{`GRANT INSERT ON camera.credential_admission_database TO camera_credential_writer`, `REVOKE INSERT ON camera.credential_admission_database FROM camera_credential_writer`},
		{`GRANT DELETE ON camera.credential_admission_database TO camera_credential_writer`, `REVOKE DELETE ON camera.credential_admission_database FROM camera_credential_writer`},
		{`GRANT CREATE ON SCHEMA camera TO camera_credential_writer`, `REVOKE CREATE ON SCHEMA camera FROM camera_credential_writer`},
		{`GRANT UPDATE(checksum) ON camera.schema_migrations TO camera_credential_writer`, `REVOKE UPDATE(checksum) ON camera.schema_migrations FROM camera_credential_writer`},
		{`REVOKE SELECT ON camera.credential_admission_database FROM camera_credential_writer`, `GRANT SELECT ON camera.credential_admission_database TO camera_credential_writer`},
		{`REVOKE SELECT ON camera.schema_migrations FROM camera_credential_writer`, `GRANT SELECT ON camera.schema_migrations TO camera_credential_writer`},
		{`ALTER ROLE camera_credential_writer CREATEDB`, `ALTER ROLE camera_credential_writer NOCREATEDB`},
		{`ALTER ROLE camera_credential_writer NOLOGIN`, `ALTER ROLE camera_credential_writer LOGIN`},
		{`GRANT vms_camera_test TO camera_credential_writer WITH INHERIT FALSE`, `REVOKE vms_camera_test FROM camera_credential_writer`},
	} {
		if _, err := owner.pool.Exec(ctx, pair[0]); err != nil {
			t.Fatal(err)
		}
		check(false)
		if _, err := owner.pool.Exec(ctx, pair[1]); err != nil {
			t.Fatal(err)
		}
		check(true)
	}
	ms, _ := loadAdmissionMigrations()
	if _, err := owner.pool.Exec(ctx, `UPDATE camera.schema_migrations SET checksum=$1 WHERE version=9`, strings.Repeat("0", 64)); err != nil {
		t.Fatal(err)
	}
	check(false)
	if _, err := owner.MigrateCredentialAdmission(ctx); err == nil {
		t.Fatal("changed history accepted by migration")
	}
	if _, err := owner.pool.Exec(ctx, `UPDATE camera.schema_migrations SET checksum=$1 WHERE version=9`, ms[8].checksum); err != nil {
		t.Fatal(err)
	}
	check(true)
	if _, err := owner.pool.Exec(ctx, `INSERT INTO camera.schema_migrations(version,name,checksum) VALUES (10,'future',$1)`, strings.Repeat("0", 64)); err != nil {
		t.Fatal(err)
	}
	check(false)
	if _, err := owner.pool.Exec(ctx, `DELETE FROM camera.schema_migrations WHERE version=10`); err != nil {
		t.Fatal(err)
	}
	check(true)
	if _, err := owner.pool.Exec(ctx, `UPDATE camera.credential_admission_database SET migration_set_sha256=$1`, strings.Repeat("0", 64)); err != nil {
		t.Fatal(err)
	}
	check(false)
}

func TestNativeAdmissionDatabaseSnapshotRestore(t *testing.T) {
	nativeCredentialRequired(t)
	if os.Getenv("CAMERA_TEST_ADMISSION_DUMP_RESTORE") != "1" {
		t.Skip("explicit native pg_dump/pg_restore check absent")
	}
	for _, name := range []string{"pg_dump", "pg_restore"} {
		if _, err := exec.LookPath(name); err != nil {
			t.Fatal("native backup tool required")
		}
	}
	owner, writer, budget, ctx, old := admissionStores(t)
	putAdmissionMarker(t, owner, ctx, old)
	dump := filepath.Join(t.TempDir(), "synthetic.pgdump")
	run := func(name string, args ...string) {
		t.Helper()
		// libpq does not expand a connection URI supplied only as an environment
		// default PGDATABASE. Supply dbname explicitly to both native tools.
		args = append(args, "--dbname="+os.Getenv("CAMERA_TEST_DATABASE_URL"))
		cmd := exec.CommandContext(ctx, name, args...)
		if out, err := cmd.CombinedOutput(); err != nil {
			t.Fatalf("native %s failed: %v %s", name, err, out)
		}
	}
	run("pg_dump", "--format=custom", "--schema=camera", "--file="+dump)
	next := old
	next.Generation = 2
	next.DatabaseID = "44444444-4444-4444-8444-444444444444"
	next.OperationID = "55555555-5555-4555-8555-555555555555"
	if _, err := owner.pool.Exec(ctx, `UPDATE camera.credential_admission_database SET generation=$1,database_id=$2,operation_id=$3`, next.Generation, next.DatabaseID, next.OperationID); err != nil {
		t.Fatal(err)
	}
	if err := writer.CheckCredentialAdmissionDatabase(ctx, next, "camera_credential_writer"); err != nil {
		t.Fatal(err)
	}
	run("pg_restore", "--clean", "--if-exists", "--exit-on-error", dump)
	for _, v := range []struct {
		s    *Store
		role string
	}{{writer, "camera_credential_writer"}, {budget, "camera_credential_budget"}} {
		if err := v.s.CheckCredentialAdmissionDatabase(ctx, next, v.role); err == nil {
			t.Fatal("restored old incarnation accepted for new authority")
		}
		// Explicitly preserve this limitation: unchanged old external authority can
		// match its old dump. Only the external fence/lease flow prevents this case.
		if err := v.s.CheckCredentialAdmissionDatabase(ctx, old, v.role); err != nil {
			t.Fatal("old marker restore not reproduced", err)
		}
	}
}
