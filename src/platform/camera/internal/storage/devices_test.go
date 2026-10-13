package storage

import (
	"os"
	"sync"
	"testing"

	"vms.local/platform/camera/internal/contracts"
)

func TestDeviceUpgradeFromStep02AndAtomicity(t *testing.T) {
	s, ctx := testStore(t)
	m, _ := loadMigrations(migrationFiles)
	if _, err := s.migrate(ctx, m[:1]); err != nil {
		t.Fatal(err)
	}
	if _, err := s.pool.Exec(ctx, `INSERT INTO camera.devices(device_id,display_name,device_kind) VALUES ('existing','기존 장치','CCTV')`); err != nil {
		t.Fatal(err)
	}
	if err := s.CheckReady(ctx); err == nil {
		t.Fatal("old schema accepted")
	}
	if result, err := s.Migrate(ctx); err != nil || result.Applied != 7 || result.Version != 8 {
		t.Fatal(result, err)
	}
	if d, err := s.GetDevice(ctx, "existing"); err != nil || d.DisplayName != "기존 장치" {
		t.Fatal("upgrade lost existing device", err)
	}
	input := contracts.DeviceCreate{SchemaVersion: "v1", DeviceID: "rollback", DisplayName: "롤백", DeviceKind: "TEST"}
	if _, err := s.pool.Exec(ctx, `ALTER TABLE camera.device_create_requests ADD CONSTRAINT injected_failure CHECK (principal <> 'fail')`); err != nil {
		t.Fatal(err)
	}
	if _, _, err := s.CreateDevice(ctx, "fail", "key", input); err == nil {
		t.Fatal("injected response save failure accepted")
	}
	if _, err := s.GetDevice(ctx, "rollback"); err == nil {
		t.Fatal("device left without idempotency response")
	}
	if _, _, err := s.CreateDevice(ctx, "ok", "key", input); err != nil {
		t.Fatal("retry failed", err)
	}
	if _, _, err := s.CreateDevice(ctx, "other-principal", "key", input); err == nil || err.Error() != "DEVICE_EXISTS" {
		t.Fatal("principal scope not independent", err)
	}
	if _, err := s.pool.Exec(ctx, `UPDATE camera.devices SET deleted_at=CURRENT_TIMESTAMP WHERE device_id='rollback'`); err != nil {
		t.Fatal(err)
	}
	if _, err := s.GetDevice(ctx, "rollback"); err == nil {
		t.Fatal("tombstone returned")
	}
	if _, _, err := s.CreateDevice(ctx, "ok", "other-key", input); err == nil || err.Error() != "DEVICE_EXISTS" {
		t.Fatal("tombstone id reused", err)
	}
	if _, replay, err := s.CreateDevice(ctx, "ok", "key", input); err != nil || !replay {
		t.Fatal("original response not retained", err)
	}
}

func TestNativeConcurrentDeviceCreate(t *testing.T) {
	if os.Getenv("CAMERA_TEST_ENGINE") == "pglite" {
		t.Skip("requires native PostgreSQL concurrent sessions")
	}
	s, ctx := testStore(t)
	if _, err := s.Migrate(ctx); err != nil {
		t.Fatal(err)
	}
	input := contracts.DeviceCreate{SchemaVersion: "v1", DeviceID: "race", DisplayName: "동시 생성", DeviceKind: "TEST"}
	var wg sync.WaitGroup
	replays := make(chan bool, 8)
	errs := make(chan error, 8)
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			_, replay, err := s.CreateDevice(ctx, "principal", "same", input)
			replays <- replay
			errs <- err
		}()
	}
	wg.Wait()
	close(replays)
	close(errs)
	for err := range errs {
		if err != nil {
			t.Fatal(err)
		}
	}
	count := 0
	for replay := range replays {
		if replay {
			count++
		}
	}
	if count != 7 {
		t.Fatalf("want 7 replays, got %d", count)
	}
	var rows int
	if err := s.pool.QueryRow(ctx, "SELECT count(*) FROM camera.devices").Scan(&rows); err != nil || rows != 1 {
		t.Fatal("duplicate device", err)
	}
}
