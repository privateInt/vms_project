package contracts

import (
	"encoding/json"
	"fmt"
	"math"
	"strings"
	"testing"
)

func TestSourceUpdateStorageInput(t *testing.T) {
	for _, name := range []string{"입구", "  출입구  ", strings.Repeat("📷", 128)} {
		for _, version := range []int64{1, math.MaxInt64} {
			input := SourceUpdate{SchemaVersion: "v1", ExpectedVersion: version, DisplayName: name}
			if len(input.Validate()) != 0 {
				t.Fatal("valid storage input rejected")
			}
		}
	}
	for _, input := range []SourceUpdate{
		{}, {SchemaVersion: "v2", ExpectedVersion: 1, DisplayName: "valid"},
		{SchemaVersion: "v1", ExpectedVersion: 0, DisplayName: "valid"},
		{SchemaVersion: "v1", ExpectedVersion: -1, DisplayName: "valid"},
	} {
		if len(input.Validate()) == 0 {
			t.Fatal("invalid storage input accepted")
		}
	}
	for _, name := range []string{"", " \t\n", "\u3000\u00a0", "bad\x00", "bad\xff", strings.Repeat("가", 129)} {
		if len((SourceUpdate{SchemaVersion: "v1", ExpectedVersion: 1, DisplayName: name}).Validate()) == 0 {
			t.Fatal("invalid name accepted")
		}
	}
}

func TestSourceUpdateStrictJSON(t *testing.T) {
	for _, version := range []int64{1, 9007199254740993, math.MaxInt64} {
		body := fmt.Sprintf(`{"display_name":"  \uC785\uAD6C 📷  ","expected_version":%d,"schema_version":"v1"}`, version)
		var input SourceUpdate
		if err := json.Unmarshal([]byte(body), &input); err != nil || input.ExpectedVersion != version || input.DisplayName != "  입구 📷  " || len(input.Validate()) != 0 {
			t.Fatal("valid exact input rejected or changed", input, err)
		}
	}
	for _, body := range []string{
		`null`, `[]`, `1`, `"text"`, `true`,
		`{"expected_version":null}`, `{"expected_version":"1"}`, `{"expected_version":1.0}`, `{"expected_version":1e0}`,
		`{"expected_version":9223372036854775808}`, `{"expected_version":-9223372036854775809}`,
		`{"expected_version":true}`, `{"expected_version":{}}`, `{"expected_version":[]}`,
		`{"expected_version":1,"expected_version":1}`, `{"expected_version":1,"\u0065xpected_version":1}`,
		`{"display_name":"a","display_name":"a"}`, `{"schema_version":"v1","schema_version":"v1"}`,
		`{"Display_Name":"a"}`, `{"source_id":"d1"}`, `{"transport":"RTSP"}`, `{"device_id":"d1"}`, `{"channel_key":"ch1"}`, `{"profiles":[]}`, `{"input_mode":"PULL"}`, `{"motion_mode":"FIXED"}`, `{"primary_profile_id":"main"}`, `{"version":1}`,
		`{"schema_version":null}`, `{"display_name":null}`, `{"display_name":1}`, `{"schema_version":false}`,
		`{"display_name":"bad` + string([]byte{0xff}) + `"}`, `{"display_name":`, `{} {}`,
	} {
		var input SourceUpdate
		if json.Unmarshal([]byte(body), &input) == nil {
			t.Fatalf("ambiguous JSON accepted: %q", body)
		}
	}
	// Missing fields and in-range nonpositive integers are semantic errors.
	for _, body := range []string{`{}`, `{"schema_version":"v1","display_name":"a"}`, `{"schema_version":"v1","expected_version":1}`, `{"expected_version":1,"display_name":"a"}`, `{"schema_version":"v1","expected_version":0,"display_name":"a"}`, `{"schema_version":"v1","expected_version":-9223372036854775808,"display_name":"a"}`} {
		var input SourceUpdate
		if json.Unmarshal([]byte(body), &input) != nil || len(input.Validate()) == 0 {
			t.Fatal("missing/value validation must be semantic", body)
		}
	}
}
