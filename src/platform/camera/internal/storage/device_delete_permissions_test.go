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

func TestNativeDeviceDeleteLeastPrivilege(t *testing.T) {
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
	for _, column := range []string{"device_id", "display_name", "device_kind", "version", "created_at", "updated_at", "deleted_at"} {
		var allowed bool
		if err := runtime.pool.QueryRow(ctx, "SELECT has_column_privilege(current_user,'camera.devices',$1,'UPDATE')", column).Scan(&allowed); err != nil {
			t.Fatal(err)
		}
		want := column == "display_name" || column == "version" || column == "updated_at" || column == "deleted_at"
		if allowed != want {
			t.Fatal("unexpected column privilege", column)
		}
	}
	for _, table := range []string{"devices", "device_delete_requests", "stream_profiles"} {
		for _, privilege := range []string{"UPDATE", "DELETE", "TRUNCATE", "TRIGGER"} {
			var allowed bool
			if err := runtime.pool.QueryRow(ctx, "SELECT has_table_privilege(current_user,$1,$2)", "camera."+table, privilege).Scan(&allowed); err != nil || allowed {
				t.Fatal("excess table privilege", table, privilege, err)
			}
		}
	}
	original := createDeleteDevice(t, runtime, ctx, "parent")
	if _, _, err := runtime.CreateSource(ctx, "p", "child", sourceInput("child", "ch1")); err != nil {
		t.Fatal(err)
	}
	if _, _, err := runtime.DeleteSource(ctx, "p", "child-delete", "child", deleteInput(1), unusedSourceForTest); err != nil {
		t.Fatal(err)
	}
	relations := preservedDeviceRelations(t, runtime, ctx)
	for _, query := range []string{
		"UPDATE camera.devices SET device_id=device_id", "UPDATE camera.devices SET device_kind=device_kind",
		"UPDATE camera.devices SET created_at=created_at", "DELETE FROM camera.devices", "TRUNCATE camera.devices",
		"UPDATE camera.device_delete_requests SET response_body='{}'", "DELETE FROM camera.device_delete_requests", "TRUNCATE camera.device_delete_requests",
		"DELETE FROM camera.device_create_requests", "DELETE FROM camera.device_update_requests",
		"DELETE FROM camera.video_sources", "DELETE FROM camera.stream_profiles", "UPDATE camera.stream_profiles SET fps=1",
		"ALTER TABLE camera.devices ADD COLUMN forbidden int", "CREATE TABLE camera.forbidden(id int)",
	} {
		if _, err := runtime.pool.Exec(ctx, query); state(err) != "42501" {
			t.Fatal("forbidden mutation accepted", query, state(err))
		}
	}
	for _, privilege := range []string{"INSERT ON camera.device_delete_requests", "SELECT ON camera.device_delete_requests", "UPDATE (deleted_at) ON camera.devices", "UPDATE (version) ON camera.devices", "UPDATE (updated_at) ON camera.devices"} {
		if _, err := s.pool.Exec(ctx, "REVOKE "+privilege+" FROM camera_runtime"); err != nil {
			t.Fatal(err)
		}
		if runtime.CheckReady(ctx) == nil {
			t.Fatal("lost grant accepted", privilege)
		}
		_, _, err := runtime.DeleteDevice(ctx, "p", "retry", "parent", deviceDeleteInput(1), unusedDeviceForTest)
		requireDeleteError(t, err, "DATABASE_UNAVAILABLE")
		if got, err := runtime.GetDevice(ctx, "parent"); err != nil || !reflect.DeepEqual(got, original) {
			t.Fatal("grant failure changed parent", err)
		}
		if preservedDeviceRelations(t, runtime, ctx) != relations {
			t.Fatal("grant failure changed protected rows")
		}
		var count int
		if err := s.pool.QueryRow(ctx, "SELECT count(*) FROM camera.device_delete_requests").Scan(&count); err != nil || count != 0 {
			t.Fatal("failed receipt persisted", err)
		}
		if _, err := s.pool.Exec(ctx, "GRANT "+privilege+" TO camera_runtime"); err != nil {
			t.Fatal(err)
		}
	}
	got, replay, err := runtime.DeleteDevice(ctx, "p", "retry", "parent", deviceDeleteInput(1), unusedDeviceForTest)
	if err != nil || replay || got.Version != 2 {
		t.Fatal("runtime deletion failed", err)
	}
	if again, replay, err := runtime.DeleteDevice(ctx, "p", "retry", "parent", deviceDeleteInput(1), nil); err != nil || !replay || !reflect.DeepEqual(again, got) {
		t.Fatal("runtime replay failed", err)
	}
	if preservedDeviceRelations(t, runtime, ctx) != relations {
		t.Fatal("runtime deletion changed protected rows")
	}
	if err := runtime.CheckReady(ctx); err != nil {
		t.Fatal(err)
	}
	t.Log("native role, column-only device deletion, protected rows and grant-loss rollback/retry passed")
}
