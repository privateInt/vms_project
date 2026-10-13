package storage

import (
	"context"
	"errors"
	"os"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
)

// These integration tests DROP camera schema. The supplied DB must be disposable.
// The Docker runner creates a dedicated DB and sets both required variables.
func testStore(t *testing.T) (*Store, context.Context) {
	t.Helper()
	dsn := os.Getenv("CAMERA_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("CAMERA_TEST_DATABASE_URL absent: PostgreSQL integration not executed")
	}
	if os.Getenv("CAMERA_TEST_ALLOW_SCHEMA_RESET") != "1" {
		t.Fatal("explicit CAMERA_TEST_ALLOW_SCHEMA_RESET=1 required for disposable DB")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 120*time.Second)
	t.Cleanup(cancel)
	s, err := Open(ctx, dsn)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(s.Close)
	var database, engine string
	if e := s.pool.QueryRow(ctx, "SELECT current_database(), version()").Scan(&database, &engine); e != nil {
		t.Fatal(e)
	}
	wasm := os.Getenv("CAMERA_TEST_ENGINE") == "pglite" && strings.Contains(engine, "(PGlite ")
	if database != "vms_camera_test" && !wasm {
		t.Fatal("refusing schema reset outside disposable vms_camera_test database")
	}
	reset := func() {
		if _, e := s.pool.Exec(ctx, "DROP SCHEMA IF EXISTS camera CASCADE"); e != nil {
			t.Fatal(e)
		}
	}
	reset()
	t.Cleanup(func() {
		c, stop := context.WithTimeout(context.Background(), 5*time.Second)
		defer stop()
		_, _ = s.pool.Exec(c, "DROP SCHEMA IF EXISTS camera CASCADE")
	})
	return s, ctx
}

func state(err error) string {
	var pg *pgconn.PgError
	if errors.As(err, &pg) {
		return pg.Code
	}
	return ""
}

const seed = `INSERT INTO camera.devices(device_id,display_name,device_kind) VALUES ('d1','카메라','CCTV');
INSERT INTO camera.video_sources(source_id,device_id,channel_key,display_name,transport,input_mode,motion_mode,primary_profile_id)
VALUES ('s1','d1','ch1','입구','RTSP','PULL','FIXED','main');
INSERT INTO camera.stream_profiles(source_id,profile_id,position,codec,width,height,fps) VALUES ('s1','main',1,'H264',1920,1080,30);`

func TestPostgresMigrationAndConstraints(t *testing.T) {
	s, ctx := testStore(t)
	var version string
	if err := s.pool.QueryRow(ctx, "SELECT version()").Scan(&version); err != nil {
		t.Fatal(err)
	}
	t.Log("database engine:", version)
	t.Run("apply_and_reapply", func(t *testing.T) {
		r, e := s.Migrate(ctx)
		if e != nil || r.Applied != 8 || r.Version != 8 {
			t.Fatalf("first: %+v %v", r, e)
		}
		r, e = s.Migrate(ctx)
		if e != nil || r.Applied != 0 || r.Version != 8 {
			t.Fatalf("again: %+v %v", r, e)
		}
	})
	if t.Failed() {
		return
	}
	if e := s.WithTx(ctx, func(tx pgx.Tx) error { _, e := tx.Exec(ctx, seed); return e }); e != nil {
		t.Fatal(e)
	}
	t.Run("one_device_multiple_channels_and_xr", func(t *testing.T) {
		e := s.WithTx(ctx, func(tx pgx.Tx) error {
			_, e := tx.Exec(ctx, `INSERT INTO camera.video_sources(source_id,device_id,channel_key,display_name,transport,input_mode,motion_mode,primary_profile_id) VALUES ('s2','d1','ch2','두 번째','RTSP','PULL','FIXED','main');
INSERT INTO camera.stream_profiles VALUES ('s2','main',1,'H264',1280,720,15);
INSERT INTO camera.devices(device_id,display_name,device_kind) VALUES ('xr1','스마트글래스','SMART_GLASSES');
INSERT INTO camera.video_sources(source_id,device_id,channel_key,display_name,transport,input_mode,motion_mode,primary_profile_id) VALUES ('sx','xr1','ch1','글래스 영상','WEBRTC','PUSH','MOVING','main');
INSERT INTO camera.stream_profiles VALUES ('sx','main',1,'H264',1280,720,30);`)
			return e
		})
		if e != nil {
			t.Fatal(e)
		}
	})
	cases := []struct{ name, sql, code string }{
		{"duplicate_device", `INSERT INTO camera.devices(device_id,display_name,device_kind) VALUES ('d1','dup','TEST')`, "23505"},
		{"unknown_parent", `INSERT INTO camera.video_sources(source_id,device_id,channel_key,display_name,transport,input_mode,motion_mode,primary_profile_id) VALUES ('bad','missing','x','bad','RTSP','PULL','FIXED','main')`, "23503"},
		{"duplicate_channel", `INSERT INTO camera.video_sources(source_id,device_id,channel_key,display_name,transport,input_mode,motion_mode,primary_profile_id) VALUES ('bad','d1','ch1','bad','RTSP','PULL','FIXED','main')`, "23505"},
		{"duplicate_profile", `INSERT INTO camera.stream_profiles VALUES ('s1','main',2,'H264',1280,720,30)`, "23505"},
		{"duplicate_position", `INSERT INTO camera.stream_profiles VALUES ('s1','sub',1,'H264',1280,720,30)`, "23505"},
		{"invalid_id", `INSERT INTO camera.devices(device_id,display_name,device_kind) VALUES ('../x','bad','TEST')`, "23514"},
		{"blank_name", `INSERT INTO camera.devices(device_id,display_name,device_kind) VALUES ('blank',E' \t\n','TEST')`, "23514"},
		{"missing_name", `INSERT INTO camera.devices(device_id,device_kind) VALUES ('null','TEST')`, "23502"},
		{"wrong_kind", `UPDATE camera.devices SET device_kind='INVALID' WHERE device_id='d1'`, "23514"},
		{"wrong_transport_pair", `UPDATE camera.video_sources SET input_mode='PUSH' WHERE source_id='s1'`, "23514"},
		{"invalid_version", `UPDATE camera.devices SET version=0 WHERE device_id='d1'`, "23514"},
		{"profile_fps_zero", `UPDATE camera.stream_profiles SET fps=0 WHERE source_id='s1'`, "23514"},
		{"profile_fps_nan", `UPDATE camera.stream_profiles SET fps='NaN' WHERE source_id='s1'`, "23514"},
		{"invalid_dimensions", `UPDATE camera.stream_profiles SET width=16385 WHERE source_id='s1'`, "23514"},
		{"profile_upper_bound", `INSERT INTO camera.stream_profiles VALUES ('s1','extra',9,'H264',1280,720,30)`, "23514"},
		{"parent_delete_restricted", `DELETE FROM camera.devices WHERE device_id='d1'`, "23503|23001"},
		{"profile_minimum_at_commit", `DELETE FROM camera.stream_profiles WHERE source_id='s1'`, "23503"},
		{"new_source_requires_profile", `INSERT INTO camera.video_sources(source_id,device_id,channel_key,display_name,transport,input_mode,motion_mode,primary_profile_id) VALUES ('empty','d1','empty','bad','RTSP','PULL','FIXED','main')`, "23503"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			err := s.WithTx(ctx, func(tx pgx.Tx) error { _, e := tx.Exec(ctx, c.sql); return e })
			if !strings.Contains("|"+c.code+"|", "|"+state(err)+"|") || state(err) == "" {
				t.Fatalf("expected %s got %s (%v)", c.code, state(err), err)
			}
		})
	}
	t.Run("callback_error_rolls_back", func(t *testing.T) {
		sentinel := errors.New("application failure")
		e := s.WithTx(ctx, func(tx pgx.Tx) error {
			if _, e := tx.Exec(ctx, "INSERT INTO camera.devices(device_id,display_name,device_kind) VALUES ('rollback','test','TEST')"); e != nil {
				return e
			}
			return sentinel
		})
		if !errors.Is(e, sentinel) {
			t.Fatal(e)
		}
		var count int
		if e = s.pool.QueryRow(ctx, "SELECT count(*) FROM camera.devices WHERE device_id='rollback'").Scan(&count); e != nil || count != 0 {
			t.Fatal("rollback failed", e)
		}
	})
	t.Run("public_has_no_schema_access", func(t *testing.T) {
		var allowed bool
		if e := s.pool.QueryRow(ctx, "SELECT EXISTS (SELECT 1 FROM pg_namespace n CROSS JOIN LATERAL aclexplode(COALESCE(n.nspacl, acldefault('n',n.nspowner))) a WHERE n.nspname='camera' AND a.grantee=0 AND a.privilege_type='USAGE')").Scan(&allowed); e != nil || allowed {
			t.Fatal("schema access not isolated", e)
		}
	})
	t.Run("history_checksum_rejected", func(t *testing.T) {
		_, e := s.pool.Exec(ctx, "UPDATE camera.schema_migrations SET checksum=repeat('0',64) WHERE version=1")
		if e != nil {
			t.Fatal(e)
		}
		if _, e = s.Migrate(ctx); e == nil || !strings.Contains(errorCodes(e), "MIGRATION_HISTORY_MISMATCH") {
			t.Fatal("modified history accepted", e)
		}
		m, _ := loadMigrations(migrationFiles)
		_, e = s.pool.Exec(ctx, "UPDATE camera.schema_migrations SET checksum=$1 WHERE version=1", m[0].checksum)
		if e != nil {
			t.Fatal(e)
		}
	})
	t.Run("future_version_rejected", func(t *testing.T) {
		_, e := s.pool.Exec(ctx, "INSERT INTO camera.schema_migrations VALUES (9,'future',repeat('0',64),CURRENT_TIMESTAMP)")
		if e != nil {
			t.Fatal(e)
		}
		if _, e = s.Migrate(ctx); e == nil {
			t.Fatal("future version accepted")
		}
		_, e = s.pool.Exec(ctx, "DELETE FROM camera.schema_migrations WHERE version=9")
		if e != nil {
			t.Fatal(e)
		}
	})
}

func errorCodes(err error) string {
	var out []string
	for err != nil {
		out = append(out, err.Error())
		err = errors.Unwrap(err)
	}
	return strings.Join(out, " ")
}

func TestPostgresMigrationFailureIsAtomic(t *testing.T) {
	s, ctx := testStore(t)
	m, _ := loadMigrations(migrationFiles)
	m = append(m, migration{name: "migrations/0009_failure.sql", sql: "CREATE TABLE camera.should_rollback(id integer); SELECT missing_column FROM camera.devices;", checksum: strings.Repeat("0", 64)})
	if _, e := s.migrate(ctx, m); e == nil {
		t.Fatal("bad SQL accepted")
	}
	var name *string
	if e := s.pool.QueryRow(ctx, "SELECT to_regclass('camera.devices')::text").Scan(&name); e != nil || name != nil {
		t.Fatal("migration partial state left", e)
	}
	if r, e := s.Migrate(ctx); e != nil || r.Applied != 8 {
		t.Fatal("retry failed", e)
	}
}

func TestPostgresConcurrentMigrations(t *testing.T) {
	if os.Getenv("CAMERA_TEST_ENGINE") == "pglite" {
		t.Skip("native concurrent sessions cannot be validated by PGlite")
	}
	s, ctx := testStore(t)
	var wg sync.WaitGroup
	results := make(chan MigrationResult, 2)
	errs := make(chan error, 2)
	for i := 0; i < 2; i++ {
		wg.Add(1)
		go func() { defer wg.Done(); r, e := s.Migrate(ctx); results <- r; errs <- e }()
	}
	wg.Wait()
	close(results)
	close(errs)
	for e := range errs {
		if e != nil {
			t.Fatal(e)
		}
	}
	applied := 0
	for r := range results {
		applied += r.Applied
		if r.Version != 8 {
			t.Fatal("wrong version")
		}
	}
	if applied != 8 {
		t.Fatal("migration executed more than once")
	}
}

func TestPostgresExistingTableNotOverwritten(t *testing.T) {
	s, ctx := testStore(t)
	if _, err := s.pool.Exec(ctx, "CREATE SCHEMA camera; CREATE TABLE camera.devices(existing_data text); INSERT INTO camera.devices VALUES ('preserve')"); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Migrate(ctx); err == nil {
		t.Fatal("conflicting schema accepted")
	}
	var value string
	if err := s.pool.QueryRow(ctx, "SELECT existing_data FROM camera.devices").Scan(&value); err != nil || value != "preserve" {
		t.Fatal("existing data lost", err)
	}
	var journal *string
	if err := s.pool.QueryRow(ctx, "SELECT to_regclass('camera.schema_migrations')::text").Scan(&journal); err != nil || journal != nil {
		t.Fatal("partial migration history left", err)
	}
}
