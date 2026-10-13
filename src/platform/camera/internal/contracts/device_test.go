package contracts

import (
	"encoding/json"
	"strings"
	"testing"
)

func TestDeviceJSONBoundary(t *testing.T) {
	for _, input := range []string{`null`, `[]`, `{"device_id":null}`, `{"device_id":123}`, `{"Device_id":"d1"}`, `{"device_id":"a","device_id":"b"}`, `{"device_id":"a","password":"secret"}`} {
		var d DeviceCreate
		if json.Unmarshal([]byte(input), &d) == nil {
			t.Fatalf("ambiguous JSON accepted: %s", input)
		}
	}
	var a, b DeviceCreate
	if json.Unmarshal([]byte(`{"schema_version":"v1","device_id":"d1","display_name":" 한글 ","device_kind":"CCTV"}`), &a) != nil || json.Unmarshal([]byte(`{"device_kind":"CCTV","display_name":" 한글 ","device_id":"d1","schema_version":"v1"}`), &b) != nil || a != b || a.DisplayName != " 한글 " || len(a.Validate()) != 0 {
		t.Fatal("canonical fields or whitespace lost")
	}
	for _, name := range []string{" ", "\u00a0", "\x00", strings.Repeat("가", 129)} {
		a.DisplayName = name
		if len(a.Validate()) == 0 {
			t.Fatal("invalid name accepted")
		}
	}
}
func TestDeviceCursorAndKey(t *testing.T) {
	c := EncodeDeviceCursor("Device-1")
	if after, e := DecodeDeviceCursor(c); e != nil || after != "Device-1" {
		t.Fatal("cursor round trip")
	}
	for _, c := range []string{"!", c + "=", strings.Repeat("A", 513)} {
		if _, e := DecodeDeviceCursor(c); e == nil {
			t.Fatal("invalid cursor accepted")
		}
	}
	for _, key := range []string{"", " ", "a\nb", "한글", strings.Repeat("a", 129)} {
		if ValidIdempotencyKey(key) {
			t.Fatal("invalid key accepted")
		}
	}
	if !ValidIdempotencyKey("key-01") {
		t.Fatal("valid key rejected")
	}
}
