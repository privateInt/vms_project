package contracts

import (
	"encoding/base64"
	"strings"
	"testing"
)

func TestSourceCursorBindsScopeAndDeviceFilter(t *testing.T) {
	for _, device := range []string{"", "d1", strings.Repeat("d", 64)} {
		id := strings.Repeat("s", 64)
		cursor := EncodeSourceCursor(id, device)
		if got, err := DecodeSourceCursor(cursor, device); err != nil || got != id || len(cursor) > 512 {
			t.Fatal("cursor roundtrip", got, err)
		}
		if _, err := DecodeSourceCursor(cursor, "different"); err == nil {
			t.Fatal("filter change accepted")
		}
	}
	if got, err := DecodeSourceCursor("", "d1"); err != nil || got != "" {
		t.Fatal(got, err)
	}
	encode := func(value string) string { return base64.RawURLEncoding.EncodeToString([]byte(value)) }
	for _, cursor := range []string{
		EncodeDeviceCursor("s1"), EncodeSourceCursor("bad!", "d1"), "!", strings.Repeat("a", 513),
		EncodeSourceCursor("s1", "d1") + "=", EncodeSourceCursor("s1", "d1") + "\n",
		encode(`{"scope":"camera.sources:v2","after":"s1","device_id":"d1"}`),
		encode(`{"scope":"camera.sources:v1","after":"s1","device_id":"d1","extra":true}`),
		encode(`{"scope":"camera.sources:v1","after":"s0","after":"s1","device_id":"d1"}`),
		encode(`{"scope":"camera.sources:v1","after":"s1","Device_ID":"d1"}`),
		encode(`{"scope":"camera.sources:v1","after":"s1","device_id":"d1"} {}`),
	} {
		if _, err := DecodeSourceCursor(cursor, "d1"); err == nil {
			t.Fatal("invalid cursor accepted", cursor)
		}
	}
	if _, err := DecodeSourceCursor("", "bad!"); err == nil {
		t.Fatal("invalid filter")
	}
	if _, err := DecodeSourceCursor(EncodeSourceCursor("s1", "d1"), ""); err == nil {
		t.Fatal("filter removed")
	}
	if _, err := DecodeSourceCursor(EncodeSourceCursor("s1", ""), "d1"); err == nil {
		t.Fatal("filter added")
	}
}
