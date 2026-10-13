package storage

import (
	"context"
	"errors"
	"os"
	"reflect"
	"sync"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
	"vms.local/platform/camera/internal/contracts"
)

type deviceDeleteOutcome struct {
	value  contracts.DeviceDeletion
	replay bool
	err    error
}

// Observe a real server lock wait instead of assuming goroutine scheduling.
func waitDeviceBlockedPID(t *testing.T, s *Store, ctx context.Context, blocker int32) int32 {
	t.Helper()
	deadline := time.NewTimer(5 * time.Second)
	defer deadline.Stop()
	tick := time.NewTicker(10 * time.Millisecond)
	defer tick.Stop()
	for {
		var pid int32
		err := s.pool.QueryRow(ctx, "SELECT pid FROM pg_stat_activity WHERE $1=ANY(pg_blocking_pids(pid)) LIMIT 1", blocker).Scan(&pid)
		if err == nil {
			return pid
		}
		if !errors.Is(err, pgx.ErrNoRows) {
			t.Fatal(err)
		}
		select {
		case <-ctx.Done():
			t.Fatal("lock observation cancelled")
		case <-deadline.C:
			t.Fatal("competing transaction did not reach shared lock")
		case <-tick.C:
		}
	}
}

func TestNativeDeviceDeleteConcurrentReceipts(t *testing.T) {
	if os.Getenv("CAMERA_TEST_ENGINE") == "pglite" {
		t.Skip("requires native PostgreSQL concurrent sessions")
	}
	s, ctx := testStore(t)
	if _, err := s.Migrate(ctx); err != nil {
		t.Fatal(err)
	}
	for _, sameKey := range []bool{true, false} {
		id := "different"
		if sameKey {
			id = "same"
		}
		createDeleteDevice(t, s, ctx, id)
		start := make(chan struct{})
		results := make(chan deviceDeleteOutcome, 2)
		for i := 0; i < 2; i++ {
			key := "a"
			if i == 1 && !sameKey {
				key = "b"
			}
			go func(key string) {
				<-start
				value, replay, err := s.DeleteDevice(ctx, "p", key, id, deviceDeleteInput(1), unusedDeviceForTest)
				results <- deviceDeleteOutcome{value, replay, err}
			}(key)
		}
		close(start)
		first, second := <-results, <-results
		if first.err != nil {
			first, second = second, first
		}
		if first.err != nil || first.value.Version != 2 {
			t.Fatal("no successful deletion", first.err)
		}
		if sameKey {
			if second.err != nil || first.replay == second.replay || !reflect.DeepEqual(first.value, second.value) {
				t.Fatal("same key was not exactly one mutation plus replay", second.err)
			}
		} else {
			requireDeleteError(t, second.err, "DEVICE_NOT_FOUND")
		}
		var version int64
		if err := s.pool.QueryRow(ctx, "SELECT version FROM camera.devices WHERE device_id=$1", id).Scan(&version); err != nil || version != 2 {
			t.Fatal("concurrent deletion changed version twice", err)
		}
	}
}

func TestNativeDeviceDeleteWinsAgainstSourceCreation(t *testing.T) {
	if os.Getenv("CAMERA_TEST_ENGINE") == "pglite" {
		t.Skip("requires native PostgreSQL concurrent sessions")
	}
	for _, rollback := range []bool{false, true} {
		name := "commit"
		if rollback {
			name = "rollback"
		}
		t.Run(name, func(t *testing.T) {
			s, ctx := testStore(t)
			if _, err := s.Migrate(ctx); err != nil {
				t.Fatal(err)
			}
			createDeleteDevice(t, s, ctx, "parent")
			entered := make(chan int32, 1)
			release := make(chan struct{})
			var once sync.Once
			unblock := func() { once.Do(func() { close(release) }) }
			t.Cleanup(unblock)
			guard := func(ctx context.Context, tx pgx.Tx, id string) (DeviceUsage, error) {
				var pid int32
				if err := tx.QueryRow(ctx, "SELECT pg_backend_pid()").Scan(&pid); err != nil {
					return DeviceUsageUnknown, err
				}
				entered <- pid
				select {
				case <-release:
				case <-ctx.Done():
					return DeviceUsageUnknown, ctx.Err()
				}
				if rollback {
					return DeviceUsageUnknown, errors.New("injected admission rollback")
				}
				return DeviceUsageUnused, nil
			}
			deleted := make(chan deviceDeleteOutcome, 1)
			go func() {
				value, replay, err := s.DeleteDevice(ctx, "p", "delete", "parent", deviceDeleteInput(1), guard)
				deleted <- deviceDeleteOutcome{value, replay, err}
			}()
			var pid int32
			select {
			case pid = <-entered:
			case <-ctx.Done():
				t.Fatal("guard never entered")
			}
			created := make(chan error, 1)
			go func() { _, _, err := s.CreateSource(ctx, "p", "source", sourceInput("child", "ch1")); created <- err }()
			waitDeviceBlockedPID(t, s, ctx, pid)
			unblock()
			deletion, sourceError := <-deleted, <-created
			if rollback {
				requireDeleteError(t, deletion.err, "DEVICE_USAGE_UNAVAILABLE")
				if sourceError != nil {
					t.Fatal("rollback did not admit source", sourceError)
				}
			} else {
				if deletion.err != nil {
					t.Fatal(deletion.err)
				}
				requireDeleteError(t, sourceError, "DEVICE_UNAVAILABLE")
			}
			var children, profiles, requests int
			if err := s.pool.QueryRow(ctx, "SELECT (SELECT count(*) FROM camera.video_sources),(SELECT count(*) FROM camera.stream_profiles),(SELECT count(*) FROM camera.source_create_requests)").Scan(&children, &profiles, &requests); err != nil {
				t.Fatal(err)
			}
			if rollback {
				if children != 1 || profiles != 2 || requests != 1 {
					t.Fatal("source transaction incomplete")
				}
			} else if children != 0 || profiles != 0 || requests != 0 {
				t.Fatal("source survived deleted parent")
			}
		})
	}
}

func TestNativeSourceCreationWinsAgainstDeviceDeletion(t *testing.T) {
	if os.Getenv("CAMERA_TEST_ENGINE") == "pglite" {
		t.Skip("requires native PostgreSQL concurrent sessions")
	}
	for _, rollback := range []bool{false, true} {
		name := "commit"
		if rollback {
			name = "rollback"
		}
		t.Run(name, func(t *testing.T) {
			s, ctx := testStore(t)
			if _, err := s.Migrate(ctx); err != nil {
				t.Fatal(err)
			}
			createDeleteDevice(t, s, ctx, "parent")
			failureSQL := ""
			if rollback {
				failureSQL = "RAISE EXCEPTION 'injected source rollback';"
			}
			if _, err := s.pool.Exec(ctx, `CREATE FUNCTION camera.pause_source_creation() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM pg_advisory_xact_lock(1447908165,1); `+failureSQL+` RETURN NEW; END $$; CREATE TRIGGER pause_source_creation BEFORE INSERT ON camera.video_sources FOR EACH ROW EXECUTE FUNCTION camera.pause_source_creation()`); err != nil {
				t.Fatal(err)
			}
			gate, err := s.pool.Begin(ctx)
			if err != nil {
				t.Fatal(err)
			}
			defer gate.Rollback(context.Background())
			var gatePID int32
			if err = gate.QueryRow(ctx, "SELECT pg_backend_pid()").Scan(&gatePID); err != nil {
				t.Fatal(err)
			}
			if _, err = gate.Exec(ctx, "SELECT pg_advisory_xact_lock(1447908165,1)"); err != nil {
				t.Fatal(err)
			}
			created := make(chan error, 1)
			go func() { _, _, err := s.CreateSource(ctx, "p", "source", sourceInput("child", "ch1")); created <- err }()
			sourcePID := waitDeviceBlockedPID(t, s, ctx, gatePID)
			deleted := make(chan deviceDeleteOutcome, 1)
			go func() {
				value, replay, err := s.DeleteDevice(ctx, "p", "delete", "parent", deviceDeleteInput(1), unusedDeviceForTest)
				deleted <- deviceDeleteOutcome{value, replay, err}
			}()
			waitDeviceBlockedPID(t, s, ctx, sourcePID)
			if err = gate.Commit(ctx); err != nil {
				t.Fatal(err)
			}
			sourceError, deletion := <-created, <-deleted
			if rollback {
				requireDeleteError(t, sourceError, "DATABASE_UNAVAILABLE")
				if deletion.err != nil {
					t.Fatal("source rollback still blocked parent deletion", deletion.err)
				}
			} else {
				if sourceError != nil {
					t.Fatal(sourceError)
				}
				requireDeleteError(t, deletion.err, "DEVICE_HAS_ACTIVE_SOURCES")
				if _, _, err := s.DeleteSource(ctx, "p", "child-delete", "child", deleteInput(1), unusedSourceForTest); err != nil {
					t.Fatal(err)
				}
				if got, replay, err := s.DeleteDevice(ctx, "p", "delete", "parent", deviceDeleteInput(1), unusedDeviceForTest); err != nil || replay || got.Version != 2 {
					t.Fatal("child rejection could not retry", err)
				}
			}
		})
	}
}

func TestNativeDeviceDeleteAndRenameShareRowLock(t *testing.T) {
	if os.Getenv("CAMERA_TEST_ENGINE") == "pglite" {
		t.Skip("requires native PostgreSQL concurrent sessions")
	}
	for _, renameFirst := range []bool{false, true} {
		name := "delete_first"
		if renameFirst {
			name = "rename_first"
		}
		t.Run(name, func(t *testing.T) {
			s, ctx := testStore(t)
			if _, err := s.Migrate(ctx); err != nil {
				t.Fatal(err)
			}
			createDeleteDevice(t, s, ctx, "parent")
			gate, err := s.pool.Begin(ctx)
			if err != nil {
				t.Fatal(err)
			}
			defer gate.Rollback(context.Background())
			var pid int32
			if err = gate.QueryRow(ctx, "SELECT pg_backend_pid()").Scan(&pid); err != nil {
				t.Fatal(err)
			}
			if _, err = gate.Exec(ctx, "SELECT device_id FROM camera.devices WHERE device_id='parent' FOR UPDATE"); err != nil {
				t.Fatal(err)
			}
			deleted := make(chan deviceDeleteOutcome, 1)
			go func() {
				value, replay, err := s.DeleteDevice(ctx, "p", "delete", "parent", deviceDeleteInput(1), unusedDeviceForTest)
				deleted <- deviceDeleteOutcome{value, replay, err}
			}()
			waitDeviceBlockedPID(t, s, ctx, pid)
			if renameFirst {
				if _, err = gate.Exec(ctx, "UPDATE camera.devices SET display_name='renamed',version=version+1,updated_at=clock_timestamp() WHERE device_id='parent'"); err != nil {
					t.Fatal(err)
				}
			}
			if err = gate.Commit(ctx); err != nil {
				t.Fatal(err)
			}
			outcome := <-deleted
			if renameFirst {
				requireDeleteError(t, outcome.err, "DEVICE_VERSION_CONFLICT")
				if _, _, err = s.DeleteDevice(ctx, "p", "delete", "parent", deviceDeleteInput(2), unusedDeviceForTest); err != nil {
					t.Fatal(err)
				}
			} else if outcome.err != nil {
				t.Fatal(outcome.err)
			}
			_, _, err = s.UpdateDevice(ctx, "p", "new-rename", "parent", updateInput(2, "restore"))
			requireDeleteError(t, err, "DEVICE_NOT_FOUND")
		})
	}
}
