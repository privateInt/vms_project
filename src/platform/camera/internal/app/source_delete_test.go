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

const testSourceDelete = `{"schema_version":"v1","expected_version":1}`

func TestSourceDeleteHTTPBoundary(t *testing.T) {
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
		{"disabled", testSourceDelete, "REGISTRY_DISABLED", 503, nil},
		{"unauthorized_first", `null`, "UNAUTHORIZED", 401, func(r *http.Request) { r.Header.Del("Authorization"); r.Method = "DELETE"; r.URL.RawQuery = "bad=1" }},
		{"method_first", `null`, "METHOD_NOT_ALLOWED", 405, func(r *http.Request) { r.Method = "PUT"; r.URL.RawQuery = "bad=1" }},
		{"query_before_path", `null`, "QUERY_INVALID", 400, func(r *http.Request) { r.URL.Path = "/api/v1/sources/bad!"; r.URL.RawQuery = "bad=1" }},
		{"bad_query", testSourceDelete, "QUERY_INVALID", 400, func(r *http.Request) { r.URL.RawQuery = "%" }},
		{"empty_query", testSourceDelete, "QUERY_INVALID", 400, func(r *http.Request) { r.URL.ForceQuery = true }},
		{"path_before_precondition", testSourceDelete, "CONTRACT_INVALID", 422, func(r *http.Request) { r.URL.Path = "/api/v1/sources/bad!"; r.Header.Set("If-Match", "1") }},
		{"precondition_before_key", testSourceDelete, "PRECONDITION_HEADER_UNSUPPORTED", 400, func(r *http.Request) { r.Header.Set("If-Match", ""); r.Header.Del("Idempotency-Key") }},
		{"if_none_match", testSourceDelete, "PRECONDITION_HEADER_UNSUPPORTED", 400, func(r *http.Request) { r.Header.Set("If-None-Match", "*") }},
		{"if_unmodified", testSourceDelete, "PRECONDITION_HEADER_UNSUPPORTED", 400, func(r *http.Request) { r.Header.Set("If-Unmodified-Since", "Wed, 30 Sep 2026 01:00:00 GMT") }},
		{"key_before_media", `null`, "IDEMPOTENCY_KEY_INVALID", 400, func(r *http.Request) { r.Header.Del("Idempotency-Key"); r.Header.Set("Content-Type", "text/plain") }},
		{"duplicate_key", testSourceDelete, "IDEMPOTENCY_KEY_INVALID", 400, func(r *http.Request) { r.Header.Add("Idempotency-Key", "same-key") }},
		{"key_space", testSourceDelete, "IDEMPOTENCY_KEY_INVALID", 400, func(r *http.Request) { r.Header.Set("Idempotency-Key", "not valid") }},
		{"key_unicode", testSourceDelete, "IDEMPOTENCY_KEY_INVALID", 400, func(r *http.Request) { r.Header.Set("Idempotency-Key", "한글") }},
		{"key_long", testSourceDelete, "IDEMPOTENCY_KEY_INVALID", 400, func(r *http.Request) { r.Header.Set("Idempotency-Key", strings.Repeat("x", 129)) }},
		{"media_before_json", `null`, "UNSUPPORTED_MEDIA_TYPE", 415, func(r *http.Request) { r.Header.Set("Content-Type", "application/merge-patch+json") }},
		{"null", `null`, "INVALID_JSON", 400, nil},
		{"duplicate_field", `{"expected_version":1,"expected_version":1}`, "INVALID_JSON", 400, nil},
		{"float", strings.Replace(testSourceDelete, `:1}`, `:1.0}`, 1), "INVALID_JSON", 400, nil},
		{"exponent", strings.Replace(testSourceDelete, `:1}`, `:1e0}`, 1), "INVALID_JSON", 400, nil},
		{"overflow", strings.Replace(testSourceDelete, `:1}`, `:9223372036854775808}`, 1), "INVALID_JSON", 400, nil},
		{"unknown", `{"password":"never-log"}`, "INVALID_JSON", 400, nil},
		{"force", `{"schema_version":"v1","expected_version":1,"force":true}`, "INVALID_JSON", 400, nil},
		{"immutable", `{"device_id":"d1"}`, "INVALID_JSON", 400, nil},
		{"profiles", `{"profiles":[]}`, "INVALID_JSON", 400, nil},
		{"channel", `{"channel_key":"ch1"}`, "INVALID_JSON", 400, nil},
		{"transport", `{"transport":"RTSP"}`, "INVALID_JSON", 400, nil},
		{"trailing", testSourceDelete + ` {}`, "INVALID_JSON", 400, nil},
		{"missing", `{}`, "CONTRACT_INVALID", 422, nil},
		{"zero", strings.Replace(testSourceDelete, `:1}`, `:0}`, 1), "CONTRACT_INVALID", 422, nil},
		{"large_trailing_whitespace", testSourceDelete + strings.Repeat(" ", 65536), "BODY_TOO_LARGE", 413, nil},
		{"body_at_limit", testSourceDelete + strings.Repeat(" ", 65536-len(testSourceDelete)), "REGISTRY_DISABLED", 503, nil},
		{"max_integer", strings.Replace(testSourceDelete, `:1}`, `:9223372036854775807}`, 1), "REGISTRY_DISABLED", 503, nil},
		{"json_charset", testSourceDelete, "REGISTRY_DISABLED", 503, func(r *http.Request) { r.Header.Set("Content-Type", "application/json; charset=utf-8") }},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			r := httptest.NewRequest("DELETE", "/api/v1/sources/d1", strings.NewReader(c.body))
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

func TestSourceDeleteReservedRoute(t *testing.T) {
	a, err := New(testToken, slog.New(slog.NewTextHandler(&bytes.Buffer{}, nil)))
	if err != nil {
		t.Fatal(err)
	}
	for _, path := range []string{"/api/v1/sources/validate", "/api/v1/sources/%76alidate", "/api/v1/sources/val%69date"} {
		for _, method := range []string{"DELETE"} {
			r := httptest.NewRequest(method, path, strings.NewReader(testSourceDelete))
			r.Header.Set("Authorization", "Bearer "+testToken)
			r.Header.Set("Content-Type", "application/json")
			w := httptest.NewRecorder()
			a.ServeHTTP(w, r)
			if w.Code != 405 || w.Header().Get("Allow") != "POST" {
				t.Fatal("reserved route changed", path, method, w.Code)
			}
		}

	}
	for _, id := range []string{"Validate", "validate-1", "s%31"} {
		r := httptest.NewRequest("DELETE", "/api/v1/sources/"+id, strings.NewReader(testSourceDelete))
		r.Header.Set("Authorization", "Bearer "+testToken)
		r.Header.Set("Content-Type", "application/json")
		r.Header.Set("Idempotency-Key", "route-key")
		w := httptest.NewRecorder()
		a.ServeHTTP(w, r)
		if w.Code != 503 || !strings.Contains(w.Body.String(), "REGISTRY_DISABLED") {
			t.Fatal("nonreserved route rejected", id, w.Code)
		}
	}
	for _, path := range []string{"/api/v1/sources/bad%2Fid", "/api/v1/sources/%76alidate%2Fx", "/api/v1/sources/%252F"} {
		r := httptest.NewRequest("DELETE", path, strings.NewReader(testSourceDelete))
		r.Header.Set("Authorization", "Bearer "+testToken)
		w := httptest.NewRecorder()
		a.ServeHTTP(w, r)
		if w.Code != 422 {
			t.Fatal("invalid decoded ID accepted", path, w.Code)
		}
	}
}
