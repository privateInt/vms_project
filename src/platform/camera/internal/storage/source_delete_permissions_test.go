package storage

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"net/url"
	"os"
	"reflect"
	"testing"
)

func TestNativeSourceDeleteLeastPrivilege(t *testing.T) {
	if os.Getenv("CAMERA_TEST_ENGINE") == "pglite" {
		t.Skip("requires native PostgreSQL role authentication and privileges")
	}
	s, ctx := testStore(t)
	if _, err := s.Migrate(ctx); err != nil {
		t.Fatal(err)
	}
	var random [24]byte
	if _, err := rand.Read(random[:]); err != nil {
		t.Fatal(err)
	}
	password := hex.EncodeToString(random[:])
	if _, err := s.pool.Exec(ctx, "CREATE ROLE camera_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD '"+password+"'"); err != nil {
		t.Fatal("fresh runtime role required")
	}
	t.Cleanup(func() {
		_, _ = s.pool.Exec(context.Background(), "DROP OWNED BY camera_runtime")
		_, _ = s.pool.Exec(context.Background(), "DROP ROLE camera_runtime")
	})
	for i := 0; i < 2; i++ {
		if err := s.ProvisionRegistryRuntime(ctx); err != nil {
			t.Fatal(err)
		}
	}
	u, err := url.Parse(os.Getenv("CAMERA_TEST_DATABASE_URL"))
	if err != nil {
		t.Fatal("invalid test DSN")
	}
	u.User = url.UserPassword("camera_runtime", password)
	runtime, err := Open(ctx, u.String())
	if err != nil {
		t.Fatal("runtime authentication failed")
	}
	defer runtime.Close()
	if err := runtime.CheckReady(ctx); err != nil {
		t.Fatal(err)
	}
	var identity string
	if err := runtime.pool.QueryRow(ctx, "SELECT current_user").Scan(&identity); err != nil || identity != "camera_runtime" {
		t.Fatal("wrong runtime role", err)
	}
	for _, column := range []string{"source_id", "device_id", "channel_key", "display_name", "transport", "input_mode", "motion_mode", "primary_profile_id", "version", "created_at", "updated_at", "deleted_at"} {
		var allowed bool
		if err := runtime.pool.QueryRow(ctx, "SELECT has_column_privilege(current_user,'camera.video_sources',$1,'UPDATE')", column).Scan(&allowed); err != nil {
			t.Fatal(err)
		}
		want := column == "display_name" || column == "version" || column == "updated_at" || column == "deleted_at"
		if allowed != want {
			t.Fatal("wrong mutable column", column)
		}
	}
	for _, table := range []string{"video_sources", "stream_profiles", "source_delete_requests"} {
		for _, privilege := range []string{"UPDATE", "DELETE", "TRUNCATE", "TRIGGER"} {
			var allowed bool
			if err := runtime.pool.QueryRow(ctx, "SELECT has_table_privilege(current_user,$1,$2)", "camera."+table, privilege).Scan(&allowed); err != nil || allowed {
				t.Fatal("excess table privilege", table, privilege, err)
			}
		}
	}
	original := seedUpdateSource(t, runtime, ctx, "source", "ch1")
	profiles := sourceProfileState(t, runtime, ctx, "source")
	for _, query := range []string{
		"UPDATE camera.video_sources SET source_id=source_id", "UPDATE camera.video_sources SET device_id=device_id",
		"UPDATE camera.video_sources SET channel_key=channel_key", "UPDATE camera.video_sources SET created_at=created_at",
		"UPDATE camera.video_sources SET primary_profile_id=primary_profile_id", "DELETE FROM camera.video_sources",
		"TRUNCATE camera.video_sources", "UPDATE camera.stream_profiles SET fps=1", "DELETE FROM camera.stream_profiles",
		"UPDATE camera.source_delete_requests SET response_body='{}'", "DELETE FROM camera.source_delete_requests",
		"TRUNCATE camera.source_delete_requests", "DELETE FROM camera.source_update_requests", "DELETE FROM camera.source_create_requests",
		"ALTER TABLE camera.video_sources ADD COLUMN forbidden int", "CREATE TABLE camera.forbidden(id int)",
	} {
		if _, err := runtime.pool.Exec(ctx, query); state(err) != "42501" {
			t.Fatal("forbidden mutation accepted", query, state(err))
		}
	}
	// Lose each required grant, verify readiness and atomic failure, then retry
	// the same key. INSERT loss happens after the row mutation and must undo it.
	for _, privilege := range []string{
		"INSERT ON camera.source_delete_requests", "SELECT ON camera.source_delete_requests",
		"UPDATE (deleted_at) ON camera.video_sources", "UPDATE (version) ON camera.video_sources",
		"UPDATE (updated_at) ON camera.video_sources",
	} {
		if _, err := s.pool.Exec(ctx, "REVOKE "+privilege+" FROM camera_runtime"); err != nil {
			t.Fatal(err)
		}
		if runtime.CheckReady(ctx) == nil {
			t.Fatal("missing grant accepted", privilege)
		}
		_, _, err := runtime.DeleteSource(ctx, "p", "retry", "source", deleteInput(1), unusedSourceForTest)
		requireDeleteError(t, err, "DATABASE_UNAVAILABLE")
		if got, err := runtime.GetSource(ctx, "source"); err != nil || !reflect.DeepEqual(got, original) || sourceProfileState(t, runtime, ctx, "source") != profiles {
			t.Fatal("permission failure changed source", err)
		}
		var count int
		if err := s.pool.QueryRow(ctx, "SELECT count(*) FROM camera.source_delete_requests").Scan(&count); err != nil || count != 0 {
			t.Fatal("failed journal persisted", err)
		}
		if _, err := s.pool.Exec(ctx, "GRANT "+privilege+" TO camera_runtime"); err != nil {
			t.Fatal(err)
		}
	}
	got, replay, err := runtime.DeleteSource(ctx, "p", "retry", "source", deleteInput(1), unusedSourceForTest)
	if err != nil || replay || got.Version != 2 {
		t.Fatal("runtime delete failed", err)
	}
	if after, replay, err := runtime.DeleteSource(ctx, "p", "retry", "source", deleteInput(1), nil); err != nil || !replay || !reflect.DeepEqual(after, got) {
		t.Fatal("runtime replay failed", err)
	}
	if _, err := runtime.GetSource(ctx, "source"); err == nil {
		t.Fatal("tombstone visible")
	}
	if sourceProfileState(t, runtime, ctx, "source") != profiles {
		t.Fatal("profile changed")
	}
	if err := runtime.CheckReady(ctx); err != nil {
		t.Fatal(err)
	}
	t.Log("native role, column-only deletion grants, forbidden physical deletion and grant-loss rollback/retry passed")
}
