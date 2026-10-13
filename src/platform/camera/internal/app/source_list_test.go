package app

import (
	"encoding/json"
	"io"
	"log/slog"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"

	"vms.local/platform/camera/internal/contracts"
)

func TestSourceListHTTPBoundary(t *testing.T) {
	a, err := New(testToken, slog.New(slog.NewTextHandler(io.Discard, nil)))
	if err != nil {
		t.Fatal(err)
	}
	cursor := url.QueryEscape(contracts.EncodeSourceCursor("s1", "d1"))
	for _, c := range []struct {
		query  string
		status int
	}{
		{"", 503}, {"limit=1", 503}, {"limit=200&device_id=d1&cursor=" + cursor, 503},
		{"device_id=absent", 503}, {"limit=0", 400}, {"limit=201", 400}, {"limit=1.5", 400},
		{"limit=99999999999999999999999", 400}, {"limit=", 400}, {"cursor=", 400},
		{"device_id=", 400}, {"device_id=bad!", 400}, {"device_id=" + strings.Repeat("a", 65), 400},
		{"limit=1&limit=2", 400}, {"cursor=x&cursor=y", 400}, {"device_id=d1&device_id=d1", 400},
		{"extra=1", 400}, {"limit=1;device_id=d1", 400}, {"cursor=%xx", 400},
		{"cursor=" + url.QueryEscape(contracts.EncodeDeviceCursor("s1")), 400},
		{"cursor=" + cursor, 400}, {"device_id=d2&cursor=" + cursor, 400},
	} {
		r := httptest.NewRequest("GET", "/api/v1/sources?"+c.query, nil)
		r.Header.Set("Authorization", "Bearer "+testToken)
		w := httptest.NewRecorder()
		a.ServeHTTP(w, r)
		if w.Code != c.status {
			t.Fatalf("%s: want %d got %d (%s)", c.query, c.status, w.Code, w.Body.String())
		}
		if w.Header().Get("X-Request-ID") == "" {
			t.Fatal("missing request ID")
		}
		var value map[string]any
		_ = json.Unmarshal(w.Body.Bytes(), &value)
		want := "QUERY_INVALID"
		if c.status == 503 {
			want = "REGISTRY_DISABLED"
		}
		if value["error"].(map[string]any)["code"] != want {
			t.Fatal(value)
		}
	}
	for _, method := range []string{"GET", "PUT", "HEAD", "DELETE"} {
		r := httptest.NewRequest(method, "/api/v1/sources", nil)
		w := httptest.NewRecorder()
		a.ServeHTTP(w, r)
		if w.Code != 401 {
			t.Fatal("unauthenticated list/method", method, w.Code)
		}
		if method != "GET" {
			r.Header.Set("Authorization", "Bearer "+testToken)
			w = httptest.NewRecorder()
			a.ServeHTTP(w, r)
			if w.Code != 405 || w.Header().Get("Allow") != "GET, POST" {
				t.Fatal("method contract", method, w.Code)
			}
		}
	}
}
