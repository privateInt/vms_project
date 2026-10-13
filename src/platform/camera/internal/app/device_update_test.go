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

const testDeviceUpdate = `{"schema_version":"v1","expected_version":1,"display_name":"  renamed  "}`

func TestDeviceUpdateHTTPBoundary(t *testing.T) {
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
		{"disabled", testDeviceUpdate, "REGISTRY_DISABLED", 503, nil},
		{"unauthorized_first", `null`, "UNAUTHORIZED", 401, func(r *http.Request) { r.Header.Del("Authorization"); r.Method = "DELETE"; r.URL.RawQuery = "bad=1" }},
		{"method_first", `null`, "METHOD_NOT_ALLOWED", 405, func(r *http.Request) { r.Method = "PUT"; r.URL.RawQuery = "bad=1" }},
		{"query_before_path", `null`, "QUERY_INVALID", 400, func(r *http.Request) { r.URL.Path = "/api/v1/devices/bad!"; r.URL.RawQuery = "bad=1" }},
		{"bad_query", testDeviceUpdate, "QUERY_INVALID", 400, func(r *http.Request) { r.URL.RawQuery = "%" }},
		{"empty_query", testDeviceUpdate, "QUERY_INVALID", 400, func(r *http.Request) { r.URL.ForceQuery = true }},
		{"path_before_precondition", testDeviceUpdate, "CONTRACT_INVALID", 422, func(r *http.Request) { r.URL.Path = "/api/v1/devices/bad!"; r.Header.Set("If-Match", "1") }},
		{"precondition_before_key", testDeviceUpdate, "PRECONDITION_HEADER_UNSUPPORTED", 400, func(r *http.Request) { r.Header.Set("If-Match", ""); r.Header.Del("Idempotency-Key") }},
		{"if_none_match", testDeviceUpdate, "PRECONDITION_HEADER_UNSUPPORTED", 400, func(r *http.Request) { r.Header.Set("If-None-Match", "*") }},
		{"if_unmodified", testDeviceUpdate, "PRECONDITION_HEADER_UNSUPPORTED", 400, func(r *http.Request) { r.Header.Set("If-Unmodified-Since", "Wed, 30 Sep 2026 01:00:00 GMT") }},
		{"key_before_media", `null`, "IDEMPOTENCY_KEY_INVALID", 400, func(r *http.Request) { r.Header.Del("Idempotency-Key"); r.Header.Set("Content-Type", "text/plain") }},
		{"duplicate_key", testDeviceUpdate, "IDEMPOTENCY_KEY_INVALID", 400, func(r *http.Request) { r.Header.Add("Idempotency-Key", "same-key") }},
		{"key_space", testDeviceUpdate, "IDEMPOTENCY_KEY_INVALID", 400, func(r *http.Request) { r.Header.Set("Idempotency-Key", "not valid") }},
		{"key_unicode", testDeviceUpdate, "IDEMPOTENCY_KEY_INVALID", 400, func(r *http.Request) { r.Header.Set("Idempotency-Key", "한글") }},
		{"key_long", testDeviceUpdate, "IDEMPOTENCY_KEY_INVALID", 400, func(r *http.Request) { r.Header.Set("Idempotency-Key", strings.Repeat("x", 129)) }},
		{"media_before_json", `null`, "UNSUPPORTED_MEDIA_TYPE", 415, func(r *http.Request) { r.Header.Set("Content-Type", "application/merge-patch+json") }},
		{"null", `null`, "INVALID_JSON", 400, nil},
		{"duplicate_field", `{"expected_version":1,"expected_version":1}`, "INVALID_JSON", 400, nil},
		{"float", strings.Replace(testDeviceUpdate, `:1,`, `:1.0,`, 1), "INVALID_JSON", 400, nil},
		{"exponent", strings.Replace(testDeviceUpdate, `:1,`, `:1e0,`, 1), "INVALID_JSON", 400, nil},
		{"overflow", strings.Replace(testDeviceUpdate, `:1,`, `:9223372036854775808,`, 1), "INVALID_JSON", 400, nil},
		{"unknown", `{"password":"never-log"}`, "INVALID_JSON", 400, nil},
		{"immutable", `{"device_kind":"CCTV"}`, "INVALID_JSON", 400, nil},
		{"trailing", testDeviceUpdate + ` {}`, "INVALID_JSON", 400, nil},
		{"missing", `{}`, "CONTRACT_INVALID", 422, nil},
		{"zero", strings.Replace(testDeviceUpdate, `:1,`, `:0,`, 1), "CONTRACT_INVALID", 422, nil},
		{"blank", strings.Replace(testDeviceUpdate, "renamed", "", 1), "CONTRACT_INVALID", 422, nil},
		{"nul", strings.Replace(testDeviceUpdate, "renamed", `\u0000`, 1), "CONTRACT_INVALID", 422, nil},
		{"long_name", strings.Replace(testDeviceUpdate, "renamed", strings.Repeat("가", 129), 1), "CONTRACT_INVALID", 422, nil},
		{"large", strings.Replace(testDeviceUpdate, "renamed", strings.Repeat("x", 65536), 1), "BODY_TOO_LARGE", 413, nil},
		{"large_trailing_whitespace", testDeviceUpdate + strings.Repeat(" ", 65536), "BODY_TOO_LARGE", 413, nil},
		{"body_at_limit", testDeviceUpdate + strings.Repeat(" ", 65536-len(testDeviceUpdate)), "REGISTRY_DISABLED", 503, nil},
		{"max_integer", strings.Replace(testDeviceUpdate, `:1,`, `:9223372036854775807,`, 1), "REGISTRY_DISABLED", 503, nil},
		{"json_charset", testDeviceUpdate, "REGISTRY_DISABLED", 503, func(r *http.Request) { r.Header.Set("Content-Type", "application/json; charset=utf-8") }},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			r := httptest.NewRequest("PATCH", "/api/v1/devices/d1", strings.NewReader(c.body))
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
