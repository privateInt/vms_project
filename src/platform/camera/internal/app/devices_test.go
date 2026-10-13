package app

import (
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

const testToken = "camera-device-test-token-1234567890"
const testDevice = `{"schema_version":"v1","device_id":"d1","display_name":"입구","device_kind":"CCTV"}`

func TestDeviceHTTPBoundaryWithoutDatabase(t *testing.T) {
	a, err := New(testToken, slog.New(slog.NewTextHandler(io.Discard, nil)))
	if err != nil {
		t.Fatal(err)
	}
	cases := []struct {
		name, method, path, body, media, key, token string
		status                                      int
	}{
		{"auth", "GET", "/api/v1/devices", "", "", "", "", 401},
		{"disabled", "GET", "/api/v1/devices", "", "", "", testToken, 503},
		{"method", "DELETE", "/api/v1/devices", "", "", "", testToken, 405},
		{"get_missing_method", "POST", "/api/v1/devices/d1", testDevice, "application/json", "key", testToken, 405},
		{"key", "POST", "/api/v1/devices", testDevice, "application/json", "", testToken, 400},
		{"media", "POST", "/api/v1/devices", testDevice, "text/plain", "key", testToken, 415},
		{"duplicate", "POST", "/api/v1/devices", `{"device_id":"a","device_id":"b"}`, "application/json", "key", testToken, 400},
		{"null", "POST", "/api/v1/devices", `null`, "application/json", "key", testToken, 400},
		{"unknown", "POST", "/api/v1/devices", `{"password":"never-log"}`, "application/json", "key", testToken, 400},
		{"semantic", "POST", "/api/v1/devices", `{}`, "application/json", "key", testToken, 422},
		{"large", "POST", "/api/v1/devices", `{"display_name":"` + strings.Repeat("x", 65536) + `"}`, "application/json", "key", testToken, 413},
		{"trailing", "POST", "/api/v1/devices", testDevice + ` {}`, "application/json", "key", testToken, 400},
		{"create_disabled", "POST", "/api/v1/devices", testDevice, "application/json", "key", testToken, 503},
		{"limit_zero", "GET", "/api/v1/devices?limit=0", "", "", "", testToken, 400},
		{"limit_large", "GET", "/api/v1/devices?limit=201", "", "", "", testToken, 400},
		{"duplicate_query", "GET", "/api/v1/devices?limit=1&limit=2", "", "", "", testToken, 400},
		{"cursor", "GET", "/api/v1/devices?cursor=broken", "", "", "", testToken, 400},
		{"unknown_query", "GET", "/api/v1/devices?device_kind=CCTV", "", "", "", testToken, 400},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			r := httptest.NewRequest(c.method, c.path, strings.NewReader(c.body))
			r.Header.Set("Content-Type", c.media)
			r.Header.Set("Idempotency-Key", c.key)
			if c.token != "" {
				r.Header.Set("Authorization", "Bearer "+c.token)
			}
			w := httptest.NewRecorder()
			a.ServeHTTP(w, r)
			if w.Code != c.status || w.Header().Get("X-Request-ID") == "" || strings.Contains(w.Body.String(), "never-log") {
				t.Fatalf("status=%d body=%s", w.Code, w.Body.String())
			}
		})
	}
	w := httptest.NewRecorder()
	a.ServeHTTP(w, httptest.NewRequest(http.MethodGet, "/health/ready", nil))
	if w.Code != 200 {
		t.Fatal("disabled mode must retain foundation readiness")
	}
}
