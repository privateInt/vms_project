package storage

import (
	"context"
	"errors"
	"fmt"
	"math"
	"os"
	"reflect"
	"sync"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
	"vms.local/platform/camera/internal/contracts"
)

func deleteInput(version int64) contracts.SourceDelete {
	return contracts.SourceDelete{SchemaVersion: "v1", ExpectedVersion: version}
}

// Only a fixture: this does not observe real sessions or prove runtime safety.
func unusedSourceForTest(context.Context, pgx.Tx, string) (SourceUsage, error) {
	return SourceUsageUnused, nil
}

func requireDeleteError(t *testing.T, err error, code string) {
	t.Helper()
	if err == nil || err.Error() != code {
		t.Fatalf("expected %s, got %v", code, err)
	}
}

func TestSourceDeleteSchemaUpgradePreservationAndReplay(t *testing.T) {
	s, ctx := testStore(t)
	m, _ := loadMigrations(migrationFiles)
	if _, err := s.migrate(ctx, m[:5]); err != nil {
		t.Fatal(err)
	}
	original := seedUpdateSource(t, s, ctx, "source", "ch1")
	sibling := seedUpdateSource(t, s, ctx, "tail", "ch2")
	parent, _, err := s.UpdateDevice(ctx, "p", "create-source", "parent", updateInput(1, "renamed parent"))
	if err != nil {
		t.Fatal(err)
	}
	updated, _, err := s.UpdateSource(ctx, "p", "create-source", "source", sourceUpdateInput(1, "renamed"))
	if err != nil {
		t.Fatal(err)
	}
	profiles := sourceProfileState(t, s, ctx, "source")
	var history string
	if err := s.pool.QueryRow(ctx, `SELECT json_agg(row_to_json(m) ORDER BY version)::text FROM camera.schema_migrations m`).Scan(&history); err != nil {
		t.Fatal(err)
	}
	if s.CheckReady(ctx) == nil {
		t.Fatal("schema 5 accepted by schema 8 code")
	}
	for _, applied := range []int{3, 0} {
		if result, err := s.Migrate(ctx); err != nil || result.Version != 8 || result.Applied != applied {
			t.Fatal(result, err)
		}
	}
	if err := s.CheckReady(ctx); err != nil {
		t.Fatal(err)
	}
	var afterHistory string
	if err := s.pool.QueryRow(ctx, `SELECT json_agg(row_to_json(m) ORDER BY version)::text FROM camera.schema_migrations m WHERE version<=5`).Scan(&afterHistory); err != nil || afterHistory != history {
		t.Fatal("old migration history changed", err)
	}
	page, more, err := s.ListSources(ctx, "", "parent", 1)
	if err != nil || !more || len(page) != 1 || page[0].SourceID != "source" {
		t.Fatal("invalid initial page", err)
	}
	got, replay, err := s.DeleteSource(ctx, "p", "create-source", "source", deleteInput(2), unusedSourceForTest)
	if err != nil || replay || got.SourceID != "source" || got.SchemaVersion != "v1" || got.Version != 3 || got.DeletedAt.Before(updated.UpdatedAt) {
		t.Fatal("delete failed", got, err)
	}
	var at, deleted time.Time
	if err := s.pool.QueryRow(ctx, "SELECT updated_at,deleted_at FROM camera.video_sources WHERE source_id='source'").Scan(&at, &deleted); err != nil || !at.Equal(deleted) || !deleted.Equal(got.DeletedAt) {
		t.Fatal("deletion timestamps differ", err)
	}
	tombstone, err := scanSource(s.pool.QueryRow(ctx, sourceSelectBase+" WHERE s.source_id='source'"))
	if err != nil {
		t.Fatal(err)
	}
	tombstone.Version, tombstone.UpdatedAt = updated.Version, updated.UpdatedAt
	if !reflect.DeepEqual(tombstone, updated) || sourceProfileState(t, s, ctx, "source") != profiles {
		t.Fatal("source declaration or profiles changed")
	}
	if value, err := s.GetDevice(ctx, "parent"); err != nil || !reflect.DeepEqual(value, parent) {
		t.Fatal("parent changed", err)
	}
	if value, err := s.GetSource(ctx, "tail"); err != nil || !reflect.DeepEqual(value, sibling) {
		t.Fatal("sibling changed", err)
	}
	if _, err := s.GetSource(ctx, "source"); err == nil || err.Error() != "SOURCE_NOT_FOUND" {
		t.Fatal("deleted source visible", err)
	}
	for _, cursor := range []string{"", "source"} {
		page, more, err = s.ListSources(ctx, cursor, "parent", 1)
		if err != nil || more || len(page) != 1 || page[0].SourceID != "tail" {
			t.Fatal("deleted cursor/filter not preserved", err)
		}
	}
	if _, _, err := s.CreateSource(ctx, "p", "new-create", sourceInput("source", "new-channel")); err == nil || err.Error() != "SOURCE_EXISTS" {
		t.Fatal("deleted ID reused", err)
	}
	if _, _, err := s.CreateSource(ctx, "p", "new-channel", sourceInput("other", "ch1")); err == nil || err.Error() != "SOURCE_CHANNEL_EXISTS" {
		t.Fatal("deleted channel reused", err)
	}
	if _, _, err := s.UpdateSource(ctx, "p", "new-update", "source", sourceUpdateInput(3, "restore")); err == nil || err.Error() != "SOURCE_NOT_FOUND" {
		t.Fatal("new PATCH resurrected source", err)
	}
	s.Close()
	s, err = Open(ctx, os.Getenv("CAMERA_TEST_DATABASE_URL"))
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	// A durable success replays without invoking even a missing usage guard.
	if value, replay, err := s.DeleteSource(ctx, "p", "create-source", "source", deleteInput(2), nil); err != nil || !replay || !reflect.DeepEqual(value, got) {
		t.Fatal("durable deletion replay changed", err)
	}
	if value, replay, err := s.CreateSource(ctx, "p", "create-source", sourceInput("source", "ch1")); err != nil || !replay || !reflect.DeepEqual(value, original) {
		t.Fatal("POST snapshot changed", err)
	}
	if value, replay, err := s.UpdateSource(ctx, "p", "create-source", "source", sourceUpdateInput(1, "renamed")); err != nil || !replay || !reflect.DeepEqual(value, updated) {
		t.Fatal("PATCH snapshot changed", err)
	}
	if value, replay, err := s.UpdateDevice(ctx, "p", "create-source", "parent", updateInput(1, "renamed parent")); err != nil || !replay || !reflect.DeepEqual(value, parent) {
		t.Fatal("device PATCH history changed", err)
	}
	for _, c := range []struct {
		principal, key string
		version        int64
		code           string
	}{
		{"p", "create-source", 3, "IDEMPOTENCY_CONFLICT"},
		{"p", "another", 3, "SOURCE_NOT_FOUND"},
		{"other", "create-source", 2, "SOURCE_NOT_FOUND"},
	} {
		_, _, err := s.DeleteSource(ctx, c.principal, c.key, "source", deleteInput(c.version), nil)
		requireDeleteError(t, err, c.code)
	}
	if _, err := s.GetSource(ctx, "source"); err == nil {
		t.Fatal("historical replay resurrected source")
	}
	if value, replay, err := s.DeleteSource(ctx, "p", "create-source", "tail", deleteInput(1), unusedSourceForTest); err != nil || replay || value.SourceID != "tail" {
		t.Fatal("DELETE path scope leaked", err)
	}
	t.Log("schema 5->6/reapply, tombstone/profile preservation, cursor, POST/PATCH histories and reopen replay passed")
}

func TestSourceDeleteUsageErrorsAndRollback(t *testing.T) {
	s, ctx := testStore(t)
	if _, err := s.Migrate(ctx); err != nil {
		t.Fatal(err)
	}
	original := seedUpdateSource(t, s, ctx, "source", "ch1")
	for _, c := range []struct {
		name  string
		guard SourceDeleteGuard
		code  string
	}{
		{"missing", nil, "SOURCE_USAGE_UNAVAILABLE"},
		{"unknown", func(context.Context, pgx.Tx, string) (SourceUsage, error) { return SourceUsageUnknown, nil }, "SOURCE_USAGE_UNAVAILABLE"},
		{"invalid", func(context.Context, pgx.Tx, string) (SourceUsage, error) { return SourceUsage(99), nil }, "SOURCE_USAGE_UNAVAILABLE"},
		{"busy", func(context.Context, pgx.Tx, string) (SourceUsage, error) { return SourceUsageInUse, nil }, "SOURCE_IN_USE"},
		{"failed", func(context.Context, pgx.Tx, string) (SourceUsage, error) {
			return SourceUsageUnused, errors.New("private details")
		}, "SOURCE_USAGE_UNAVAILABLE"},
		{"transaction", func(ctx context.Context, tx pgx.Tx, id string) (SourceUsage, error) {
			_, err := tx.Exec(ctx, "UPDATE camera.video_sources SET display_name='guard change' WHERE source_id=$1", id)
			return SourceUsageUnknown, err
		}, "SOURCE_USAGE_UNAVAILABLE"},
	} {
		t.Run(c.name, func(t *testing.T) {
			_, _, err := s.DeleteSource(ctx, "p", "retry", "source", deleteInput(1), c.guard)
			requireDeleteError(t, err, c.code)
			if value, err := s.GetSource(ctx, "source"); err != nil || !reflect.DeepEqual(value, original) {
				t.Fatal("guard failure changed data", err)
			}
		})
	}
	for _, c := range []struct {
		id      string
		version int64
		code    string
	}{
		{"absent", 1, "SOURCE_NOT_FOUND"}, {"source", 2, "SOURCE_VERSION_CONFLICT"},
	} {
		_, _, err := s.DeleteSource(ctx, "p", "retry", c.id, deleteInput(c.version), nil)
		requireDeleteError(t, err, c.code)
	}
	if _, err := s.pool.Exec(ctx, `ALTER TABLE camera.source_delete_requests ADD CONSTRAINT injected_failure CHECK(principal <> 'p')`); err != nil {
		t.Fatal(err)
	}
	_, _, err := s.DeleteSource(ctx, "p", "retry", "source", deleteInput(1), unusedSourceForTest)
	requireDeleteError(t, err, "DATABASE_UNAVAILABLE")
	if value, err := s.GetSource(ctx, "source"); err != nil || !reflect.DeepEqual(value, original) {
		t.Fatal("journal failure left tombstone", err)
	}
	var count int
	if err := s.pool.QueryRow(ctx, "SELECT count(*) FROM camera.source_delete_requests").Scan(&count); err != nil || count != 0 {
		t.Fatal("failure persisted journal", err)
	}
	if _, err := s.pool.Exec(ctx, `ALTER TABLE camera.source_delete_requests DROP CONSTRAINT injected_failure`); err != nil {
		t.Fatal(err)
	}
	if value, replay, err := s.DeleteSource(ctx, "p", "retry", "source", deleteInput(1), unusedSourceForTest); err != nil || replay || value.Version != 2 {
		t.Fatal("same-key recovery failed", err)
	}
}

func TestSourceDeleteVersionAndClockBounds(t *testing.T) {
	s, ctx := testStore(t)
	if _, err := s.Migrate(ctx); err != nil {
		t.Fatal(err)
	}
	seedUpdateSource(t, s, ctx, "edge", "ch1")
	seedUpdateSource(t, s, ctx, "exhausted", "ch2")
	if _, err := s.pool.Exec(ctx, `UPDATE camera.video_sources SET version=$1,updated_at=clock_timestamp()+interval '1 day' WHERE source_id='edge'`, int64(math.MaxInt64-1)); err != nil {
		t.Fatal(err)
	}
	before, err := s.GetSource(ctx, "edge")
	if err != nil {
		t.Fatal(err)
	}
	got, _, err := s.DeleteSource(ctx, "p", "last", "edge", deleteInput(math.MaxInt64-1), unusedSourceForTest)
	if err != nil || got.Version != math.MaxInt64 || !got.DeletedAt.Equal(before.UpdatedAt) {
		t.Fatal("version/clock bounds", got, err)
	}
	if _, err := s.pool.Exec(ctx, `UPDATE camera.video_sources SET version=$1 WHERE source_id='exhausted'`, int64(math.MaxInt64)); err != nil {
		t.Fatal(err)
	}
	_, _, err = s.DeleteSource(ctx, "p", "overflow", "exhausted", deleteInput(math.MaxInt64), nil)
	requireDeleteError(t, err, "SOURCE_VERSION_EXHAUSTED")
	if _, err := s.GetSource(ctx, "exhausted"); err != nil {
		t.Fatal("overflow changed source", err)
	}
}

func TestSourceDeleteValidatesBeforeDatabaseAccess(t *testing.T) {
	s := &Store{}
	for _, c := range []struct {
		principal, key, id string
		input              contracts.SourceDelete
	}{
		{"", "k", "s", deleteInput(1)}, {"p", " ", "s", deleteInput(1)},
		{"p", "k", "../s", deleteInput(1)}, {"p", "k", "validate", deleteInput(1)},
		{"p", "k", "s", deleteInput(0)}, {"p", "k", "s", contracts.SourceDelete{SchemaVersion: "v2", ExpectedVersion: 1}},
	} {
		_, _, err := s.DeleteSource(context.Background(), c.principal, c.key, c.id, c.input, nil)
		requireDeleteError(t, err, "CONTRACT_INVALID")
	}
}

func TestNativeConcurrentSourceDelete(t *testing.T) {
	if os.Getenv("CAMERA_TEST_ENGINE") == "pglite" {
		t.Skip("requires native PostgreSQL concurrent sessions")
	}
	s, ctx := testStore(t)
	if _, err := s.Migrate(ctx); err != nil {
		t.Fatal(err)
	}
	type outcome struct {
		value  contracts.SourceDeletion
		replay bool
		err    error
	}
	for _, sameKey := range []bool{true, false} {
		id := fmt.Sprintf("race-%t", sameKey)
		seedUpdateSource(t, s, ctx, id, id)
		start := make(chan struct{})
		out := make(chan outcome, 8)
		var wg sync.WaitGroup
		for i := 0; i < 8; i++ {
			wg.Add(1)
			go func(i int) {
				defer wg.Done()
				key := fmt.Sprint(i)
				if sameKey {
					key = "shared"
				}
				<-start
				v, r, e := s.DeleteSource(ctx, "p", key, id, deleteInput(1), unusedSourceForTest)
				out <- outcome{v, r, e}
			}(i)
		}
		close(start)
		wg.Wait()
		close(out)
		first, replays, missing := 0, 0, 0
		var receipt *contracts.SourceDeletion
		for r := range out {
			if r.err != nil {
				requireDeleteError(t, r.err, "SOURCE_NOT_FOUND")
				missing++
				continue
			}
			if r.replay {
				replays++
			} else {
				first++
			}
			if r.value.Version != 2 || (receipt != nil && !reflect.DeepEqual(*receipt, r.value)) {
				t.Fatal("concurrent receipts differ")
			}
			v := r.value
			receipt = &v
		}
		if first != 1 || (sameKey && (replays != 7 || missing != 0)) || (!sameKey && (replays != 0 || missing != 7)) {
			t.Fatal("unexpected outcomes", first, replays, missing)
		}
	}
	// Exercise both real methods sharing the same row lock and version condition.
	for i := 0; i < 8; i++ {
		id := fmt.Sprintf("mixed-%d", i)
		seedUpdateSource(t, s, ctx, id, id)
		start := make(chan struct{})
		rename := make(chan error, 1)
		deletion := make(chan error, 1)
		go func() {
			<-start
			_, _, e := s.UpdateSource(ctx, "p", "mixed", id, sourceUpdateInput(1, "renamed"))
			rename <- e
		}()
		go func() {
			<-start
			_, _, e := s.DeleteSource(ctx, "p", "mixed", id, deleteInput(1), unusedSourceForTest)
			deletion <- e
		}()
		close(start)
		r, d := <-rename, <-deletion
		if r == nil {
			requireDeleteError(t, d, "SOURCE_VERSION_CONFLICT")
		} else {
			if d != nil {
				t.Fatal("both competing methods failed", r, d)
			}
			requireDeleteError(t, r, "SOURCE_NOT_FOUND")
		}
	}
}

func TestSourceDeleteJournalConstraints(t *testing.T) {
	s, ctx := testStore(t)
	if _, err := s.Migrate(ctx); err != nil {
		t.Fatal(err)
	}
	insert := `INSERT INTO camera.source_delete_requests(principal,method,path,key_hash,request_hash,response_body) VALUES ('p',$1,$2,$3,$4,$5::jsonb)`
	hash := hashText([]byte("key"))
	for _, c := range []struct{ method, path, keyHash, requestHash, body string }{
		{"PATCH", "/api/v1/sources/s1", hash, hash, "{}"}, {"DELETE", "/api/v1/devices/s1", hash, hash, "{}"},
		{"DELETE", "/api/v1/sources/validate", hash, hash, "{}"}, {"DELETE", "/api/v1/sources/s1", "raw", hash, "{}"},
		{"DELETE", "/api/v1/sources/s1", hash, "invalid", "{}"}, {"DELETE", "/api/v1/sources/s1", hash, hash, "[]"},
	} {
		if _, err := s.pool.Exec(ctx, insert, c.method, c.path, c.keyHash, c.requestHash, c.body); state(err) != "23514" {
			t.Fatal("journal constraint missing", state(err))
		}
	}
	if _, err := s.pool.Exec(ctx, insert, "DELETE", "/api/v1/sources/s1", hash, hash, "{}"); err != nil {
		t.Fatal(err)
	}
	if _, err := s.pool.Exec(ctx, insert, "DELETE", "/api/v1/sources/s1", hash, hash, "{}"); state(err) != "23505" {
		t.Fatal("duplicate journal allowed", err)
	}
}
