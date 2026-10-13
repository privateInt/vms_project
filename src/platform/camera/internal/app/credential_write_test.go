package app

import (
	"bytes"
	"context"
	"crypto/tls"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
	"vms.local/platform/camera/internal/storage"
	"vms.local/platform/internal/httpapi"
)

const credentialToken = "synthetic-credential-http-token-123"
const credentialBody = `{"schema_version":"v1","device_id":"camera-1","expected_version":0,"target":{"protocol":"RTSP","host":"private.camera.example","port":554},"secret":{"username":"private-user-123","password":" private-password-123 "}}`
const credentialPath = "/api/v1/credentials/credential-1/versions"

type credentialWriterFunc func(context.Context, storage.CredentialIdentity, storage.CredentialWrite, storage.CredentialAuthorizer) (storage.CredentialMetadata, bool, error)

func (f credentialWriterFunc) WriteVersion(c context.Context, i storage.CredentialIdentity, w storage.CredentialWrite, a storage.CredentialAuthorizer) (storage.CredentialMetadata, bool, error) {
	return f(c, i, w, a)
}
func credentialPrincipal(context.Context) (string, string, bool, error) {
	return "scope-1", "subject-1", true, nil
}
func credentialAuthorization(context.Context, pgx.Tx, storage.CredentialAccess) (bool, error) {
	return true, nil
}

func credentialTestAPI(t *testing.T, writer credentialVersionWriter, principal CredentialPrincipalResolver, logs *bytes.Buffer) *httpapi.API {
	t.Helper()
	a, err := New(credentialToken, slog.New(slog.NewJSONHandler(logs, nil)))
	if err != nil {
		t.Fatal(err)
	}
	registerCredentialWrites(a, writer, principal, credentialAuthorization)
	return a
}
func credentialRequest(method, path, body string) *http.Request {
	r := httptest.NewRequest(method, "https://camera.example"+path, strings.NewReader(body))
	r.TLS = &tls.ConnectionState{HandshakeComplete: true, Version: tls.VersionTLS13}
	r.Header.Set("Authorization", "Bearer "+credentialToken)
	r.Header.Set("Content-Type", "application/json")
	r.Header.Set("Idempotency-Key", "request-1")
	return r
}
func credentialStatus(t *testing.T, api http.Handler, r *http.Request, status int, code string) *httptest.ResponseRecorder {
	t.Helper()
	response := httptest.NewRecorder()
	api.ServeHTTP(response, r)
	if response.Code != status {
		t.Fatalf("status %d, want %d: %s", response.Code, status, response.Body.String())
	}
	if code != "" {
		var problem struct{ Error struct{ Code string } }
		if json.Unmarshal(response.Body.Bytes(), &problem) != nil || problem.Error.Code != code {
			t.Fatalf("unexpected safe error: %s", response.Body.String())
		}
	}
	if response.Header().Get("Cache-Control") != "no-store" || response.Header().Get("X-Request-ID") == "" {
		t.Fatal("missing safe response headers")
	}
	return response
}
func credentialSafe(t *testing.T, output string) {
	t.Helper()
	for _, private := range []string{"private.camera.example", "private-user-123", "private-password-123", credentialToken, "SYNTHETIC_SQL_PRIVATE"} {
		if strings.Contains(output, private) {
			t.Fatal("private value disclosed")
		}
	}
}

func TestCredentialHTTPWriteAndReplay(t *testing.T) {
	var logs bytes.Buffer
	calls := 0
	created := time.Date(2026, 10, 8, 0, 0, 0, 0, time.UTC)
	writer := credentialWriterFunc(func(ctx context.Context, identity storage.CredentialIdentity, command storage.CredentialWrite, authorize storage.CredentialAuthorizer) (storage.CredentialMetadata, bool, error) {
		calls++
		if identity.ScopeID != "scope-1" || identity.PrincipalID != "subject-1" || identity.IdempotencyKey != "request-1" || command.CredentialID != "credential-1" || command.DeviceID != "camera-1" || command.Target.Host != "private.camera.example" || command.Secret.Password() != " private-password-123 " || authorize == nil {
			t.Fatal("incorrect store arguments")
		}
		if deadline, ok := ctx.Deadline(); !ok || time.Until(deadline) > 8*time.Second {
			t.Fatal("missing bounded operation")
		}
		return storage.CredentialMetadata{CredentialID: command.CredentialID, DeviceID: command.DeviceID, Version: command.ExpectedVersion + 1, CreatedAt: created}, calls == 2, nil
	})
	api := credentialTestAPI(t, writer, credentialPrincipal, &logs)
	var first []byte
	for index := 0; index < 2; index++ {
		r := credentialRequest("POST", credentialPath, credentialBody)
		r.Header.Set("X-Principal-ID", "spoofed")
		r.Header.Set("X-Scope-ID", "spoofed")
		response := credentialStatus(t, api, r, 201, "")
		if response.Header().Get("Idempotency-Replayed") != []string{"false", "true"}[index] {
			t.Fatal("replay flag")
		}
		var result map[string]json.RawMessage
		if json.Unmarshal(response.Body.Bytes(), &result) != nil || len(result) != 2 {
			t.Fatal("receipt shape")
		}
		if index == 0 {
			first = result["credential"]
		} else if !bytes.Equal(first, result["credential"]) {
			t.Fatal("replay metadata changed")
		}
		credentialSafe(t, response.Body.String())
	}
	response := credentialStatus(t, api, credentialRequest("POST", credentialPath, strings.Replace(credentialBody, `"expected_version":0`, `"expected_version":1`, 1)), 201, "")
	if !strings.Contains(response.Body.String(), `"credential_version":2`) {
		t.Fatal("replacement did not create version 2")
	}
	credentialSafe(t, logs.String())
}

func TestCredentialHTTPValidationOrder(t *testing.T) {
	var logs bytes.Buffer
	calls := 0
	writer := credentialWriterFunc(func(context.Context, storage.CredentialIdentity, storage.CredentialWrite, storage.CredentialAuthorizer) (storage.CredentialMetadata, bool, error) {
		calls++
		return storage.CredentialMetadata{}, false, errors.New("SYNTHETIC_SQL_PRIVATE")
	})
	api := credentialTestAPI(t, writer, credentialPrincipal, &logs)
	cases := []struct {
		name   string
		mutate func(*http.Request)
		status int
		code   string
	}{
		{"auth", func(r *http.Request) { r.Header.Del("Authorization"); r.Method = "GET" }, 401, "UNAUTHORIZED"},
		{"plaintext", func(r *http.Request) { r.TLS = nil; r.Header.Set("X-Forwarded-Proto", "https") }, 403, "CREDENTIAL_TRANSPORT_REQUIRED"},
		{"old tls", func(r *http.Request) { r.TLS.Version = tls.VersionTLS11 }, 403, "CREDENTIAL_TRANSPORT_REQUIRED"},
		{"unfinished tls", func(r *http.Request) { r.TLS.HandshakeComplete = false }, 403, "CREDENTIAL_TRANSPORT_REQUIRED"},
		{"method", func(r *http.Request) { r.Method = "GET"; r.URL.RawQuery = "secret=private-password-123" }, 405, "METHOD_NOT_ALLOWED"},
		{"query", func(r *http.Request) { r.URL.RawQuery = "bad=1" }, 400, "QUERY_INVALID"},
		{"empty query", func(r *http.Request) { r.URL.ForceQuery = true }, 400, "QUERY_INVALID"},
		{"path", func(r *http.Request) { r.URL.Path = "/api/v1/credentials/bad@id/versions" }, 422, "CONTRACT_INVALID"},
		{"precondition", func(r *http.Request) { r.Header["If-Match"] = []string{""}; r.Header.Del("Idempotency-Key") }, 400, "PRECONDITION_HEADER_UNSUPPORTED"},
		{"missing key", func(r *http.Request) { r.Header.Del("Idempotency-Key") }, 400, "IDEMPOTENCY_KEY_INVALID"},
		{"repeated key", func(r *http.Request) { r.Header.Add("Idempotency-Key", "second") }, 400, "IDEMPOTENCY_KEY_INVALID"},
		{"key space", func(r *http.Request) { r.Header.Set("Idempotency-Key", "bad key") }, 400, "IDEMPOTENCY_KEY_INVALID"},
		{"media", func(r *http.Request) { r.Header.Set("Content-Type", "text/plain") }, 415, "UNSUPPORTED_MEDIA_TYPE"},
		{"body", func(r *http.Request) {
			r.Body = io.NopCloser(strings.NewReader(`{"secret":{"password":"private-password-123"},"unknown":1}`))
		}, 400, "INVALID_JSON"},
		{"duplicate nested", func(r *http.Request) {
			r.Body = io.NopCloser(strings.NewReader(strings.Replace(credentialBody, `"port":554`, `"port":554,"port":555`, 1)))
		}, 400, "INVALID_JSON"},
		{"trailing", func(r *http.Request) { r.Body = io.NopCloser(strings.NewReader(credentialBody + " {}")) }, 400, "INVALID_JSON"},
		{"semantics", func(r *http.Request) {
			r.Body = io.NopCloser(strings.NewReader(strings.Replace(credentialBody, `"expected_version":0`, `"expected_version":-1`, 1)))
		}, 422, "CONTRACT_INVALID"},
		{"too large", func(r *http.Request) {
			r.Body = io.NopCloser(strings.NewReader(strings.Replace(credentialBody, "private-password-123", strings.Repeat("x", 65536), 1)))
		}, 413, "BODY_TOO_LARGE"},
	}
	for _, test := range cases {
		t.Run(test.name, func(t *testing.T) {
			r := credentialRequest("POST", credentialPath, credentialBody)
			test.mutate(r)
			response := credentialStatus(t, api, r, test.status, test.code)
			credentialSafe(t, response.Body.String())
		})
	}
	if calls != 0 {
		t.Fatal("invalid request reached storage")
	}
	credentialSafe(t, logs.String())
}

func TestCredentialHTTPAuthorization(t *testing.T) {
	for _, test := range []struct {
		name     string
		resolver CredentialPrincipalResolver
		status   int
		code     string
	}{
		{"denied", func(context.Context) (string, string, bool, error) { return "scope-1", "subject-1", false, nil }, 403, "FORBIDDEN"},
		{"unavailable", func(context.Context) (string, string, bool, error) {
			return "scope-1", "subject-1", true, errors.New("SYNTHETIC_SQL_PRIVATE")
		}, 503, "CREDENTIAL_AUTHORIZATION_UNAVAILABLE"},
		{"invalid identity", func(context.Context) (string, string, bool, error) { return "bad/id", "subject-1", true, nil }, 503, "CREDENTIAL_AUTHORIZATION_UNAVAILABLE"},
	} {
		t.Run(test.name, func(t *testing.T) {
			var logs bytes.Buffer
			writer := credentialWriterFunc(func(context.Context, storage.CredentialIdentity, storage.CredentialWrite, storage.CredentialAuthorizer) (storage.CredentialMetadata, bool, error) {
				t.Fatal("unauthorized request reached storage")
				return storage.CredentialMetadata{}, false, nil
			})
			api := credentialTestAPI(t, writer, test.resolver, &logs)
			r := credentialRequest("GET", credentialPath, "malformed private-password-123")
			response := credentialStatus(t, api, r, test.status, test.code)
			credentialSafe(t, response.Body.String()+logs.String())
		})
	}
}

func TestCredentialHTTPStoreErrorsAreSafe(t *testing.T) {
	for _, code := range []string{"CREDENTIAL_EXISTS", "CREDENTIAL_UNAVAILABLE", "CREDENTIAL_VERSION_CONFLICT", "CREDENTIAL_VERSION_EXHAUSTED", "DEVICE_UNAVAILABLE", "IDEMPOTENCY_CONFLICT", "CREDENTIAL_AUTHORIZATION_UNAVAILABLE", "CREDENTIAL_ADMISSION_UNAVAILABLE", "CREDENTIAL_ENCRYPTION_FAILED", "SYNTHETIC_SQL_PRIVATE"} {
		t.Run(code, func(t *testing.T) {
			var logs bytes.Buffer
			writer := credentialWriterFunc(func(context.Context, storage.CredentialIdentity, storage.CredentialWrite, storage.CredentialAuthorizer) (storage.CredentialMetadata, bool, error) {
				return storage.CredentialMetadata{}, false, &storage.Error{Code: code}
			})
			api := credentialTestAPI(t, writer, credentialPrincipal, &logs)
			status := 409
			expected := code
			if strings.HasSuffix(code, "UNAVAILABLE") && code != "DEVICE_UNAVAILABLE" && code != "CREDENTIAL_UNAVAILABLE" {
				status = 503
			}
			if code == "CREDENTIAL_ENCRYPTION_FAILED" || code == "SYNTHETIC_SQL_PRIVATE" {
				status = 503
				expected = "CREDENTIAL_STORE_UNAVAILABLE"
			}
			response := credentialStatus(t, api, credentialRequest("POST", credentialPath, credentialBody), status, expected)
			credentialSafe(t, response.Body.String()+logs.String())
		})
	}
}

func TestCredentialHTTPNoImplicitActivation(t *testing.T) {
	var logs bytes.Buffer
	api, err := New(credentialToken, slog.New(slog.NewJSONHandler(&logs, nil)))
	if err != nil {
		t.Fatal(err)
	}
	credentialStatus(t, api, credentialRequest("POST", credentialPath, credentialBody), 404, "NOT_FOUND")
	if RegisterCredentialWrites(api, nil, credentialPrincipal, credentialAuthorization) == nil || RegisterCredentialWrites(api, &storage.CredentialStore{}, nil, credentialAuthorization) == nil || RegisterCredentialWrites(api, &storage.CredentialStore{}, credentialPrincipal, nil) == nil {
		t.Fatal("incomplete configuration installed")
	}
	credentialStatus(t, api, credentialRequest("POST", credentialPath, credentialBody), 404, "NOT_FOUND")
	// Exercise the concrete storage path, rather than a synthetic operation guard.
	if RegisterCredentialWrites(api, &storage.CredentialStore{}, credentialPrincipal, credentialAuthorization) != nil {
		t.Fatal("register")
	}
	response := credentialStatus(t, api, credentialRequest("POST", credentialPath, credentialBody), 503, "CREDENTIAL_ADMISSION_UNAVAILABLE")
	credentialSafe(t, response.Body.String()+logs.String())
}

func TestCredentialHTTPRejectsInconsistentReceipt(t *testing.T) {
	for _, kind := range []string{"id", "device", "version", "time", "revoked"} {
		t.Run(kind, func(t *testing.T) {
			var logs bytes.Buffer
			writer := credentialWriterFunc(func(context.Context, storage.CredentialIdentity, storage.CredentialWrite, storage.CredentialAuthorizer) (storage.CredentialMetadata, bool, error) {
				at := time.Now()
				result := storage.CredentialMetadata{CredentialID: "credential-1", DeviceID: "camera-1", Version: 1, CreatedAt: at}
				switch kind {
				case "id":
					result.CredentialID = "wrong"
				case "device":
					result.DeviceID = "wrong"
				case "version":
					result.Version = 2
				case "time":
					result.CreatedAt = time.Time{}
				case "revoked":
					result.RevokedAt = &at
				}
				return result, false, nil
			})
			api := credentialTestAPI(t, writer, credentialPrincipal, &logs)
			credentialStatus(t, api, credentialRequest("POST", credentialPath, credentialBody), 503, "CREDENTIAL_STORE_UNAVAILABLE")
		})
	}
}

func TestCredentialHTTPActualTLS(t *testing.T) {
	var logs bytes.Buffer
	writer := credentialWriterFunc(func(_ context.Context, _ storage.CredentialIdentity, w storage.CredentialWrite, _ storage.CredentialAuthorizer) (storage.CredentialMetadata, bool, error) {
		return storage.CredentialMetadata{CredentialID: w.CredentialID, DeviceID: w.DeviceID, Version: 1, CreatedAt: time.Now()}, false, nil
	})
	api := credentialTestAPI(t, writer, credentialPrincipal, &logs)
	server := httptest.NewTLSServer(api)
	defer server.Close()
	r, err := http.NewRequest("POST", server.URL+credentialPath, strings.NewReader(credentialBody))
	if err != nil {
		t.Fatal(err)
	}
	r.Header = credentialRequest("POST", credentialPath, credentialBody).Header
	response, err := server.Client().Do(r)
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	body, err := io.ReadAll(response.Body)
	if err != nil || response.StatusCode != 201 {
		t.Fatal("actual TLS write failed")
	}
	credentialSafe(t, string(body)+logs.String())
}
