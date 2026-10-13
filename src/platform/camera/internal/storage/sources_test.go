package storage

import (
	"os"
	"reflect"
	"sync"
	"testing"

	"vms.local/platform/camera/internal/contracts"
)

func sourceInput(id, channel string) contracts.SourceCreate {
	return contracts.SourceCreate{SchemaVersion: "v1", SourceID: id, DeviceID: "parent", ChannelKey: channel, DisplayName: "영상", Transport: "RTSP", InputMode: "PULL", MotionMode: "UNKNOWN", Profiles: []contracts.Profile{{ProfileID: "main", Codec: "H264", Width: 1920, Height: 1080, FPS: 29.97}, {ProfileID: "sub", Codec: "AUTO", Width: 640, Height: 360, FPS: 15}}}
}

func TestSourceUpgradeFromStep04AndAtomicity(t *testing.T) {
	s, ctx := testStore(t)
	m, _ := loadMigrations(migrationFiles)
	if _, err := s.migrate(ctx, m[:2]); err != nil {
		t.Fatal(err)
	}
	device := contracts.DeviceCreate{SchemaVersion: "v1", DeviceID: "parent", DisplayName: "기존 장치", DeviceKind: "CCTV"}
	original, _, err := s.CreateDevice(ctx, "principal", "same-key", device)
	if err != nil {
		t.Fatal(err)
	}
	if err = s.CheckReady(ctx); err == nil {
		t.Fatal("source API accepted version 2")
	}
	if result, e := s.Migrate(ctx); e != nil || result.Applied != 6 || result.Version != 8 {
		t.Fatal(result, e)
	}
	if replay, reused, e := s.CreateDevice(ctx, "principal", "same-key", device); e != nil || !reused || !reflect.DeepEqual(replay, original) {
		t.Fatal("existing device replay lost", e)
	}
	input := sourceInput("s1", "ch1")
	created, reused, err := s.CreateSource(ctx, "principal", "same-key", input)
	if err != nil || reused || created.Version != 1 || !reflect.DeepEqual(created.Profiles, input.Profiles) {
		t.Fatal(created, err)
	}
	got, err := s.GetSource(ctx, "s1")
	if err != nil || !reflect.DeepEqual(created, got) {
		t.Fatal("source roundtrip", err)
	}
	changed := input
	changed.Profiles = []contracts.Profile{input.Profiles[1], input.Profiles[0]}
	if _, _, e := s.CreateSource(ctx, "principal", "same-key", changed); e == nil || e.Error() != "IDEMPOTENCY_CONFLICT" {
		t.Fatal("array order ignored", e)
	}
	for _, c := range []struct {
		in   contracts.SourceCreate
		code string
	}{{sourceInput("s1", "other"), "SOURCE_EXISTS"}, {sourceInput("s2", "ch1"), "SOURCE_CHANNEL_EXISTS"}} {
		if _, _, e := s.CreateSource(ctx, "principal", "conflict-"+c.code, c.in); e == nil || e.Error() != c.code {
			t.Fatal(c.code, e)
		}
	}
	if _, _, e := s.CreateSource(ctx, "other-principal", "same-key", input); e == nil || e.Error() != "SOURCE_EXISTS" {
		t.Fatal("principal namespace", e)
	}
	xr := sourceInput("xr", "ch2")
	xr.Transport = "WEBRTC"
	xr.InputMode = "PUSH"
	if _, _, err = s.CreateSource(ctx, "principal", "xr", xr); err != nil {
		t.Fatal("multiple channels/XR", err)
	}
	missing := sourceInput("missing", "missing")
	missing.DeviceID = "absent"
	if _, _, e := s.CreateSource(ctx, "principal", "retry-parent", missing); e == nil || e.Error() != "DEVICE_UNAVAILABLE" {
		t.Fatal("missing parent", e)
	}
	if _, err = s.pool.Exec(ctx, `INSERT INTO camera.devices(device_id,display_name,device_kind) VALUES ('absent','new','TEST')`); err != nil {
		t.Fatal(err)
	}
	if _, _, err = s.CreateSource(ctx, "principal", "retry-parent", missing); err != nil {
		t.Fatal("failed request consumed key", err)
	}
	if _, err = s.pool.Exec(ctx, `UPDATE camera.devices SET deleted_at=CURRENT_TIMESTAMP WHERE device_id='absent'`); err != nil {
		t.Fatal(err)
	}
	missing.SourceID = "deleted-parent"
	missing.ChannelKey = "second"
	if _, _, e := s.CreateSource(ctx, "principal", "deleted-parent", missing); e == nil || e.Error() != "DEVICE_UNAVAILABLE" {
		t.Fatal("deleted parent", e)
	}
	// Fail after the first profile has been written: no partial source/profiles/key.
	if _, err = s.pool.Exec(ctx, `ALTER TABLE camera.stream_profiles ADD CONSTRAINT injected_profile_failure CHECK (profile_id <> 'block')`); err != nil {
		t.Fatal(err)
	}
	broken := sourceInput("rollback", "rollback")
	broken.Profiles[1].ProfileID = "block"
	if _, _, e := s.CreateSource(ctx, "principal", "rollback", broken); e == nil {
		t.Fatal("profile failure accepted")
	}
	var count int
	if e := s.pool.QueryRow(ctx, `SELECT (SELECT count(*) FROM camera.video_sources WHERE source_id='rollback')+(SELECT count(*) FROM camera.stream_profiles WHERE source_id='rollback')+(SELECT count(*) FROM camera.source_create_requests WHERE key_hash=$1)`, hashText([]byte("rollback"))).Scan(&count); e != nil || count != 0 {
		t.Fatal("partial profile transaction", e)
	}
	if _, err = s.pool.Exec(ctx, `ALTER TABLE camera.stream_profiles DROP CONSTRAINT injected_profile_failure; ALTER TABLE camera.source_create_requests ADD CONSTRAINT injected_response_failure CHECK(principal <> 'fail')`); err != nil {
		t.Fatal(err)
	}
	if _, _, e := s.CreateSource(ctx, "fail", "rollback", broken); e == nil {
		t.Fatal("response failure accepted")
	}
	if _, e := s.GetSource(ctx, "rollback"); e == nil {
		t.Fatal("source survived response failure")
	}
	if _, err = s.pool.Exec(ctx, `ALTER TABLE camera.source_create_requests DROP CONSTRAINT injected_response_failure`); err != nil {
		t.Fatal(err)
	}
	if _, _, err = s.CreateSource(ctx, "fail", "rollback", broken); err != nil {
		t.Fatal("same-key recovery failed", err)
	}
	if _, err = s.pool.Exec(ctx, `UPDATE camera.video_sources SET deleted_at=CURRENT_TIMESTAMP WHERE source_id='s1'`); err != nil {
		t.Fatal(err)
	}
	if _, e := s.GetSource(ctx, "s1"); e == nil || e.Error() != "SOURCE_NOT_FOUND" {
		t.Fatal("tombstone returned", e)
	}
	if _, _, e := s.CreateSource(ctx, "principal", "new-key", input); e == nil || e.Error() != "SOURCE_EXISTS" {
		t.Fatal("tombstone ID reused", e)
	}
	if replay, reused, e := s.CreateSource(ctx, "principal", "same-key", input); e != nil || !reused || !reflect.DeepEqual(replay, created) {
		t.Fatal("original response lost", e)
	}
}

func TestNativeConcurrentSourceCreate(t *testing.T) {
	if os.Getenv("CAMERA_TEST_ENGINE") == "pglite" {
		t.Skip("requires native PostgreSQL concurrent sessions")
	}
	s, ctx := testStore(t)
	if _, err := s.Migrate(ctx); err != nil {
		t.Fatal(err)
	}
	if _, err := s.pool.Exec(ctx, `INSERT INTO camera.devices(device_id,display_name,device_kind) VALUES ('parent','Parent','TEST')`); err != nil {
		t.Fatal(err)
	}
	var wg sync.WaitGroup
	results := make(chan bool, 8)
	errs := make(chan error, 8)
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			_, replay, err := s.CreateSource(ctx, "p", "key", sourceInput("race", "race"))
			results <- replay
			errs <- err
		}()
	}
	wg.Wait()
	close(results)
	close(errs)
	for err := range errs {
		if err != nil {
			t.Fatal(err)
		}
	}
	replays := 0
	for r := range results {
		if r {
			replays++
		}
	}
	if replays != 7 {
		t.Fatal("expected seven replays", replays)
	}
	var sources, profiles, requests int
	if err := s.pool.QueryRow(ctx, `SELECT (SELECT count(*) FROM camera.video_sources),(SELECT count(*) FROM camera.stream_profiles),(SELECT count(*) FROM camera.source_create_requests)`).Scan(&sources, &profiles, &requests); err != nil || sources != 1 || profiles != 2 || requests != 1 {
		t.Fatal(sources, profiles, requests, err)
	}
}
