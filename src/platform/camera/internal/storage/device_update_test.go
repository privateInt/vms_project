package storage

import (
	"context"
	"fmt"
	"math"
	"os"
	"reflect"
	"sync"
	"testing"

	"vms.local/platform/camera/internal/contracts"
)

func updateInput(version int64, name string) contracts.DeviceUpdate {
	return contracts.DeviceUpdate{SchemaVersion: "v1", ExpectedVersion: version, DisplayName: name}
}

func TestDeviceUpdateSchemaUpgradeAndReplay(t *testing.T) {
	s, ctx := testStore(t)
	m, _ := loadMigrations(migrationFiles)
	if _, err := s.migrate(ctx, m[:3]); err != nil {
		t.Fatal(err)
	}
	createdInput := contracts.DeviceCreate{SchemaVersion: "v1", DeviceID: "parent", DisplayName: "기존 장치", DeviceKind: "CCTV"}
	original, _, err := s.CreateDevice(ctx, "p", "same-key", createdInput)
	if err != nil {
		t.Fatal(err)
	}
	source, _, err := s.CreateSource(ctx, "p", "source-key", sourceInput("source", "channel"))
	if err != nil {
		t.Fatal(err)
	}
	if err = s.CheckReady(ctx); err == nil {
		t.Fatal("schema 3 accepted by schema 6 code")
	}
	if result, err := s.Migrate(ctx); err != nil || result.Version != 8 || result.Applied != 5 {
		t.Fatal(result, err)
	}
	if result, err := s.Migrate(ctx); err != nil || result.Applied != 0 {
		t.Fatal(result, err)
	}
	if err = s.CheckReady(ctx); err != nil {
		t.Fatal(err)
	}
	input := updateInput(1, "  출입구 장치  ")
	updated, replay, err := s.UpdateDevice(ctx, "p", "same-key", "parent", input)
	if err != nil || replay || updated.Version != 2 || updated.DisplayName != input.DisplayName || updated.DeviceID != original.DeviceID || updated.DeviceKind != original.DeviceKind || !updated.CreatedAt.Equal(original.CreatedAt) || updated.UpdatedAt.Before(original.UpdatedAt) {
		t.Fatal("rename did not preserve immutable fields or advance version", err)
	}
	if got, err := s.GetDevice(ctx, "parent"); err != nil || !reflect.DeepEqual(got, updated) {
		t.Fatal("get did not return current device", err)
	}
	if items, _, err := s.ListDevices(ctx, "", 10); err != nil || len(items) != 1 || !reflect.DeepEqual(items[0], updated) {
		t.Fatal("list did not return current device", err)
	}
	if got, err := s.GetSource(ctx, "source"); err != nil || !reflect.DeepEqual(got, source) {
		t.Fatal("child source/profile changed", err)
	}
	if got, replay, err := s.CreateDevice(ctx, "p", "same-key", createdInput); err != nil || !replay || !reflect.DeepEqual(got, original) {
		t.Fatal("POST replay changed or conflicted with PATCH", err)
	}
	second, replay, err := s.UpdateDevice(ctx, "p", "second", "parent", updateInput(2, "다음 이름"))
	if err != nil || replay || second.Version != 3 {
		t.Fatal(second, err)
	}
	// Close and reopen the pool to ensure no in-memory request cache is needed.
	s.Close()
	s, err = Open(ctx, os.Getenv("CAMERA_TEST_DATABASE_URL"))
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	if got, replay, err := s.UpdateDevice(ctx, "p", "same-key", "parent", input); err != nil || !replay || !reflect.DeepEqual(got, updated) {
		t.Fatal("original PATCH snapshot lost after later update/reopen", err)
	}
	if got, err := s.GetDevice(ctx, "parent"); err != nil || !reflect.DeepEqual(got, second) {
		t.Fatal("historical replay rolled back current device", err)
	}
	for _, changed := range []contracts.DeviceUpdate{updateInput(2, input.DisplayName), updateInput(1, "changed")} {
		if _, _, err := s.UpdateDevice(ctx, "p", "same-key", "parent", changed); err == nil || err.Error() != "IDEMPOTENCY_CONFLICT" {
			t.Fatal("different request under same key accepted", err)
		}
	}
	if _, _, err := s.UpdateDevice(ctx, "other-principal", "same-key", "parent", input); err == nil || err.Error() != "DEVICE_VERSION_CONFLICT" {
		t.Fatal("principal scope incorrectly replayed", err)
	}
	other := createdInput
	other.DeviceID = "other"
	if _, _, err := s.CreateDevice(ctx, "p", "create-other", other); err != nil {
		t.Fatal(err)
	}
	if got, replay, err := s.UpdateDevice(ctx, "p", "same-key", "other", input); err != nil || replay || got.DeviceID != "other" {
		t.Fatal("path scope not independent", err)
	}
	t.Log("schema 3->6 preserves device/source/create replay; rename/get/list and durable historical PATCH replay passed")
}

func TestDeviceUpdateErrorsAndAtomicity(t *testing.T) {
	s, ctx := testStore(t)
	if _, err := s.Migrate(ctx); err != nil {
		t.Fatal(err)
	}
	create := contracts.DeviceCreate{SchemaVersion: "v1", DeviceID: "device", DisplayName: "original", DeviceKind: "TEST"}
	original, _, err := s.CreateDevice(ctx, "p", "create", create)
	if err != nil {
		t.Fatal(err)
	}
	input := updateInput(1, "new")
	for _, c := range []struct {
		id      string
		version int64
		code    string
	}{
		{"absent", 1, "DEVICE_NOT_FOUND"}, {"device", 2, "DEVICE_VERSION_CONFLICT"},
	} {
		if _, _, err := s.UpdateDevice(ctx, "p", "attempt", c.id, updateInput(c.version, "new")); err == nil || err.Error() != c.code {
			t.Fatal("wrong error", err)
		}
	}
	if _, err := s.pool.Exec(ctx, `ALTER TABLE camera.device_update_requests ADD CONSTRAINT injected_failure CHECK(principal <> 'fail')`); err != nil {
		t.Fatal(err)
	}
	if _, _, err := s.UpdateDevice(ctx, "fail", "attempt", "device", input); err == nil {
		t.Fatal("injected response failure accepted")
	}
	if got, err := s.GetDevice(ctx, "device"); err != nil || !reflect.DeepEqual(got, original) {
		t.Fatal("partial update survived response failure", err)
	}
	var count int
	if err := s.pool.QueryRow(ctx, "SELECT count(*) FROM camera.device_update_requests").Scan(&count); err != nil || count != 0 {
		t.Fatal("failed attempt left a success journal", err)
	}
	if _, err := s.pool.Exec(ctx, `ALTER TABLE camera.device_update_requests DROP CONSTRAINT injected_failure`); err != nil {
		t.Fatal(err)
	}
	updated, replay, err := s.UpdateDevice(ctx, "fail", "attempt", "device", input)
	if err != nil || replay || updated.Version != 2 {
		t.Fatal("same-key retry after failed transaction did not succeed", err)
	}
	// Matching values still represent a new version-checked command.
	if same, replay, err := s.UpdateDevice(ctx, "p", "same-name", "device", updateInput(2, "new")); err != nil || replay || same.Version != 3 {
		t.Fatal("same-name command did not advance version", err)
	}
	if _, err := s.pool.Exec(ctx, `UPDATE camera.devices SET deleted_at=clock_timestamp() WHERE device_id='device'`); err != nil {
		t.Fatal(err)
	}
	if _, _, err := s.UpdateDevice(ctx, "p", "new-request", "device", updateInput(3, "rename")); err == nil || err.Error() != "DEVICE_NOT_FOUND" {
		t.Fatal("tombstone updated", err)
	}
	if historical, replay, err := s.UpdateDevice(ctx, "fail", "attempt", "device", input); err != nil || !replay || !reflect.DeepEqual(historical, updated) {
		t.Fatal("prior success must remain replayable without resurrecting device", err)
	}
	t.Log("version conflict, tombstone, response-write rollback, same-key retry and same-name version advance passed")
}

func TestDeviceUpdateVersionAndClockBounds(t *testing.T) {
	s, ctx := testStore(t)
	if _, err := s.Migrate(ctx); err != nil {
		t.Fatal(err)
	}
	if _, err := s.pool.Exec(ctx, `INSERT INTO camera.devices(device_id,display_name,device_kind,version,updated_at) VALUES ('edge','original','TEST',$1,clock_timestamp()+interval '1 day')`, int64(math.MaxInt64-1)); err != nil {
		t.Fatal(err)
	}
	before, err := s.GetDevice(ctx, "edge")
	if err != nil {
		t.Fatal(err)
	}
	got, _, err := s.UpdateDevice(ctx, "p", "last", "edge", updateInput(math.MaxInt64-1, "last"))
	if err != nil || got.Version != math.MaxInt64 || got.UpdatedAt.Before(before.UpdatedAt) {
		t.Fatal("version or clock boundary", err)
	}
	if _, _, err := s.UpdateDevice(ctx, "p", "overflow", "edge", updateInput(math.MaxInt64, "overflow")); err == nil || err.Error() != "DEVICE_VERSION_EXHAUSTED" {
		t.Fatal("overflow not rejected", err)
	}
	if after, err := s.GetDevice(ctx, "edge"); err != nil || !reflect.DeepEqual(after, got) {
		t.Fatal("overflow modified device", err)
	}
}

func TestDeviceUpdateValidatesBeforeDatabaseAccess(t *testing.T) {
	s := &Store{}
	for _, c := range []struct {
		principal, key, id string
		input              contracts.DeviceUpdate
	}{
		{"", "key", "device", updateInput(1, "name")}, {"p", " ", "device", updateInput(1, "name")},
		{"p", "key", "../device", updateInput(1, "name")}, {"p", "key", "device", updateInput(0, "name")},
		{"p", "key", "device", updateInput(1, "\x00")},
	} {
		if _, _, err := s.UpdateDevice(context.Background(), c.principal, c.key, c.id, c.input); err == nil || err.Error() != "CONTRACT_INVALID" {
			t.Fatal("invalid storage call was not rejected", err)
		}
	}
}

func TestNativeConcurrentDeviceUpdate(t *testing.T) {
	if os.Getenv("CAMERA_TEST_ENGINE") == "pglite" {
		t.Skip("requires native PostgreSQL concurrent sessions")
	}
	s, ctx := testStore(t)
	if _, err := s.Migrate(ctx); err != nil {
		t.Fatal(err)
	}
	if _, _, err := s.CreateDevice(ctx, "p", "create", contracts.DeviceCreate{SchemaVersion: "v1", DeviceID: "race", DisplayName: "race", DeviceKind: "TEST"}); err != nil {
		t.Fatal(err)
	}
	type outcome struct {
		device contracts.Device
		replay bool
		err    error
	}
	run := func(version int64, sameKey, differentBody bool) []outcome {
		var wg sync.WaitGroup
		start := make(chan struct{})
		out := make(chan outcome, 8)
		for i := 0; i < 8; i++ {
			wg.Add(1)
			go func(i int) {
				defer wg.Done()
				key, name := fmt.Sprintf("v%d-key%d", version, i), "name"
				if sameKey {
					key = fmt.Sprintf("v%d-shared", version)
				}
				if differentBody {
					name = fmt.Sprintf("name%d", i)
				}
				<-start
				d, replay, err := s.UpdateDevice(ctx, "p", key, "race", updateInput(version, name))
				out <- outcome{d, replay, err}
			}(i)
		}
		close(start)
		wg.Wait()
		close(out)
		var results []outcome
		for result := range out {
			results = append(results, result)
		}
		return results
	}
	for _, scenario := range []struct {
		version                int64
		sameKey, differentBody bool
		conflicts              int
		code                   string
	}{
		{1, true, false, 0, ""}, {2, false, true, 7, "DEVICE_VERSION_CONFLICT"}, {3, true, true, 7, "IDEMPOTENCY_CONFLICT"},
	} {
		first, replayed, conflicts := 0, 0, 0
		var snapshot *contracts.Device
		for _, out := range run(scenario.version, scenario.sameKey, scenario.differentBody) {
			if out.err != nil {
				if out.err.Error() != scenario.code {
					t.Fatal(out.err)
				}
				conflicts++
			} else {
				if out.replay {
					replayed++
				} else {
					first++
				}
				if out.device.Version != scenario.version+1 {
					t.Fatal("wrong version")
				}
				if snapshot != nil && !reflect.DeepEqual(*snapshot, out.device) {
					t.Fatal("same-key snapshots differ")
				}
				value := out.device
				snapshot = &value
			}
		}
		if first != 1 || conflicts != scenario.conflicts || replayed != 7-scenario.conflicts {
			t.Fatal("unexpected concurrent outcomes", first, replayed, conflicts)
		}
	}
	var count int
	if err := s.pool.QueryRow(ctx, "SELECT count(*) FROM camera.device_update_requests").Scan(&count); err != nil || count != 3 {
		t.Fatal("unexpected successful request count", err)
	}
	t.Log("same-key parallel replay, competing versions and parallel conflicting key bodies passed")
}
