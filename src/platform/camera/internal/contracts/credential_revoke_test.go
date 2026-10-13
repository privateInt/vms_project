package contracts

import (
	"encoding/json"
	"strings"
	"testing"
)

func TestCredentialVersionPathTokens(t *testing.T) {
	for _, value := range []string{"1", "42", "9007199254740993", "9223372036854775807"} {
		n, ok := ParseCredentialVersion(value)
		if !ok || n < 1 {
			t.Fatalf("valid exact version rejected: %s", value)
		}
		if value == "9007199254740993" && n != 9007199254740993 {
			t.Fatal("version lost precision")
		}
	}
	for _, value := range []string{"", "0", "01", "+1", "-1", "1.0", "1e0", " 1", "1 ", "latest", "１", "9223372036854775808", strings.Repeat("9", 20)} {
		t.Run(value, func(t *testing.T) {
			if _, ok := ParseCredentialVersion(value); ok {
				t.Fatal("noncanonical version accepted")
			}
		})
	}
}

func TestCredentialRevokeStrictJSON(t *testing.T) {
	const valid = `{"schema_version":"v1","device_id":"camera-1"}`
	var input CredentialRevoke
	if json.Unmarshal([]byte(valid), &input) != nil || len(input.Validate()) != 0 {
		t.Fatal("valid input")
	}
	for name, body := range map[string]string{
		"null": "null", "array": "[]", "trailing": valid + " {}", "case": `{"Schema_Version":"v1","device_id":"camera-1"}`,
		"duplicate":         `{"schema_version":"v1","device_id":"a","device_id":"b"}`,
		"escaped duplicate": `{"schema_version":"v1","device_id":"a","device_\u0069d":"b"}`,
		"null field":        `{"schema_version":null,"device_id":"camera-1"}`,
		"number field":      `{"schema_version":"v1","device_id":1}`,
		"surrogate":         `{"schema_version":"v1","device_id":"\ud800"}`,
		"invalid utf8":      strings.Replace(valid, "camera-1", string([]byte{0xff}), 1),
		"force":             `{"schema_version":"v1","device_id":"camera-1","force":true}`,
		"usage":             `{"schema_version":"v1","device_id":"camera-1","unused":true}`,
		"identity":          `{"schema_version":"v1","device_id":"camera-1","scope_id":"spoofed"}`,
		"secret":            `{"schema_version":"v1","device_id":"camera-1","password":"synthetic-private-password"}`,
		"version in body":   `{"schema_version":"v1","device_id":"camera-1","expected_version":1}`,
	} {
		t.Run(name, func(t *testing.T) {
			if input.UnmarshalJSON([]byte(body)) == nil {
				t.Fatal("ambiguous revoke accepted")
			}
			if input.SchemaVersion != "" || input.DeviceID != "" {
				t.Fatal("failed decode retained previous values")
			}
		})
	}
}

func TestCredentialRevokeSemantics(t *testing.T) {
	for _, body := range []string{`{}`, `{"schema_version":"v2","device_id":"camera-1"}`, `{"schema_version":"v1","device_id":"bad/id"}`, `{"schema_version":"v1"}`} {
		var input CredentialRevoke
		if json.Unmarshal([]byte(body), &input) != nil || len(input.Validate()) == 0 {
			t.Fatal("invalid revoke semantics accepted")
		}
	}
}
