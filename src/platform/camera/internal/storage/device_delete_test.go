package storage

import (
	"context"
	"errors"
	"fmt"
	"math"
	"os"
	"reflect"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"vms.local/platform/camera/internal/contracts"
)

func deviceDeleteInput(version int64) contracts.DeviceDelete {
	return contracts.DeviceDelete{SchemaVersion: "v1", ExpectedVersion: version}
}

// Controlled fixture only: production usage admission belongs to the HTTP unit.
func unusedDeviceForTest(context.Context, pgx.Tx, string) (DeviceUsage, error) {
	return DeviceUsageUnused, nil
}

func createDeleteDevice(t *testing.T, s *Store, ctx context.Context, id string) contracts.Device {
	t.Helper()
	got, _, err := s.CreateDevice(ctx, "p", "create-"+id, contracts.DeviceCreate{SchemaVersion: "v1", DeviceID: id, DisplayName: "original", DeviceKind: "TEST"})
	if err != nil {
		t.Fatal(err)
	}
	return got
}

func preservedDeviceRelations(t *testing.T, s *Store, ctx context.Context) string {
	t.Helper()
	var value string
	// Preserve complete rows, including tombstones, timestamps and JSON receipts.
	if err := s.pool.QueryRow(ctx, `SELECT jsonb_build_object(
'sources',(SELECT coalesce(jsonb_agg(to_jsonb(v) ORDER BY source_id),'[]') FROM camera.video_sources v),
'profiles',(SELECT coalesce(jsonb_agg(to_jsonb(p) ORDER BY source_id,position),'[]') FROM camera.stream_profiles p),
'device_create',(SELECT coalesce(jsonb_agg(to_jsonb(r) ORDER BY principal,method,path,key_hash),'[]') FROM camera.device_create_requests r),
'device_update',(SELECT coalesce(jsonb_agg(to_jsonb(r) ORDER BY principal,method,path,key_hash),'[]') FROM camera.device_update_requests r),
'source_create',(SELECT coalesce(jsonb_agg(to_jsonb(r) ORDER BY principal,method,path,key_hash),'[]') FROM camera.source_create_requests r),
'source_update',(SELECT coalesce(jsonb_agg(to_jsonb(r) ORDER BY principal,method,path,key_hash),'[]') FROM camera.source_update_requests r),
'source_delete',(SELECT coalesce(jsonb_agg(to_jsonb(r) ORDER BY principal,method,path,key_hash),'[]') FROM camera.source_delete_requests r))::text`).Scan(&value); err != nil {
		t.Fatal(err)
	}
	return value
}

func TestDeviceDeleteUpgradePreservationAndReplay(t *testing.T) {
	s, ctx := testStore(t)
	m, _ := loadMigrations(migrationFiles)
	if _, err := s.migrate(ctx, m[:6]); err != nil {
		t.Fatal(err)
	}
	created := createDeleteDevice(t, s, ctx, "parent")
	tail := createDeleteDevice(t, s, ctx, "tail")
	updated, _, err := s.UpdateDevice(ctx, "p", "rename", "parent", updateInput(1, "renamed"))
	if err != nil {
		t.Fatal(err)
	}
	sourceInput := sourceInput("child", "ch1")
	child, _, err := s.CreateSource(ctx, "p", "child-create", sourceInput)
	if err != nil {
		t.Fatal(err)
	}
	childUpdate, _, err := s.UpdateSource(ctx, "p", "child-update", "child", sourceUpdateInput(1, "child renamed"))
	if err != nil {
		t.Fatal(err)
	}
	childDeletion, _, err := s.DeleteSource(ctx, "p", "child-delete", "child", deleteInput(2), unusedSourceForTest)
	if err != nil {
		t.Fatal(err)
	}
	relations := preservedDeviceRelations(t, s, ctx)
	var history string
	if err := s.pool.QueryRow(ctx, "SELECT json_agg(row_to_json(m) ORDER BY version)::text FROM camera.schema_migrations m").Scan(&history); err != nil {
		t.Fatal(err)
	}
	if s.CheckReady(ctx) == nil {
		t.Fatal("schema 6 accepted by schema 8 code")
	}
	for _, count := range []int{2, 0} {
		if result, err := s.Migrate(ctx); err != nil || result.Version != 8 || result.Applied != count {
			t.Fatal(result, err)
		}
	}
	if err := s.CheckReady(ctx); err != nil {
		t.Fatal(err)
	}
	var afterHistory string
	if err := s.pool.QueryRow(ctx, "SELECT json_agg(row_to_json(m) ORDER BY version)::text FROM camera.schema_migrations m WHERE version<=6").Scan(&afterHistory); err != nil || afterHistory != history {
		t.Fatal("old migration history changed", err)
	}
	got, replay, err := s.DeleteDevice(ctx, "p", "delete", "parent", deviceDeleteInput(2), unusedDeviceForTest)
	if err != nil || replay || got.DeviceID != "parent" || got.Version != 3 || got.SchemaVersion != "v1" || got.DeletedAt.Before(updated.UpdatedAt) {
		t.Fatal("device deletion failed", got, err)
	}
	var deletedAt, updatedAt time.Time
	if err := s.pool.QueryRow(ctx, "SELECT deleted_at,updated_at FROM camera.devices WHERE device_id='parent'").Scan(&deletedAt, &updatedAt); err != nil || !deletedAt.Equal(updatedAt) || !deletedAt.Equal(got.DeletedAt) {
		t.Fatal("unequal deletion timestamps", err)
	}
	tombstone, err := scanDevice(s.pool.QueryRow(ctx, "SELECT "+deviceColumns+" FROM camera.devices WHERE device_id='parent'"))
	if err != nil {
		t.Fatal(err)
	}
	tombstone.Version, tombstone.UpdatedAt = updated.Version, updated.UpdatedAt
	if !reflect.DeepEqual(tombstone, updated) || preservedDeviceRelations(t, s, ctx) != relations {
		t.Fatal("parent declaration, child, profile or history changed")
	}
	if other, err := s.GetDevice(ctx, "tail"); err != nil || !reflect.DeepEqual(other, tail) {
		t.Fatal("other parent changed", err)
	}
	_, err = s.GetDevice(ctx, "parent")
	requireDeleteError(t, err, "DEVICE_NOT_FOUND")
	for _, after := range []string{"", "parent"} {
		items, more, err := s.ListDevices(ctx, after, 1)
		if err != nil || more || len(items) != 1 || items[0].DeviceID != "tail" {
			t.Fatal("deleted cursor or device list changed", err)
		}
	}
	if items, more, err := s.ListSources(ctx, "", "parent", 1); err != nil || more || len(items) != 0 {
		t.Fatal("deleted parent source filter changed", err)
	}
	_, _, err = s.CreateDevice(ctx, "p", "new", contracts.DeviceCreate{SchemaVersion: "v1", DeviceID: "parent", DisplayName: "original", DeviceKind: "TEST"})
	requireDeleteError(t, err, "DEVICE_EXISTS")
	_, _, err = s.CreateSource(ctx, "p", "new", sourceInput)
	requireDeleteError(t, err, "DEVICE_UNAVAILABLE")
	_, _, err = s.UpdateDevice(ctx, "p", "new", "parent", updateInput(3, "restore"))
	requireDeleteError(t, err, "DEVICE_NOT_FOUND")
	s.Close()
	s, err = Open(ctx, os.Getenv("CAMERA_TEST_DATABASE_URL"))
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	if again, replay, err := s.DeleteDevice(ctx, "p", "delete", "parent", deviceDeleteInput(2), nil); err != nil || !replay || !reflect.DeepEqual(again, got) {
		t.Fatal("deletion receipt did not survive reconnect", err)
	}
	if again, replay, err := s.CreateDevice(ctx, "p", "create-parent", contracts.DeviceCreate{SchemaVersion: "v1", DeviceID: "parent", DisplayName: "original", DeviceKind: "TEST"}); err != nil || !replay || !reflect.DeepEqual(again, created) {
		t.Fatal("device POST snapshot lost", err)
	}
	if again, replay, err := s.UpdateDevice(ctx, "p", "rename", "parent", updateInput(1, "renamed")); err != nil || !replay || !reflect.DeepEqual(again, updated) {
		t.Fatal("device PATCH snapshot lost", err)
	}
	if again, replay, err := s.CreateSource(ctx, "p", "child-create", sourceInput); err != nil || !replay || !reflect.DeepEqual(again, child) {
		t.Fatal("child POST snapshot lost", err)
	}
	if again, replay, err := s.UpdateSource(ctx, "p", "child-update", "child", sourceUpdateInput(1, "child renamed")); err != nil || !replay || !reflect.DeepEqual(again, childUpdate) {
		t.Fatal("child PATCH snapshot lost", err)
	}
	if again, replay, err := s.DeleteSource(ctx, "p", "child-delete", "child", deleteInput(2), nil); err != nil || !replay || !reflect.DeepEqual(again, childDeletion) {
		t.Fatal("child DELETE snapshot lost", err)
	}
	_, _, err = s.DeleteDevice(ctx, "p", "delete", "parent", deviceDeleteInput(3), nil)
	requireDeleteError(t, err, "IDEMPOTENCY_CONFLICT")
	for _, principal := range []string{"p", "other"} {
		_, _, err = s.DeleteDevice(ctx, principal, "new-key", "parent", deviceDeleteInput(3), unusedDeviceForTest)
		requireDeleteError(t, err, "DEVICE_NOT_FOUND")
	}
	if preservedDeviceRelations(t, s, ctx) != relations {
		t.Fatal("replay resurrected or modified child rows")
	}
}

func TestDeviceDeleteAdmissionAndErrorOrder(t *testing.T) {
	s, ctx := testStore(t)
	if _, err := s.Migrate(ctx); err != nil {
		t.Fatal(err)
	}
	original := createDeleteDevice(t, s, ctx, "parent")
	if _, _, err := s.CreateSource(ctx, "p", "child", sourceInput("child", "ch1")); err != nil {
		t.Fatal(err)
	}
	_, _, err := s.DeleteDevice(ctx, "p", "attempt", "missing", deviceDeleteInput(1), nil)
	requireDeleteError(t, err, "DEVICE_NOT_FOUND")
	_, _, err = s.DeleteDevice(ctx, "p", "attempt", "parent", deviceDeleteInput(2), nil)
	requireDeleteError(t, err, "DEVICE_VERSION_CONFLICT")
	called := false
	guard := func(context.Context, pgx.Tx, string) (DeviceUsage, error) {
		called = true
		return DeviceUsageUnused, nil
	}
	_, _, err = s.DeleteDevice(ctx, "p", "attempt", "parent", deviceDeleteInput(1), guard)
	requireDeleteError(t, err, "DEVICE_HAS_ACTIVE_SOURCES")
	if called {
		t.Fatal("usage checked before child rejection")
	}
	if got, err := s.GetDevice(ctx, "parent"); err != nil || !reflect.DeepEqual(got, original) {
		t.Fatal("rejection changed parent", err)
	}
	if _, _, err := s.DeleteSource(ctx, "p", "child-delete", "child", deleteInput(1), unusedSourceForTest); err != nil {
		t.Fatal(err)
	}
	for _, test := range []struct {
		name  string
		guard DeviceDeleteGuard
		code  string
	}{
		{"nil", nil, "DEVICE_USAGE_UNAVAILABLE"},
		{"unknown", func(context.Context, pgx.Tx, string) (DeviceUsage, error) { return DeviceUsageUnknown, nil }, "DEVICE_USAGE_UNAVAILABLE"},
		{"invalid", func(context.Context, pgx.Tx, string) (DeviceUsage, error) { return DeviceUsage(99), nil }, "DEVICE_USAGE_UNAVAILABLE"},
		{"in_use", func(context.Context, pgx.Tx, string) (DeviceUsage, error) { return DeviceUsageInUse, nil }, "DEVICE_IN_USE"},
		{"error", func(context.Context, pgx.Tx, string) (DeviceUsage, error) {
			return DeviceUsageUnused, errors.New("sensitive admission error")
		}, "DEVICE_USAGE_UNAVAILABLE"},
	} {
		t.Run(test.name, func(t *testing.T) {
			_, _, err := s.DeleteDevice(ctx, "p", "attempt", "parent", deviceDeleteInput(1), test.guard)
			requireDeleteError(t, err, test.code)
			if got, err := s.GetDevice(ctx, "parent"); err != nil || !reflect.DeepEqual(got, original) {
				t.Fatal("usage rejection changed parent", err)
			}
		})
	}
	got, replay, err := s.DeleteDevice(ctx, "p", "attempt", "parent", deviceDeleteInput(1), unusedDeviceForTest)
	if err != nil || replay || got.Version != 2 {
		t.Fatal("failed key could not be retried", err)
	}
	// 'validate' remains a valid device identifier.
	createDeleteDevice(t, s, ctx, "validate")
	if got, _, err := s.DeleteDevice(ctx, "p", "attempt", "validate", deviceDeleteInput(1), unusedDeviceForTest); err != nil || got.DeviceID != "validate" {
		t.Fatal("existing identifier was reserved", err)
	}
}

func TestDeviceDeleteJournalFailureAndClockBounds(t *testing.T) {
	s, ctx := testStore(t)
	if _, err := s.Migrate(ctx); err != nil {
		t.Fatal(err)
	}
	original := createDeleteDevice(t, s, ctx, "parent")
	if _, err := s.pool.Exec(ctx, "ALTER TABLE camera.device_delete_requests ADD CONSTRAINT injected_failure CHECK(principal <> 'p')"); err != nil {
		t.Fatal(err)
	}
	_, _, err := s.DeleteDevice(ctx, "p", "retry", "parent", deviceDeleteInput(1), unusedDeviceForTest)
	requireDeleteError(t, err, "DATABASE_UNAVAILABLE")
	if got, err := s.GetDevice(ctx, "parent"); err != nil || !reflect.DeepEqual(got, original) {
		t.Fatal("tombstone survived failed journal", err)
	}
	var count int
	if err := s.pool.QueryRow(ctx, "SELECT count(*) FROM camera.device_delete_requests").Scan(&count); err != nil || count != 0 {
		t.Fatal("failed journal persisted", err)
	}
	if _, err := s.pool.Exec(ctx, "ALTER TABLE camera.device_delete_requests DROP CONSTRAINT injected_failure"); err != nil {
		t.Fatal(err)
	}
	if got, replay, err := s.DeleteDevice(ctx, "p", "retry", "parent", deviceDeleteInput(1), unusedDeviceForTest); err != nil || replay || got.Version != 2 {
		t.Fatal("journal failure retry failed", err)
	}
	createDeleteDevice(t, s, ctx, "edge")
	createDeleteDevice(t, s, ctx, "full")
	if _, err := s.pool.Exec(ctx, "UPDATE camera.devices SET version=$1,updated_at=clock_timestamp()+interval '1 day' WHERE device_id='edge'", int64(math.MaxInt64-1)); err != nil {
		t.Fatal(err)
	}
	before, err := s.GetDevice(ctx, "edge")
	if err != nil {
		t.Fatal(err)
	}
	got, _, err := s.DeleteDevice(ctx, "p", "edge", "edge", deviceDeleteInput(math.MaxInt64-1), unusedDeviceForTest)
	if err != nil || got.Version != math.MaxInt64 || !got.DeletedAt.Equal(before.UpdatedAt) {
		t.Fatal("clock or exact int64 bound failed", err)
	}
	if _, err := s.pool.Exec(ctx, "UPDATE camera.devices SET version=$1 WHERE device_id='full'", int64(math.MaxInt64)); err != nil {
		t.Fatal(err)
	}
	_, _, err = s.DeleteDevice(ctx, "p", "full", "full", deviceDeleteInput(math.MaxInt64), nil)
	requireDeleteError(t, err, "DEVICE_VERSION_EXHAUSTED")
}

func TestDeviceDeleteReceiptConstraintsAndInputs(t *testing.T) {
	s, ctx := testStore(t)
	if _, err := s.Migrate(ctx); err != nil {
		t.Fatal(err)
	}
	for _, input := range []contracts.DeviceDelete{{}, {SchemaVersion: "v2", ExpectedVersion: 1}, {SchemaVersion: "v1", ExpectedVersion: 0}} {
		_, _, err := s.DeleteDevice(ctx, "p", "k", "device", input, unusedDeviceForTest)
		requireDeleteError(t, err, "CONTRACT_INVALID")
	}
	for _, args := range [][3]string{{"", "k", "device"}, {"p", "bad key", "device"}, {"p", "k", "../device"}} {
		_, _, err := s.DeleteDevice(ctx, args[0], args[1], args[2], deviceDeleteInput(1), unusedDeviceForTest)
		requireDeleteError(t, err, "CONTRACT_INVALID")
	}
	query := "INSERT INTO camera.device_delete_requests(principal,method,path,key_hash,request_hash,response_body) VALUES ('p',$1,$2,$3,$4,$5::jsonb)"
	valid := []any{"DELETE", "/api/v1/devices/validate", hashText([]byte("k")), hashText([]byte("body")), `{}`}
	for _, test := range []struct {
		index int
		value any
	}{{0, "PATCH"}, {1, "/api/v1/sources/device"}, {1, "/api/v1/devices/a/b"}, {2, "raw-key"}, {3, "bad"}, {4, `[]`}} {
		args := append([]any(nil), valid...)
		args[test.index] = test.value
		if _, err := s.pool.Exec(ctx, query, args...); state(err) != "23514" {
			t.Fatal("invalid receipt accepted", test.index, state(err))
		}
	}
	if _, err := s.pool.Exec(ctx, query, valid...); err != nil {
		t.Fatal("validate path rejected", err)
	}
	if _, err := s.pool.Exec(ctx, query, valid...); state(err) != "23505" {
		t.Fatal("duplicate receipt accepted", state(err))
	}
}

func TestDeviceDeleteReadCommittedOverridesConnectionDefault(t *testing.T) {
	if os.Getenv("CAMERA_TEST_ENGINE") == "pglite" {
		t.Skip("requires native PostgreSQL connection settings")
	}
	s, ctx := testStore(t)
	config := s.pool.Config()
	config.ConnConfig.RuntimeParams["default_transaction_isolation"] = "repeatable read"
	pool, err := pgxpool.NewWithConfig(ctx, config)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	other := &Store{pool: pool}
	if err := other.WithTx(ctx, func(tx pgx.Tx) error {
		var isolation string
		if err := tx.QueryRow(ctx, "SHOW transaction_isolation").Scan(&isolation); err != nil {
			return err
		}
		if isolation != "read committed" {
			return fmt.Errorf("unexpected transaction isolation: %s", isolation)
		}
		return nil
	}); err != nil {
		t.Fatal(err)
	}
}
