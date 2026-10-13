package app

import (
	"bytes"
	"encoding/json"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

const testDeviceDelete = `{"schema_version":"v1","expected_version":1}`

func TestDeviceDeleteHTTPBoundary(t *testing.T) {
	var logs bytes.Buffer
	a, err := New(testToken, slog.New(slog.NewTextHandler(&logs, nil)))
	if err != nil {
		t.Fatal(err)
	}
	type edit func(*http.Request)
	cases := []struct {
		name, body, code string
		status           int
		edit             edit
	}{
		{"disabled", testDeviceDelete, "REGISTRY_DISABLED", 503, nil},
		{"unauthorized_first", `null`, "UNAUTHORIZED", 401, func(r *http.Request) { r.Header.Del("Authorization"); r.Method = "DELETE"; r.URL.RawQuery = "bad=1" }},
		{"method_first", `null`, "METHOD_NOT_ALLOWED", 405, func(r *http.Request) { r.Method = "PUT"; r.URL.RawQuery = "bad=1" }},
		{"query_before_path", `null`, "QUERY_INVALID", 400, func(r *http.Request) { r.URL.Path = "/api/v1/devices/bad!"; r.URL.RawQuery = "bad=1" }},
		{"bad_query", testDeviceDelete, "QUERY_INVALID", 400, func(r *http.Request) { r.URL.RawQuery = "%" }},
		{"empty_query", testDeviceDelete, "QUERY_INVALID", 400, func(r *http.Request) { r.URL.ForceQuery = true }},
		{"path_before_precondition", testDeviceDelete, "CONTRACT_INVALID", 422, func(r *http.Request) { r.URL.Path = "/api/v1/devices/bad!"; r.Header.Set("If-Match", "1") }},
		{"precondition_before_key", testDeviceDelete, "PRECONDITION_HEADER_UNSUPPORTED", 400, func(r *http.Request) { r.Header.Set("If-Match", ""); r.Header.Del("Idempotency-Key") }},
		{"if_none_match", testDeviceDelete, "PRECONDITION_HEADER_UNSUPPORTED", 400, func(r *http.Request) { r.Header.Set("If-None-Match", "*") }},
		{"if_unmodified", testDeviceDelete, "PRECONDITION_HEADER_UNSUPPORTED", 400, func(r *http.Request) { r.Header.Set("If-Unmodified-Since", "Wed, 30 Sep 2026 01:00:00 GMT") }},
		{"key_before_media", `null`, "IDEMPOTENCY_KEY_INVALID", 400, func(r *http.Request) { r.Header.Del("Idempotency-Key"); r.Header.Set("Content-Type", "text/plain") }},
		{"duplicate_key", testDeviceDelete, "IDEMPOTENCY_KEY_INVALID", 400, func(r *http.Request) { r.Header.Add("Idempotency-Key", "same-key") }},
		{"key_space", testDeviceDelete, "IDEMPOTENCY_KEY_INVALID", 400, func(r *http.Request) { r.Header.Set("Idempotency-Key", "not valid") }},
		{"key_unicode", testDeviceDelete, "IDEMPOTENCY_KEY_INVALID", 400, func(r *http.Request) { r.Header.Set("Idempotency-Key", "한글") }},
		{"key_long", testDeviceDelete, "IDEMPOTENCY_KEY_INVALID", 400, func(r *http.Request) { r.Header.Set("Idempotency-Key", strings.Repeat("x", 129)) }},
		{"media_before_json", `null`, "UNSUPPORTED_MEDIA_TYPE", 415, func(r *http.Request) { r.Header.Set("Content-Type", "application/merge-patch+json") }},
		{"empty_body", ``, "INVALID_JSON", 400, nil},
		{"null", `null`, "INVALID_JSON", 400, nil},
		{"non_object", `[]`, "INVALID_JSON", 400, nil},
		{"invalid_utf8", `{"schema_version":"` + string([]byte{0xff}) + `","expected_version":1}`, "INVALID_JSON", 400, nil},
		{"null_version", `{"schema_version":"v1","expected_version":null}`, "INVALID_JSON", 400, nil},
		{"string_version", `{"schema_version":"v1","expected_version":"1"}`, "INVALID_JSON", 400, nil},
		{"escaped_duplicate", `{"expected_version":1,"\u0065xpected_version":1}`, "INVALID_JSON", 400, nil},
		{"case_variant", `{"Schema_Version":"v1","expected_version":1}`, "INVALID_JSON", 400, nil},
		{"cascade", `{"schema_version":"v1","expected_version":1,"cascade":true}`, "INVALID_JSON", 400, nil},
		{"negative", `{"schema_version":"v1","expected_version":-1}`, "CONTRACT_INVALID", 422, nil},
		{"wrong_schema", `{"schema_version":"v2","expected_version":1}`, "CONTRACT_INVALID", 422, nil},
		{"duplicate_field", `{"expected_version":1,"expected_version":1}`, "INVALID_JSON", 400, nil},
		{"float", strings.Replace(testDeviceDelete, `:1}`, `:1.0}`, 1), "INVALID_JSON", 400, nil},
		{"exponent", strings.Replace(testDeviceDelete, `:1}`, `:1e0}`, 1), "INVALID_JSON", 400, nil},
		{"overflow", strings.Replace(testDeviceDelete, `:1}`, `:9223372036854775808}`, 1), "INVALID_JSON", 400, nil},
		{"unknown", `{"password":"never-log"}`, "INVALID_JSON", 400, nil},
		{"force", `{"schema_version":"v1","expected_version":1,"force":true}`, "INVALID_JSON", 400, nil},
		{"immutable", `{"device_id":"d1"}`, "INVALID_JSON", 400, nil},
		{"profiles", `{"profiles":[]}`, "INVALID_JSON", 400, nil},
		{"channel", `{"channel_key":"ch1"}`, "INVALID_JSON", 400, nil},
		{"transport", `{"transport":"RTSP"}`, "INVALID_JSON", 400, nil},
		{"trailing", testDeviceDelete + ` {}`, "INVALID_JSON", 400, nil},
		{"missing", `{}`, "CONTRACT_INVALID", 422, nil},
		{"zero", strings.Replace(testDeviceDelete, `:1}`, `:0}`, 1), "CONTRACT_INVALID", 422, nil},
		{"large_trailing_whitespace", testDeviceDelete + strings.Repeat(" ", 65536), "BODY_TOO_LARGE", 413, nil},
		{"body_at_limit", testDeviceDelete + strings.Repeat(" ", 65536-len(testDeviceDelete)), "REGISTRY_DISABLED", 503, nil},
		{"max_integer", strings.Replace(testDeviceDelete, `:1}`, `:9223372036854775807}`, 1), "REGISTRY_DISABLED", 503, nil},
		{"json_charset", testDeviceDelete, "REGISTRY_DISABLED", 503, func(r *http.Request) { r.Header.Set("Content-Type", "application/json; charset=utf-8") }},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			r := httptest.NewRequest("DELETE", "/api/v1/devices/d1", strings.NewReader(c.body))
			r.Header.Set("Authorization", "Bearer "+testToken)
			r.Header.Set("Content-Type", "application/json")
			r.Header.Set("Idempotency-Key", "same-key")
			if c.edit != nil {
				c.edit(r)
			}
			w := httptest.NewRecorder()
			a.ServeHTTP(w, r)
			var value struct {
				Error     struct{ Code string }
				RequestID string `json:"request_id"`
			}
			if json.Unmarshal(w.Body.Bytes(), &value) != nil || w.Code != c.status || value.Error.Code != c.code {
				t.Fatalf("%d %s", w.Code, w.Body.String())
			}
			if value.RequestID == "" || value.RequestID != w.Header().Get("X-Request-ID") || w.Header().Get("Cache-Control") != "no-store" {
				t.Fatal("response metadata")
			}
			if w.Header().Get("Location") != "" || w.Header().Get("Idempotency-Replayed") != "" {
				t.Fatal("success headers on failure")
			}
			if c.status == 405 && w.Header().Get("Allow") != "GET, PATCH, DELETE" {
				t.Fatal("allowed methods")
			}
		})
	}
	if strings.Contains(logs.String(), "never-log") || strings.Contains(logs.String(), testToken) || strings.Contains(logs.String(), "renamed") || strings.Contains(logs.String(), "same-key") {
		t.Fatal("request values leaked into logs")
	}
}

func TestDeviceDeleteDecodedRoutes(t *testing.T) {
	a, err := New(testToken, slog.New(slog.NewTextHandler(&bytes.Buffer{}, nil)))
	if err != nil {
		t.Fatal(err)
	}
	for _, path := range []string{"/api/v1/devices/validate", "/api/v1/devices/%76alidate", "/api/v1/devices/val%69date", "/api/v1/devices/Validate", "/api/v1/devices/d%31"} {
		r := httptest.NewRequest("DELETE", path, strings.NewReader(testDeviceDelete))
		r.Header.Set("Authorization", "Bearer "+testToken)
		r.Header.Set("Content-Type", "application/json")
		r.Header.Set("Idempotency-Key", "route-key")
		w := httptest.NewRecorder()
		a.ServeHTTP(w, r)
		if w.Code != 503 || !strings.Contains(w.Body.String(), "REGISTRY_DISABLED") {
			t.Fatal("valid decoded device ID rejected", path, w.Code)
		}
	}
	for _, path := range []string{"/api/v1/devices/bad%2Fid", "/api/v1/devices/%252F", "/api/v1/devices/%00", "/api/v1/devices/%ED%95%9C"} {
		r := httptest.NewRequest("DELETE", path, strings.NewReader(testDeviceDelete))
		r.Header.Set("Authorization", "Bearer "+testToken)
		w := httptest.NewRecorder()
		a.ServeHTTP(w, r)
		if w.Code != 422 {
			t.Fatal("invalid decoded device ID accepted", path, w.Code)
		}
	}
}
