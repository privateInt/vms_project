package storage

import (
	"reflect"
	"testing"

	"vms.local/platform/camera/internal/contracts"
)

func TestSourceListPaginationProfilesAndTombstones(t *testing.T) {
	s, ctx := testStore(t)
	if _, err := s.Migrate(ctx); err != nil {
		t.Fatal(err)
	}
	items, more, err := s.ListSources(ctx, "", "", 50)
	if err != nil || items == nil || len(items) != 0 || more {
		t.Fatal("empty page", items, more, err)
	}
	for _, device := range []string{"parent", "other"} {
		if _, _, err = s.CreateDevice(ctx, "p", device, contracts.DeviceCreate{SchemaVersion: "v1", DeviceID: device, DisplayName: device, DeviceKind: "TEST"}); err != nil {
			t.Fatal(err)
		}
	}
	originals := map[string]contracts.VideoSource{}
	for i, id := range []string{"z", "a", "A", "a-1", "B"} {
		input := sourceInput(id, id)
		if i == 0 {
			input.DeviceID = "other"
		}
		originals[id], _, err = s.CreateSource(ctx, "p", id, input)
		if err != nil {
			t.Fatal(err)
		}
	}
	check := func(after, device string, limit int, want []string, wantMore bool) {
		t.Helper()
		items, more, err := s.ListSources(ctx, after, device, limit)
		if err != nil || more != wantMore || len(items) != len(want) {
			t.Fatalf("%s/%s: %v more=%v err=%v", after, device, items, more, err)
		}
		for i, id := range want {
			if !reflect.DeepEqual(items[i], originals[id]) {
				t.Fatal("order/full source/profiles mismatch", id, items[i])
			}
		}
	}
	check("", "", 2, []string{"A", "B"}, true)
	check("B", "", 2, []string{"a", "a-1"}, true)
	check("a-1", "", 2, []string{"z"}, false)
	check("z", "", 200, []string{}, false)
	check("", "other", 1, []string{"z"}, false)
	check("", "missing", 50, []string{}, false)
	check("", "parent", 200, []string{"A", "B", "a", "a-1"}, false)
	check("A", "parent", 1, []string{"B"}, true)
	// The cursor row may disappear between pages; seek must still work.
	if _, err = s.pool.Exec(ctx, `UPDATE camera.video_sources SET deleted_at=CURRENT_TIMESTAMP WHERE source_id IN ('A','B')`); err != nil {
		t.Fatal(err)
	}
	check("", "parent", 2, []string{"a", "a-1"}, false)
	check("B", "", 2, []string{"a", "a-1"}, true)
	// Concurrent page changes are deliberately not a fixed snapshot. New IDs
	// after the boundary appear on later requests; IDs before it do not repeat.
	for _, id := range []string{"0-new", "c-new"} {
		originals[id], _, err = s.CreateSource(ctx, "p", id, sourceInput(id, id))
		if err != nil {
			t.Fatal(err)
		}
	}
	check("a-1", "", 2, []string{"c-new", "z"}, false)
	for _, c := range []struct {
		after, device string
		limit         int
	}{{"", "", 0}, {"", "", 201}, {"bad!", "", 1}, {"", "bad!", 1}} {
		if _, _, err = s.ListSources(ctx, c.after, c.device, c.limit); err == nil || err.Error() != "CONTRACT_INVALID" {
			t.Fatal("invalid list input", c, err)
		}
	}
}
