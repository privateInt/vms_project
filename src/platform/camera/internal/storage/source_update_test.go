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

func sourceUpdateInput(version int64, name string) contracts.SourceUpdate {
	return contracts.SourceUpdate{SchemaVersion: "v1", ExpectedVersion: version, DisplayName: name}
}

func seedUpdateSource(t *testing.T, s *Store, ctx context.Context, id, channel string) contracts.VideoSource {
	t.Helper()
	if _, _, err := s.CreateDevice(ctx, "p", "create-parent", contracts.DeviceCreate{SchemaVersion: "v1", DeviceID: "parent", DisplayName: "parent", DeviceKind: "TEST"}); err != nil {
		t.Fatal(err)
	}
	value, _, err := s.CreateSource(ctx, "p", "create-"+id, sourceInput(id, channel))
	if err != nil {
		t.Fatal(err)
	}
	return value
}

func sourceProfileState(t *testing.T, s *Store, ctx context.Context, id string) string {
	t.Helper()
	var value string
	err := s.pool.QueryRow(ctx, `SELECT json_build_object('primary',s.primary_profile_id,'profiles',
 (SELECT json_agg(row_to_json(p) ORDER BY position) FROM camera.stream_profiles p WHERE p.source_id=s.source_id))::text
 FROM camera.video_sources s WHERE source_id=$1`, id).Scan(&value)
	if err != nil {
		t.Fatal(err)
	}
	return value
}

func TestSourceUpdateSchemaUpgradeAndReplay(t *testing.T) {
	s, ctx := testStore(t)
	m, _ := loadMigrations(migrationFiles)
	if _, err := s.migrate(ctx, m[:4]); err != nil {
		t.Fatal(err)
	}
	seedUpdateSource(t, s, ctx, "sibling", "ch0")
	inputCreate := sourceInput("source", "ch1")
	original, _, err := s.CreateSource(ctx, "p", "same-key", inputCreate)
	if err != nil {
		t.Fatal(err)
	}
	sibling, err := s.GetSource(ctx, "sibling")
	if err != nil {
		t.Fatal(err)
	}
	parent, _, err := s.UpdateDevice(ctx, "p", "same-key", "parent", updateInput(1, "parent renamed"))
	if err != nil {
		t.Fatal(err)
	}
	profiles := sourceProfileState(t, s, ctx, "source")
	var history string
	if err = s.pool.QueryRow(ctx, `SELECT json_agg(row_to_json(m) ORDER BY version)::text FROM camera.schema_migrations m`).Scan(&history); err != nil {
		t.Fatal(err)
	}
	if s.CheckReady(ctx) == nil {
		t.Fatal("schema 4 accepted by schema 6 code")
	}
	if result, err := s.Migrate(ctx); err != nil || result.Version != 8 || result.Applied != 4 {
		t.Fatal(result, err)
	}
	if result, err := s.Migrate(ctx); err != nil || result.Version != 8 || result.Applied != 0 {
		t.Fatal(result, err)
	}
	if err = s.CheckReady(ctx); err != nil {
		t.Fatal(err)
	}
	var afterHistory string
	if err = s.pool.QueryRow(ctx, `SELECT json_agg(row_to_json(m) ORDER BY version)::text FROM camera.schema_migrations m WHERE version<=4`).Scan(&afterHistory); err != nil || afterHistory != history {
		t.Fatal("existing migration history changed", err)
	}
	input := sourceUpdateInput(1, "  출입구 영상  ")
	updated, replay, err := s.UpdateSource(ctx, "p", "same-key", "source", input)
	if err != nil || replay || updated.Version != 2 || updated.DisplayName != input.DisplayName || updated.UpdatedAt.Before(original.UpdatedAt) {
		t.Fatal("rename failed", err)
	}
	immutable := updated
	immutable.DisplayName = original.DisplayName
	immutable.Version = original.Version
	immutable.UpdatedAt = original.UpdatedAt
	if !reflect.DeepEqual(immutable, original) || sourceProfileState(t, s, ctx, "source") != profiles {
		t.Fatal("source declarations or profiles changed")
	}
	if got, err := s.GetSource(ctx, "source"); err != nil || !reflect.DeepEqual(got, updated) {
		t.Fatal("GET differs", err)
	}
	if items, more, err := s.ListSources(ctx, "sibling", "parent", 1); err != nil || more || len(items) != 1 || !reflect.DeepEqual(items[0], updated) {
		t.Fatal("list cursor/filter changed", err)
	}
	if got, err := s.GetSource(ctx, "sibling"); err != nil || !reflect.DeepEqual(got, sibling) {
		t.Fatal("sibling changed", err)
	}
	if got, err := s.GetDevice(ctx, "parent"); err != nil || !reflect.DeepEqual(got, parent) {
		t.Fatal("parent changed", err)
	}
	if got, replay, err := s.CreateSource(ctx, "p", "same-key", inputCreate); err != nil || !replay || !reflect.DeepEqual(got, original) {
		t.Fatal("POST replay changed", err)
	}
	if got, replay, err := s.UpdateDevice(ctx, "p", "same-key", "parent", updateInput(1, "parent renamed")); err != nil || !replay || !reflect.DeepEqual(got, parent) {
		t.Fatal("device PATCH replay changed", err)
	}
	second, replay, err := s.UpdateSource(ctx, "p", "second", "source", sourceUpdateInput(2, "latest"))
	if err != nil || replay || second.Version != 3 {
		t.Fatal(second, err)
	}
	s.Close()
	s, err = Open(ctx, os.Getenv("CAMERA_TEST_DATABASE_URL"))
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	if got, replay, err := s.UpdateSource(ctx, "p", "same-key", "source", input); err != nil || !replay || !reflect.DeepEqual(got, updated) {
		t.Fatal("durable historical snapshot lost", err)
	}
	if got, err := s.GetSource(ctx, "source"); err != nil || !reflect.DeepEqual(got, second) {
		t.Fatal("historical replay changed current source", err)
	}
	for _, changed := range []contracts.SourceUpdate{sourceUpdateInput(2, input.DisplayName), sourceUpdateInput(1, "changed")} {
		if _, _, err := s.UpdateSource(ctx, "p", "same-key", "source", changed); err == nil || err.Error() != "IDEMPOTENCY_CONFLICT" {
			t.Fatal("key conflict not detected", err)
		}
	}
	if _, _, err := s.UpdateSource(ctx, "other-principal", "same-key", "source", input); err == nil || err.Error() != "SOURCE_VERSION_CONFLICT" {
		t.Fatal("principal scope leaked", err)
	}
	if got, replay, err := s.UpdateSource(ctx, "p", "same-key", "sibling", input); err != nil || replay || got.SourceID != "sibling" {
		t.Fatal("source path scope leaked", err)
	}
	t.Log("schema 4->6, full-source/profile preservation, parent/sibling, POST/device PATCH, cursor and durable source PATCH replay passed")
}

func TestSourceUpdateErrorsAndAtomicity(t *testing.T) {
	s, ctx := testStore(t)
	if _, err := s.Migrate(ctx); err != nil {
		t.Fatal(err)
	}
	original := seedUpdateSource(t, s, ctx, "source", "ch1")
	profiles := sourceProfileState(t, s, ctx, "source")
	for _, c := range []struct {
		id      string
		version int64
		code    string
	}{{"absent", 1, "SOURCE_NOT_FOUND"}, {"source", 2, "SOURCE_VERSION_CONFLICT"}} {
		if _, _, err := s.UpdateSource(ctx, "p", "attempt", c.id, sourceUpdateInput(c.version, "new")); err == nil || err.Error() != c.code {
			t.Fatal("wrong error", err)
		}
	}
	if _, err := s.pool.Exec(ctx, `ALTER TABLE camera.source_update_requests ADD CONSTRAINT injected_failure CHECK(principal <> 'fail')`); err != nil {
		t.Fatal(err)
	}
	input := sourceUpdateInput(1, "new")
	if _, _, err := s.UpdateSource(ctx, "fail", "attempt", "source", input); err == nil {
		t.Fatal("journal failure ignored")
	}
	if got, err := s.GetSource(ctx, "source"); err != nil || !reflect.DeepEqual(got, original) || sourceProfileState(t, s, ctx, "source") != profiles {
		t.Fatal("partial update survived rollback", err)
	}
	var count int
	if err := s.pool.QueryRow(ctx, "SELECT count(*) FROM camera.source_update_requests").Scan(&count); err != nil || count != 0 {
		t.Fatal("failed success journal persisted", err)
	}
	if _, err := s.pool.Exec(ctx, `ALTER TABLE camera.source_update_requests DROP CONSTRAINT injected_failure`); err != nil {
		t.Fatal(err)
	}
	updated, replay, err := s.UpdateSource(ctx, "fail", "attempt", "source", input)
	if err != nil || replay || updated.Version != 2 {
		t.Fatal("same-key retry failed", err)
	}
	if got, replay, err := s.UpdateSource(ctx, "p", "same-name", "source", sourceUpdateInput(2, "new")); err != nil || replay || got.Version != 3 {
		t.Fatal("same-name new command failed", err)
	}
	if _, err := s.pool.Exec(ctx, `UPDATE camera.video_sources SET deleted_at=clock_timestamp() WHERE source_id='source'`); err != nil {
		t.Fatal(err)
	}
	if _, _, err := s.UpdateSource(ctx, "p", "new-key", "source", sourceUpdateInput(1, "rename")); err == nil || err.Error() != "SOURCE_NOT_FOUND" {
		t.Fatal("tombstone not checked before version", err)
	}
	if got, replay, err := s.UpdateSource(ctx, "fail", "attempt", "source", input); err != nil || !replay || !reflect.DeepEqual(got, updated) {
		t.Fatal("tombstone lost historic replay", err)
	}
	if _, err := s.GetSource(ctx, "source"); err == nil || err.Error() != "SOURCE_NOT_FOUND" {
		t.Fatal("replay resurrected source", err)
	}
	t.Log("version/tombstone errors, journal failure rollback, same-key retry and same-name increment passed")
}

func TestSourceUpdateVersionAndClockBounds(t *testing.T) {
	s, ctx := testStore(t)
	if _, err := s.Migrate(ctx); err != nil {
		t.Fatal(err)
	}
	seedUpdateSource(t, s, ctx, "edge", "ch1")
	if _, err := s.pool.Exec(ctx, `UPDATE camera.video_sources SET version=$1,updated_at=clock_timestamp()+interval '1 day' WHERE source_id='edge'`, int64(math.MaxInt64-1)); err != nil {
		t.Fatal(err)
	}
	before, err := s.GetSource(ctx, "edge")
	if err != nil {
		t.Fatal(err)
	}
	got, _, err := s.UpdateSource(ctx, "p", "last", "edge", sourceUpdateInput(math.MaxInt64-1, "last"))
	if err != nil || got.Version != math.MaxInt64 || got.UpdatedAt.Before(before.UpdatedAt) {
		t.Fatal("version/clock boundary", err)
	}
	if _, _, err := s.UpdateSource(ctx, "p", "overflow", "edge", sourceUpdateInput(math.MaxInt64, "overflow")); err == nil || err.Error() != "SOURCE_VERSION_EXHAUSTED" {
		t.Fatal("overflow allowed", err)
	}
	if after, err := s.GetSource(ctx, "edge"); err != nil || !reflect.DeepEqual(after, got) {
		t.Fatal("overflow modified source", err)
	}
}

func TestSourceUpdateValidatesBeforeDatabaseAccess(t *testing.T) {
	s := &Store{}
	for _, c := range []struct {
		principal, key, id string
		input              contracts.SourceUpdate
	}{
		{"", "key", "source", sourceUpdateInput(1, "name")}, {"p", " ", "source", sourceUpdateInput(1, "name")},
		{"p", "key", "../source", sourceUpdateInput(1, "name")}, {"p", "key", "validate", sourceUpdateInput(1, "name")},
		{"p", "key", "source", sourceUpdateInput(0, "name")}, {"p", "key", "source", sourceUpdateInput(1, "\x00")},
	} {
		if _, _, err := s.UpdateSource(context.Background(), c.principal, c.key, c.id, c.input); err == nil || err.Error() != "CONTRACT_INVALID" {
			t.Fatal("invalid input accepted", err)
		}
	}
}

func TestNativeConcurrentSourceUpdate(t *testing.T) {
	if os.Getenv("CAMERA_TEST_ENGINE") == "pglite" {
		t.Skip("requires native PostgreSQL concurrent sessions")
	}
	s, ctx := testStore(t)
	if _, err := s.Migrate(ctx); err != nil {
		t.Fatal(err)
	}
	seedUpdateSource(t, s, ctx, "race", "ch1")

	type outcome struct {
		source contracts.VideoSource
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
				d, replay, err := s.UpdateSource(ctx, "p", key, "race", sourceUpdateInput(version, name))
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
		{1, true, false, 0, ""}, {2, false, true, 7, "SOURCE_VERSION_CONFLICT"}, {3, true, true, 7, "IDEMPOTENCY_CONFLICT"},
	} {
		first, replayed, conflicts := 0, 0, 0
		var snapshot *contracts.VideoSource
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
				if out.source.Version != scenario.version+1 {
					t.Fatal("wrong version")
				}
				if snapshot != nil && !reflect.DeepEqual(*snapshot, out.source) {
					t.Fatal("same-key snapshots differ")
				}
				value := out.source
				snapshot = &value
			}
		}
		if first != 1 || conflicts != scenario.conflicts || replayed != 7-scenario.conflicts {
			t.Fatal("unexpected concurrent outcomes", first, replayed, conflicts)
		}
	}
	var count int
	if err := s.pool.QueryRow(ctx, "SELECT count(*) FROM camera.source_update_requests").Scan(&count); err != nil || count != 3 {
		t.Fatal("unexpected successful request count", err)
	}
	t.Log("same-key parallel replay, competing versions and parallel conflicting key bodies passed")
}

func TestSourceUpdateJournalConstraints(t *testing.T) {
	s, ctx := testStore(t)
	if _, err := s.Migrate(ctx); err != nil {
		t.Fatal(err)
	}
	insert := `INSERT INTO camera.source_update_requests(principal,method,path,key_hash,request_hash,response_body) VALUES ('p',$1,$2,$3,$4,$5::jsonb)`
	hash := hashText([]byte("key"))
	for _, c := range []struct{ method, path, keyHash, requestHash, body string }{
		{"POST", "/api/v1/sources/s1", hash, hash, "{}"},
		{"PATCH", "/api/v1/devices/s1", hash, hash, "{}"},
		{"PATCH", "/api/v1/sources/validate", hash, hash, "{}"},
		{"PATCH", "/api/v1/sources/s1", "raw-key", hash, "{}"},
		{"PATCH", "/api/v1/sources/s1", hash, "invalid", "{}"},
		{"PATCH", "/api/v1/sources/s1", hash, hash, "[]"},
	} {
		if _, err := s.pool.Exec(ctx, insert, c.method, c.path, c.keyHash, c.requestHash, c.body); state(err) != "23514" {
			t.Fatal("journal constraint not enforced", state(err))
		}
	}
	if _, err := s.pool.Exec(ctx, insert, "PATCH", "/api/v1/sources/s1", hash, hash, "{}"); err != nil {
		t.Fatal(err)
	}
	if _, err := s.pool.Exec(ctx, insert, "PATCH", "/api/v1/sources/s1", hash, hash, "{}"); state(err) != "23505" {
		t.Fatal("duplicate request accepted", err)
	}
	if _, err := s.pool.Exec(ctx, insert, "PATCH", "/api/v1/sources/s2", hash, hash, "{}"); err != nil {
		t.Fatal("different source path rejected", err)
	}
}
