package httpapi

import (
	"bytes"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

const testToken = "test-token-with-at-least-24-characters"

func newTestAPI(t *testing.T) *API {
	t.Helper()
	a, e := New(Manifest{Platform: "test", Capabilities: map[string]string{}}, testToken, []byte(`{"openapi":"3.1.0"}`), slog.New(slog.NewTextHandler(io.Discard, nil)))
	if e != nil {
		t.Fatal(e)
	}
	return a
}

func TestAuthenticationAndReadinessScope(t *testing.T) {
	a := newTestAPI(t)
	for _, token := range []string{"", "Bearer wrong", "Basic " + testToken} {
		r := httptest.NewRequest("GET", "/api/v1/platform", nil)
		r.Header.Set("Authorization", token)
		w := httptest.NewRecorder()
		a.ServeHTTP(w, r)
		if w.Code != 401 {
			t.Fatalf("got %d", w.Code)
		}
	}
	r := httptest.NewRequest("GET", "/health/ready", nil)
	w := httptest.NewRecorder()
	a.ServeHTTP(w, r)
	if w.Code != 200 || !strings.Contains(w.Body.String(), `"business_runtime_ready":false`) {
		t.Fatal(w.Body.String())
	}
	a.BeginDrain()
	w = httptest.NewRecorder()
	a.ServeHTTP(w, r)
	if w.Code != 503 {
		t.Fatal(w.Code)
	}
}

func TestJSONBoundary(t *testing.T) {
	a := newTestAPI(t)
	a.Handle("/api/test", func(w http.ResponseWriter, r *http.Request) {
		var v struct {
			Name string `json:"name"`
		}
		if DecodeJSON(w, r, &v) {
			WriteJSON(w, 200, v)
		}
	})
	cases := []struct {
		body, media string
		want        int
	}{
		{`{"name":"ok"}`, "application/json", 200},
		{`{"name":"ok","unknown":1}`, "application/json", 400},
		{`{"name":"ok"}{}`, "application/json", 400},
		{`{"name":"ok"}` + strings.Repeat(" ", int(MaxBodyBytes)), "application/json", 413},
		{`{"name":5}`, "application/json", 400},
		{`{}`, "text/plain", 415},
	}
	for _, c := range cases {
		r := httptest.NewRequest("POST", "/api/test", strings.NewReader(c.body))
		r.Header.Set("Content-Type", c.media)
		r.Header.Set("Authorization", "Bearer "+testToken)
		w := httptest.NewRecorder()
		a.ServeHTTP(w, r)
		if w.Code != c.want {
			t.Errorf("want %d got %d", c.want, w.Code)
		}
	}
}

func TestLoggingDoesNotExposeQueryTokenOrBody(t *testing.T) {
	var logs bytes.Buffer
	a, e := New(Manifest{Platform: "test"}, testToken, []byte(`{}`), slog.New(slog.NewJSONHandler(&logs, nil)))
	if e != nil {
		t.Fatal(e)
	}
	r := httptest.NewRequest("GET", "/api/v1/platform?password=secret-query", strings.NewReader("secret-body"))
	r.Header.Set("Authorization", "Bearer "+testToken)
	w := httptest.NewRecorder()
	a.ServeHTTP(w, r)
	for _, secret := range []string{"secret-query", "secret-body", testToken} {
		if strings.Contains(logs.String(), secret) {
			t.Fatal("secret leaked into logs")
		}
	}
	if w.Header().Get("X-Request-ID") == "" {
		t.Fatal("missing request ID")
	}
}

func TestRejectPlaceholderToken(t *testing.T) {
	for _, token := range []string{"", "short", "CHANGE_ME_TO_A_REAL_SECRET_TOKEN"} {
		if _, err := New(Manifest{}, token, nil, nil); err == nil {
			t.Fatal("accepted insecure placeholder")
		}
	}
}
