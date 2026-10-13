package storage

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"net/url"
	"os"
	"reflect"
	"testing"

	"vms.local/platform/camera/internal/contracts"
)

func TestNativeDeviceUpdateLeastPrivilege(t *testing.T) {
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
	for _, column := range []string{"device_id", "device_kind", "created_at", "deleted_at", "display_name", "version", "updated_at"} {
		var allowed bool
		if err := runtime.pool.QueryRow(ctx, "SELECT has_column_privilege(current_user,'camera.devices',$1,'UPDATE')", column).Scan(&allowed); err != nil {
			t.Fatal(err)
		}
		want := column == "display_name" || column == "version" || column == "updated_at" || column == "deleted_at"
		if allowed != want {
			t.Fatal("unexpected column privilege", column)
		}
	}
	var tableUpdate bool
	if err := runtime.pool.QueryRow(ctx, "SELECT has_table_privilege(current_user,'camera.devices','UPDATE')").Scan(&tableUpdate); err != nil || tableUpdate {
		t.Fatal("table-wide UPDATE granted", err)
	}
	created, _, err := runtime.CreateDevice(ctx, "p", "create", contracts.DeviceCreate{SchemaVersion: "v1", DeviceID: "parent", DisplayName: "original", DeviceKind: "TEST"})
	if err != nil {
		t.Fatal(err)
	}
	source, _, err := runtime.CreateSource(ctx, "p", "source", sourceInput("child", "ch1"))
	if err != nil {
		t.Fatal(err)
	}
	updated, _, err := runtime.UpdateDevice(ctx, "p", "update", "parent", updateInput(1, "renamed"))
	if err != nil || updated.Version != 2 {
		t.Fatal("column privileges insufficient for locked rename", err)
	}
	if original, replay, err := runtime.CreateDevice(ctx, "p", "create", contracts.DeviceCreate{SchemaVersion: "v1", DeviceID: "parent", DisplayName: "original", DeviceKind: "TEST"}); err != nil || !replay || !reflect.DeepEqual(original, created) {
		t.Fatal("create replay changed", err)
	}
	if got, err := runtime.GetSource(ctx, "child"); err != nil || !reflect.DeepEqual(got, source) {
		t.Fatal("child source changed", err)
	}
	for _, query := range []string{
		"UPDATE camera.devices SET device_id=device_id", "UPDATE camera.devices SET device_kind=device_kind",
		"UPDATE camera.devices SET created_at=created_at",
		"DELETE FROM camera.devices", "UPDATE camera.video_sources SET transport=transport",
		"UPDATE camera.stream_profiles SET fps=1", "UPDATE camera.device_update_requests SET response_body='{}'",
		"DELETE FROM camera.device_update_requests", "TRUNCATE camera.device_update_requests",
		"ALTER TABLE camera.devices ADD COLUMN forbidden int", "CREATE TABLE camera.forbidden(id int)",
	} {
		if _, err := runtime.pool.Exec(ctx, query); state(err) != "42501" {
			t.Fatal("forbidden mutation allowed or wrong failure", state(err))
		}
	}
	// Losing a success-journal INSERT must roll back the preceding rename.
	if _, err := s.pool.Exec(ctx, "REVOKE INSERT ON camera.device_update_requests FROM camera_runtime"); err != nil {
		t.Fatal(err)
	}
	if err := runtime.CheckReady(ctx); err == nil {
		t.Fatal("missing journal INSERT accepted")
	}
	if _, _, err := runtime.UpdateDevice(ctx, "p", "retry", "parent", updateInput(2, "after retry")); err == nil {
		t.Fatal("permission failure ignored")
	}
	if got, err := runtime.GetDevice(ctx, "parent"); err != nil || !reflect.DeepEqual(got, updated) {
		t.Fatal("rename survived missing journal privilege", err)
	}
	if _, err := s.pool.Exec(ctx, "GRANT INSERT ON camera.device_update_requests TO camera_runtime"); err != nil {
		t.Fatal(err)
	}
	third, replay, err := runtime.UpdateDevice(ctx, "p", "retry", "parent", updateInput(2, "after retry"))
	if err != nil || replay || third.Version != 3 {
		t.Fatal("same-key retry after grant restore failed", err)
	}
	for _, column := range []string{"display_name", "version", "updated_at"} {
		if _, err := s.pool.Exec(ctx, "REVOKE UPDATE ("+column+") ON camera.devices FROM camera_runtime"); err != nil {
			t.Fatal(err)
		}
		if err := runtime.CheckReady(ctx); err == nil {
			t.Fatal("missing mutable-column grant accepted", column)
		}
		if _, _, err := runtime.UpdateDevice(ctx, "p", "column-retry", "parent", updateInput(3, "final")); err == nil {
			t.Fatal("missing mutable-column grant ignored", column)
		}
		if got, err := runtime.GetDevice(ctx, "parent"); err != nil || !reflect.DeepEqual(got, third) {
			t.Fatal("partial update after privilege loss", err)
		}
		if _, err := s.pool.Exec(ctx, "GRANT UPDATE ("+column+") ON camera.devices TO camera_runtime"); err != nil {
			t.Fatal(err)
		}
	}
	if got, replay, err := runtime.UpdateDevice(ctx, "p", "column-retry", "parent", updateInput(3, "final")); err != nil || replay || got.Version != 4 {
		t.Fatal("column grant recovery failed", err)
	}
	if err := runtime.CheckReady(ctx); err != nil {
		t.Fatal(err)
	}
	t.Log("real runtime role rename, column-only UPDATE, forbidden mutations, readiness, privilege-loss rollback and retry passed")
}
