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

func TestNativeSourceUpdateLeastPrivilege(t *testing.T) {
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
	// The native runner creates a disposable PostgreSQL cluster. Refuse an
	// existing role rather than altering somebody else's identity or grants.
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
		t.Fatal("test DSN invalid")
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
		t.Fatal("wrong runtime identity", err)
	}
	for _, column := range []string{"source_id", "device_id", "channel_key", "transport", "input_mode", "motion_mode", "primary_profile_id", "created_at", "deleted_at", "display_name", "version", "updated_at"} {
		var allowed bool
		if err := runtime.pool.QueryRow(ctx, "SELECT has_column_privilege(current_user,'camera.video_sources',$1,'UPDATE')", column).Scan(&allowed); err != nil {
			t.Fatal(err)
		}
		want := column == "display_name" || column == "version" || column == "updated_at" || column == "deleted_at"
		if allowed != want {
			t.Fatal("wrong column privilege", column)
		}
	}
	for _, table := range []string{"video_sources", "stream_profiles", "source_update_requests"} {
		var allowed bool
		if err := runtime.pool.QueryRow(ctx, "SELECT has_table_privilege(current_user,$1,'UPDATE')", "camera."+table).Scan(&allowed); err != nil || allowed {
			t.Fatal("table-wide UPDATE granted", table, err)
		}
	}
	original := seedUpdateSource(t, runtime, ctx, "source", "ch1")
	sibling := seedUpdateSource(t, runtime, ctx, "sibling", "ch2")
	parent, _, err := runtime.UpdateDevice(ctx, "p", "update", "parent", updateInput(1, "parent renamed"))
	if err != nil || parent.Version != 2 {
		t.Fatal("device update grants regressed", err)
	}
	updated, _, err := runtime.UpdateSource(ctx, "p", "update", "source", sourceUpdateInput(1, "renamed"))
	if err != nil || updated.Version != 2 {
		t.Fatal("source column grants insufficient", err)
	}
	if got, replay, err := runtime.CreateSource(ctx, "p", "create-source", sourceInput("source", "ch1")); err != nil || !replay || !reflect.DeepEqual(got, original) {
		t.Fatal("POST snapshot changed", err)
	}
	if got, err := runtime.GetSource(ctx, "sibling"); err != nil || !reflect.DeepEqual(got, sibling) {
		t.Fatal("sibling changed", err)
	}
	if got, err := runtime.GetDevice(ctx, "parent"); err != nil || !reflect.DeepEqual(got, parent) {
		t.Fatal("parent changed", err)
	}
	for _, query := range []string{
		"UPDATE camera.video_sources SET source_id=source_id", "UPDATE camera.video_sources SET device_id=device_id",
		"UPDATE camera.video_sources SET channel_key=channel_key", "UPDATE camera.video_sources SET transport=transport",
		"UPDATE camera.video_sources SET input_mode=input_mode", "UPDATE camera.video_sources SET motion_mode=motion_mode",
		"UPDATE camera.video_sources SET primary_profile_id=primary_profile_id", "UPDATE camera.video_sources SET created_at=created_at",
		"DELETE FROM camera.video_sources", "TRUNCATE camera.video_sources",
		"UPDATE camera.stream_profiles SET fps=1", "UPDATE camera.stream_profiles SET position=position", "DELETE FROM camera.stream_profiles",
		"UPDATE camera.source_update_requests SET response_body='{}'", "DELETE FROM camera.source_update_requests", "TRUNCATE camera.source_update_requests",
		"UPDATE camera.source_create_requests SET response_body='{}'", "UPDATE camera.devices SET device_kind='TEST'",
		"ALTER TABLE camera.video_sources ADD COLUMN forbidden int", "CREATE TABLE camera.forbidden(id int)",
	} {
		if _, err := runtime.pool.Exec(ctx, query); state(err) != "42501" {
			t.Fatal("forbidden mutation allowed or wrong failure", query, state(err))
		}
	}
	// A response-journal failure must undo the preceding name/version change.
	if _, err := s.pool.Exec(ctx, "REVOKE INSERT ON camera.source_update_requests FROM camera_runtime"); err != nil {
		t.Fatal(err)
	}
	if runtime.CheckReady(ctx) == nil {
		t.Fatal("missing journal grant accepted")
	}
	if _, _, err := runtime.UpdateSource(ctx, "p", "retry", "source", sourceUpdateInput(2, "after retry")); err == nil {
		t.Fatal("permission failure ignored")
	}
	if got, err := runtime.GetSource(ctx, "source"); err != nil || !reflect.DeepEqual(got, updated) {
		t.Fatal("partial source update", err)
	}
	if _, err := s.pool.Exec(ctx, "GRANT INSERT ON camera.source_update_requests TO camera_runtime"); err != nil {
		t.Fatal(err)
	}
	third, replay, err := runtime.UpdateSource(ctx, "p", "retry", "source", sourceUpdateInput(2, "after retry"))
	if err != nil || replay || third.Version != 3 {
		t.Fatal("grant recovery failed", err)
	}
	for _, column := range []string{"display_name", "version", "updated_at"} {
		if _, err := s.pool.Exec(ctx, "REVOKE UPDATE ("+column+") ON camera.video_sources FROM camera_runtime"); err != nil {
			t.Fatal(err)
		}
		if runtime.CheckReady(ctx) == nil {
			t.Fatal("missing column grant accepted", column)
		}
		if _, _, err := runtime.UpdateSource(ctx, "p", "column-retry", "source", sourceUpdateInput(3, "final")); err == nil {
			t.Fatal("column privilege failure ignored", column)
		}
		if got, err := runtime.GetSource(ctx, "source"); err != nil || !reflect.DeepEqual(got, third) {
			t.Fatal("partial update after column grant loss", err)
		}
		if _, err := s.pool.Exec(ctx, "GRANT UPDATE ("+column+") ON camera.video_sources TO camera_runtime"); err != nil {
			t.Fatal(err)
		}
	}
	if _, err := s.pool.Exec(ctx, "REVOKE SELECT ON camera.source_update_requests FROM camera_runtime"); err != nil {
		t.Fatal(err)
	}
	if runtime.CheckReady(ctx) == nil {
		t.Fatal("missing journal SELECT accepted")
	}
	if _, _, err := runtime.UpdateSource(ctx, "p", "column-retry", "source", sourceUpdateInput(3, "final")); err == nil {
		t.Fatal("missing journal SELECT ignored")
	}
	if _, err := s.pool.Exec(ctx, "GRANT SELECT ON camera.source_update_requests TO camera_runtime"); err != nil {
		t.Fatal(err)
	}
	if got, replay, err := runtime.UpdateSource(ctx, "p", "column-retry", "source", sourceUpdateInput(3, "final")); err != nil || replay || got.Version != 4 {
		t.Fatal("same-key column recovery failed", err)
	}
	if err := runtime.CheckReady(ctx); err != nil {
		t.Fatal(err)
	}
	t.Log("native source rename, column-only grants, immutable/profile protection, permission-loss rollback/retry and device PATCH regression passed")
}
