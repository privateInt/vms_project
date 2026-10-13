package app

import (
	"io"
	"log/slog"
	"net/http/httptest"
	"strings"
	"testing"
)

const testSource = `{"schema_version":"v1","source_id":"s1","device_id":"d1","channel_key":"ch1","display_name":"입구 영상","transport":"RTSP","input_mode":"PULL","motion_mode":"UNKNOWN","profiles":[{"profile_id":"main","codec":"H264","width":1920,"height":1080,"fps":30},{"profile_id":"sub","codec":"H264","width":640,"height":360,"fps":15}]}`

func TestSourceHTTPBoundaryWithoutDatabase(t *testing.T) {
	a, err := New(testToken, slog.New(slog.NewTextHandler(io.Discard, nil)))
	if err != nil {
		t.Fatal(err)
	}
	for _, c := range []struct {
		name, method, path, body, media, key, token string
		status                                      int
	}{
		{"auth", "POST", "/api/v1/sources", testSource, "application/json", "k", "", 401},
		{"disabled", "POST", "/api/v1/sources", testSource, "application/json", "k", testToken, 503},
		{"get_disabled", "GET", "/api/v1/sources/s1", "", "", "", testToken, 503},
		{"validation_route_preserved", "GET", "/api/v1/sources/validate", "", "", "", testToken, 405},
		{"list_disabled", "GET", "/api/v1/sources", "", "", "", testToken, 503},
		{"method", "PUT", "/api/v1/sources/s1", testSource, "application/json", "k", testToken, 405},
		{"key", "POST", "/api/v1/sources", testSource, "application/json", "", testToken, 400},
		{"media", "POST", "/api/v1/sources", testSource, "text/plain", "k", testToken, 415},
		{"null", "POST", "/api/v1/sources", "null", "application/json", "k", testToken, 400},
		{"duplicate_profile_field", "POST", "/api/v1/sources", strings.Replace(testSource, `"fps":30`, `"fps":30,"fps":15`, 1), "application/json", "k", testToken, 400},
		{"duplicate_profile_id", "POST", "/api/v1/sources", strings.Replace(testSource, `"profile_id":"sub"`, `"profile_id":"main"`, 1), "application/json", "k", testToken, 422},
		{"semantic", "POST", "/api/v1/sources", strings.Replace(testSource, `"channel_key":"ch1"`, `"channel_key":""`, 1), "application/json", "k", testToken, 422},
		{"query", "POST", "/api/v1/sources?extra=1", testSource, "application/json", "k", testToken, 400},
		{"get_query", "GET", "/api/v1/sources/s1?extra=1", "", "", "", testToken, 400},
		{"invalid_id", "GET", "/api/v1/sources/bad!", "", "", "", testToken, 422},
		{"large", "POST", "/api/v1/sources", strings.Repeat(" ", 65537) + testSource, "application/json", "k", testToken, 413},
		{"trailing", "POST", "/api/v1/sources", testSource + " {}", "application/json", "k", testToken, 400},
	} {
		t.Run(c.name, func(t *testing.T) {
			r := httptest.NewRequest(c.method, c.path, strings.NewReader(c.body))
			r.Header.Set("Content-Type", c.media)
			if c.key != "" {
				r.Header.Set("Idempotency-Key", c.key)
			}
			if c.token != "" {
				r.Header.Set("Authorization", "Bearer "+c.token)
			}
			w := httptest.NewRecorder()
			a.ServeHTTP(w, r)
			if w.Code != c.status {
				t.Fatalf("want %d got %d: %s", c.status, w.Code, w.Body.String())
			}
		})
	}
}
