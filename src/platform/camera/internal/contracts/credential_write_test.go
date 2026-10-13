package contracts

import (
	"encoding/json"
	"fmt"
	"strings"
	"testing"
)

const credentialWriteJSON = `{"schema_version":"v1","device_id":"camera-1","expected_version":0,"target":{"protocol":"RTSP","host":"Camera.Example","port":554},"secret":{"username":"private-user","password":" private-password "}}`

func TestCredentialWriteExactInput(t *testing.T) {
	var input CredentialVersionWrite
	if err := json.Unmarshal([]byte(credentialWriteJSON), &input); err != nil || len(input.Validate()) != 0 {
		t.Fatalf("valid input rejected: %v", err)
	}
	secret, err := input.Secret()
	if err != nil || secret.Username() != "private-user" || secret.Password() != " private-password " || input.Host != "Camera.Example" {
		t.Fatal("input was normalized")
	}
	for _, version := range []string{"0", "1", "9007199254740993", "9223372036854775807"} {
		body := strings.Replace(credentialWriteJSON, `"expected_version":0`, `"expected_version":`+version, 1)
		if json.Unmarshal([]byte(body), &input) != nil || len(input.Validate()) != 0 {
			t.Fatalf("exact integer %s rejected", version)
		}
		if fmt.Sprint(input.ExpectedVersion) != version {
			t.Fatal("integer lost precision")
		}
	}
	unicode := strings.Replace(credentialWriteJSON, " private-password ", `\ud83d\ude00\\uD800`, 1)
	if json.Unmarshal([]byte(unicode), &input) != nil {
		t.Fatal("paired Unicode or escaped literal rejected")
	}
	secret, _ = input.Secret()
	if secret.Password() != "😀\\uD800" {
		t.Fatal("Unicode password changed")
	}
}

func TestCredentialWriteRejectsAmbiguousJSON(t *testing.T) {
	cases := map[string]string{
		"root null": "null", "array": "[]", "trailing": credentialWriteJSON + ` {}`, "invalid syntax": credentialWriteJSON[:len(credentialWriteJSON)-1],
		"unknown":           strings.Replace(credentialWriteJSON, `"schema_version"`, `"scope_id":"spoofed","schema_version"`, 1),
		"case":              strings.Replace(credentialWriteJSON, "device_id", "Device_ID", 1),
		"duplicate":         strings.Replace(credentialWriteJSON, `"expected_version":0`, `"expected_version":0,"expected_version":1`, 1),
		"escaped duplicate": strings.Replace(credentialWriteJSON, `"password":" private-password "`, `"password":"x","pass\u0077ord":"y"`, 1),
		"nested duplicate":  strings.Replace(credentialWriteJSON, `"port":554`, `"port":554,"port":555`, 1),
		"nested unknown":    strings.Replace(credentialWriteJSON, `"port":554`, `"port":554,"network_policy":"allow"`, 1),
		"secret case":       strings.Replace(credentialWriteJSON, "username", "Username", 1),
		"secret null":       strings.Replace(credentialWriteJSON, `"username":"private-user"`, `"username":null`, 1),
		"secret array":      strings.Replace(credentialWriteJSON, `"secret":{`, `"secret":[{`, 1) + "]",
		"host null":         strings.Replace(credentialWriteJSON, `"host":"Camera.Example"`, `"host":null`, 1),
		"high surrogate":    strings.Replace(credentialWriteJSON, " private-password ", `\ud800`, 1),
		"low surrogate":     strings.Replace(credentialWriteJSON, " private-password ", `\udc00`, 1),
		"wrong pair":        strings.Replace(credentialWriteJSON, " private-password ", `\ud800\u0061`, 1),
		"invalid utf8":      strings.Replace(credentialWriteJSON, "private-user", string([]byte{0xff}), 1),
	}
	for _, number := range []string{"null", `"0"`, "true", "0.0", "1e0", "9223372036854775808", "-9223372036854775809", "[]", "{}"} {
		cases["version "+number] = strings.Replace(credentialWriteJSON, `"expected_version":0`, `"expected_version":`+number, 1)
		cases["port "+number] = strings.Replace(credentialWriteJSON, `"port":554`, `"port":`+number, 1)
	}
	for name, body := range cases {
		t.Run(name, func(t *testing.T) {
			var input CredentialVersionWrite
			if json.Unmarshal([]byte(body), &input) == nil {
				t.Fatal("ambiguous input accepted")
			}
		})
	}
}

func TestCredentialWriteSemanticValidation(t *testing.T) {
	cases := map[string]string{
		"missing version":  strings.Replace(credentialWriteJSON, `"expected_version":0,`, "", 1),
		"negative version": strings.Replace(credentialWriteJSON, `"expected_version":0`, `"expected_version":-1`, 1),
		"missing secret":   strings.Replace(credentialWriteJSON, `,"secret":{"username":"private-user","password":" private-password "}`, "", 1),
		"empty password":   strings.Replace(credentialWriteJSON, " private-password ", "", 1),
		"blank username":   strings.Replace(credentialWriteJSON, "private-user", "  ", 1),
		"username length":  strings.Replace(credentialWriteJSON, "private-user", strings.Repeat("a", 129), 1),
		"password length":  strings.Replace(credentialWriteJSON, " private-password ", strings.Repeat("a", 4097), 1),
		"password control": strings.Replace(credentialWriteJSON, " private-password ", `abc\u0000`, 1),
		"device":           strings.Replace(credentialWriteJSON, "camera-1", "bad/id", 1),
		"schema":           strings.Replace(credentialWriteJSON, "v1", "v2", 1),
		"port":             strings.Replace(credentialWriteJSON, `"port":554`, `"port":65536`, 1),
		"target":           strings.Replace(credentialWriteJSON, "Camera.Example", "user@Camera.Example", 1),
	}
	for name, body := range cases {
		t.Run(name, func(t *testing.T) {
			var input CredentialVersionWrite
			if err := json.Unmarshal([]byte(body), &input); err != nil {
				t.Fatalf("semantic case failed parsing: %v", err)
			}
			if len(input.Validate()) == 0 {
				t.Fatal("invalid semantics accepted")
			}
			violations, _ := json.Marshal(input.Validate())
			for _, private := range []string{"private-user", "private-password", "Camera.Example", "user@"} {
				if strings.Contains(string(violations), private) {
					t.Fatal("private input in validation error")
				}
			}
		})
	}
}

func TestCredentialWriteDisclosureAndClear(t *testing.T) {
	var input CredentialVersionWrite
	if json.Unmarshal([]byte(credentialWriteJSON), &input) != nil {
		t.Fatal("input")
	}
	for _, value := range []any{input, &input} {
		for _, format := range []string{"%v", "%+v", "%#v", "%s", "%q"} {
			text := fmt.Sprintf(format, value)
			for _, private := range []string{"private-user", "private-password", "Camera.Example"} {
				if strings.Contains(text, private) {
					t.Fatal("format disclosed private input")
				}
			}
		}
		if body, err := json.Marshal(value); err == nil || len(body) != 0 {
			t.Fatal("private DTO serialized")
		}
	}
	// Direct decoder failure must discard a previously populated reusable DTO.
	if input.UnmarshalJSON([]byte(`{"secret":{"password":"new"},"unknown":1}`)) == nil {
		t.Fatal("unknown field accepted")
	}
	if input.Host != "" || input.DeviceID != "" || input.username != "" || input.password != "" {
		t.Fatal("failed decode retained private values")
	}
}

func TestCredentialTargetSyntax(t *testing.T) {
	for _, host := range []string{"camera.example", "Camera.Example", "192.168.0.10", "2001:db8::1"} {
		if !ValidCredentialTarget("RTSP", host, 554) {
			t.Fatalf("valid host %s rejected", host)
		}
	}
	for _, host := range []string{"camera", "192.168.000.10", "2001:DB8::1", "fe80::1%eth0", "[2001:db8::1]", "camera.example.", "user@camera.example", "camera.example/path", " camera.example", "camera..example", "camera.123", "-camera.example"} {
		if ValidCredentialTarget("RTSP", host, 554) {
			t.Fatalf("invalid host %s accepted", host)
		}
	}
	if ValidCredentialTarget("rtsp", "camera.example", 554) || ValidCredentialTarget("RTSP", "camera.example", 0) {
		t.Fatal("invalid protocol/port accepted")
	}
}
