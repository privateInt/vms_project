package app

import (
	"bytes"
	"context"
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

const credentialVersionPath = "/api/v1/credentials/credential-1/versions/1"
const credentialRevokeBody = `{"schema_version":"v1","device_id":"camera-1"}`

type credentialManagerStub struct {
	get    func(context.Context, storage.CredentialIdentity, string, int64, storage.CredentialAuthorizer) (storage.CredentialMetadata, error)
	revoke func(context.Context, storage.CredentialIdentity, storage.CredentialReference, storage.CredentialAuthorizer, storage.CredentialRevokeGuard) (storage.CredentialMetadata, bool, error)
}

func (m credentialManagerStub) GetVersionMetadata(c context.Context, i storage.CredentialIdentity, id string, v int64, a storage.CredentialAuthorizer) (storage.CredentialMetadata, error) {
	return m.get(c, i, id, v, a)
}
func (m credentialManagerStub) RevokeVersion(c context.Context, i storage.CredentialIdentity, r storage.CredentialReference, a storage.CredentialAuthorizer, g storage.CredentialRevokeGuard) (storage.CredentialMetadata, bool, error) {
	return m.revoke(c, i, r, a, g)
}
func credentialUnused(context.Context, pgx.Tx, storage.CredentialReference) (storage.CredentialUsage, error) {
	return storage.CredentialUsageUnused, nil
}
func credentialMetadataFixture() storage.CredentialMetadata {
	return storage.CredentialMetadata{CredentialID: "credential-1", DeviceID: "camera-1", Version: 1, CreatedAt: time.Date(2026, 10, 8, 0, 0, 0, 0, time.UTC)}
}
func credentialVersionRequest(method, path, body string) *http.Request {
	r := credentialRequest(method, path, body)
	if body == "" {
		r.Body = http.NoBody
		r.ContentLength = 0
	}
	return r
}
func credentialVersionsAPI(t *testing.T, manager credentialVersionManager, resolver CredentialPrincipalResolver, logs *bytes.Buffer) *httpapi.API {
	t.Helper()
	api, err := New(credentialToken, slog.New(slog.NewJSONHandler(logs, nil)))
	if err != nil {
		t.Fatal(err)
	}
	registerCredentialVersions(api, manager, resolver, credentialAuthorization, credentialUnused)
	return api
}

func TestCredentialVersionsHTTPMetadata(t *testing.T) {
	var logs bytes.Buffer
	calls := 0
	revoked := false
	manager := credentialManagerStub{get: func(ctx context.Context, i storage.CredentialIdentity, id string, version int64, a storage.CredentialAuthorizer) (storage.CredentialMetadata, error) {
		calls++
		if i.ScopeID != "scope-1" || i.PrincipalID != "subject-1" || i.IdempotencyKey != "" || id != "credential-1" || version != 1 || a == nil {
			t.Fatal("incorrect metadata arguments")
		}
		if deadline, ok := ctx.Deadline(); !ok || time.Until(deadline) > 8*time.Second {
			t.Fatal("unbounded read")
		}
		m := credentialMetadataFixture()
		if revoked {
			at := m.CreatedAt.Add(time.Second)
			m.RevokedAt = &at
		}
		return m, nil
	}}
	api := credentialVersionsAPI(t, manager, credentialPrincipal, &logs)
	for _, state := range []bool{false, true} {
		revoked = state
		r := credentialVersionRequest("GET", credentialVersionPath, "")
		r.Header.Del("Idempotency-Key")
		r.Header.Del("Content-Type")
		r.Header.Set("X-Principal-ID", "spoofed")
		response := credentialStatus(t, api, r, 200, "")
		credentialSafe(t, response.Body.String())
		if response.Header().Get("Idempotency-Replayed") != "" {
			t.Fatal("metadata marked as mutation replay")
		}
		var result map[string]json.RawMessage
		if json.Unmarshal(response.Body.Bytes(), &result) != nil || len(result) != 2 {
			t.Fatal("unsafe envelope")
		}
		var m map[string]any
		_ = json.Unmarshal(result["credential"], &m)
		want := 4
		if state {
			want = 5
		}
		if len(m) != want {
			t.Fatal("unexpected metadata fields")
		}
		if strings.Contains(response.Body.String(), "ready") || strings.Contains(response.Body.String(), "target") {
			t.Fatal("inspection claimed readiness or returned private target")
		}
	}
	if calls != 2 {
		t.Fatal("read count")
	}
	credentialSafe(t, logs.String())
}

func TestCredentialVersionsHTTPRevokeReplay(t *testing.T) {
	var logs bytes.Buffer
	calls := 0
	metadata := credentialMetadataFixture()
	at := metadata.CreatedAt.Add(time.Second)
	metadata.RevokedAt = &at
	manager := credentialManagerStub{revoke: func(ctx context.Context, i storage.CredentialIdentity, ref storage.CredentialReference, a storage.CredentialAuthorizer, g storage.CredentialRevokeGuard) (storage.CredentialMetadata, bool, error) {
		calls++
		if i.ScopeID != "scope-1" || i.PrincipalID != "subject-1" || i.IdempotencyKey != "request-1" || ref.CredentialID != "credential-1" || ref.DeviceID != "camera-1" || ref.Version != 1 || a == nil || g == nil {
			t.Fatal("incorrect revoke arguments")
		}
		usage, err := g(ctx, nil, ref)
		if err != nil || usage != storage.CredentialUsageUnused {
			t.Fatal("guard not forwarded")
		}
		if deadline, ok := ctx.Deadline(); !ok || time.Until(deadline) > 8*time.Second {
			t.Fatal("unbounded revoke")
		}
		return metadata, calls == 2, nil
	}}
	api := credentialVersionsAPI(t, manager, credentialPrincipal, &logs)
	var original []byte
	for index := 0; index < 2; index++ {
		r := credentialVersionRequest("DELETE", credentialVersionPath, credentialRevokeBody)
		r.Header.Set("X-Scope-ID", "spoofed")
		response := credentialStatus(t, api, r, 200, "")
		credentialSafe(t, response.Body.String())
		if response.Header().Get("Idempotency-Replayed") != []string{"false", "true"}[index] {
			t.Fatal("replay flag")
		}
		var result map[string]json.RawMessage
		_ = json.Unmarshal(response.Body.Bytes(), &result)
		if index == 0 {
			original = result["credential"]
		} else if !bytes.Equal(original, result["credential"]) {
			t.Fatal("revocation time changed on replay")
		}
	}
	credentialSafe(t, logs.String())
}

func TestCredentialVersionsHTTPValidationOrder(t *testing.T) {
	var logs bytes.Buffer
	calls := 0
	manager := credentialManagerStub{
		get: func(context.Context, storage.CredentialIdentity, string, int64, storage.CredentialAuthorizer) (storage.CredentialMetadata, error) {
			calls++
			return storage.CredentialMetadata{}, nil
		},
		revoke: func(context.Context, storage.CredentialIdentity, storage.CredentialReference, storage.CredentialAuthorizer, storage.CredentialRevokeGuard) (storage.CredentialMetadata, bool, error) {
			calls++
			return storage.CredentialMetadata{}, false, nil
		},
	}
	api := credentialVersionsAPI(t, manager, credentialPrincipal, &logs)
	for _, test := range []struct {
		name, method string
		mutate       func(*http.Request)
		status       int
		code         string
	}{
		{"auth", "DELETE", func(r *http.Request) { r.Header.Del("Authorization"); r.Method = "POST" }, 401, "UNAUTHORIZED"},
		{"plaintext", "GET", func(r *http.Request) { r.TLS = nil; r.Header.Set("X-Forwarded-Proto", "https") }, 403, "CREDENTIAL_TRANSPORT_REQUIRED"},
		{"method", "GET", func(r *http.Request) { r.Method = "POST"; r.URL.RawQuery = "password=private-password-123" }, 405, "METHOD_NOT_ALLOWED"},
		{"query", "GET", func(r *http.Request) { r.URL.RawQuery = "device_id=spoofed" }, 400, "QUERY_INVALID"},
		{"empty query", "DELETE", func(r *http.Request) { r.URL.ForceQuery = true }, 400, "QUERY_INVALID"},
		{"conditional", "GET", func(r *http.Request) { r.Header["If-None-Match"] = []string{""} }, 400, "PRECONDITION_HEADER_UNSUPPORTED"},
		{"body", "GET", func(r *http.Request) {
			r.Body = io.NopCloser(strings.NewReader("private-password-123"))
			r.ContentLength = 20
		}, 400, "BODY_UNEXPECTED"},
		{"chunked", "GET", func(r *http.Request) { r.TransferEncoding = []string{"chunked"} }, 400, "BODY_UNEXPECTED"},
		{"missing key", "DELETE", func(r *http.Request) { r.Header.Del("Idempotency-Key") }, 400, "IDEMPOTENCY_KEY_INVALID"},
		{"multiple keys", "DELETE", func(r *http.Request) { r.Header.Add("Idempotency-Key", "other") }, 400, "IDEMPOTENCY_KEY_INVALID"},
		{"media", "DELETE", func(r *http.Request) { r.Header.Set("Content-Type", "text/plain") }, 415, "UNSUPPORTED_MEDIA_TYPE"},
		{"unknown", "DELETE", func(r *http.Request) {
			r.Body = io.NopCloser(strings.NewReader(`{"schema_version":"v1","device_id":"camera-1","force":true}`))
		}, 400, "INVALID_JSON"},
		{"trailing", "DELETE", func(r *http.Request) { r.Body = io.NopCloser(strings.NewReader(credentialRevokeBody + " {}")) }, 400, "INVALID_JSON"},
		{"semantics", "DELETE", func(r *http.Request) {
			r.Body = io.NopCloser(strings.NewReader(`{"schema_version":"v1","device_id":"bad/id"}`))
		}, 422, "CONTRACT_INVALID"},
		{"size", "DELETE", func(r *http.Request) {
			r.Body = io.NopCloser(strings.NewReader(`{"schema_version":"v1","device_id":"` + strings.Repeat("x", 65536) + `"}`))
		}, 413, "BODY_TOO_LARGE"},
	} {
		t.Run(test.name, func(t *testing.T) {
			body := ""
			if test.method == "DELETE" {
				body = credentialRevokeBody
			}
			r := credentialVersionRequest(test.method, credentialVersionPath, body)
			test.mutate(r)
			response := credentialStatus(t, api, r, test.status, test.code)
			credentialSafe(t, response.Body.String())
		})
	}
	for _, method := range []string{"GET", "DELETE"} {
		for _, version := range []string{"0", "01", "+1", "1.0", "latest", "9223372036854775808"} {
			r := credentialVersionRequest(method, strings.TrimSuffix(credentialVersionPath, "1")+version, "")
			credentialStatus(t, api, r, 422, "CONTRACT_INVALID")
		}
	}
	if calls != 0 {
		t.Fatal("invalid input reached manager")
	}
	credentialSafe(t, logs.String())
}

func TestCredentialVersionsHTTPPermission(t *testing.T) {
	for _, test := range []struct {
		name     string
		resolver CredentialPrincipalResolver
		status   int
		code     string
	}{
		{"denied", func(context.Context) (string, string, bool, error) { return "scope-1", "subject-1", false, nil }, 403, "FORBIDDEN"},
		{"unavailable", func(context.Context) (string, string, bool, error) {
			return "scope-1", "subject-1", true, errors.New("private-password-123")
		}, 503, "CREDENTIAL_AUTHORIZATION_UNAVAILABLE"},
	} {
		t.Run(test.name, func(t *testing.T) {
			var logs bytes.Buffer
			api := credentialVersionsAPI(t, credentialManagerStub{}, test.resolver, &logs)
			for _, method := range []string{"GET", "DELETE"} {
				r := credentialVersionRequest(method, credentialVersionPath, "malformed private-password-123")
				response := credentialStatus(t, api, r, test.status, test.code)
				credentialSafe(t, response.Body.String())
			}
			credentialSafe(t, logs.String())
		})
	}
}

func TestCredentialVersionsHTTPStoreErrors(t *testing.T) {
	for _, method := range []string{"GET", "DELETE"} {
		for _, code := range []string{"CREDENTIAL_UNAVAILABLE", "CREDENTIAL_AUTHORIZATION_UNAVAILABLE", "CREDENTIAL_ADMISSION_UNAVAILABLE", "CREDENTIAL_USAGE_UNAVAILABLE", "CREDENTIAL_IN_USE", "IDEMPOTENCY_CONFLICT", "SYNTHETIC_SQL_PRIVATE"} {
			t.Run(method+code, func(t *testing.T) {
				var logs bytes.Buffer
				failure := &storage.Error{Code: code}
				manager := credentialManagerStub{get: func(context.Context, storage.CredentialIdentity, string, int64, storage.CredentialAuthorizer) (storage.CredentialMetadata, error) {
					return storage.CredentialMetadata{}, failure
				}, revoke: func(context.Context, storage.CredentialIdentity, storage.CredentialReference, storage.CredentialAuthorizer, storage.CredentialRevokeGuard) (storage.CredentialMetadata, bool, error) {
					return storage.CredentialMetadata{}, false, failure
				}}
				api := credentialVersionsAPI(t, manager, credentialPrincipal, &logs)
				body := ""
				if method == "DELETE" {
					body = credentialRevokeBody
				}
				status := 409
				want := code
				if method == "GET" && code == "CREDENTIAL_UNAVAILABLE" {
					status = 404
				} else if code == "CREDENTIAL_AUTHORIZATION_UNAVAILABLE" || code == "CREDENTIAL_ADMISSION_UNAVAILABLE" || code == "CREDENTIAL_USAGE_UNAVAILABLE" {
					status = 503
				} else if code == "SYNTHETIC_SQL_PRIVATE" {
					status = 503
					want = "CREDENTIAL_STORE_UNAVAILABLE"
				}
				response := credentialStatus(t, api, credentialVersionRequest(method, credentialVersionPath, body), status, want)
				credentialSafe(t, response.Body.String()+logs.String())
			})
		}
	}
}

func TestCredentialVersionsHTTPConfiguration(t *testing.T) {
	var logs bytes.Buffer
	api, err := New(credentialToken, slog.New(slog.NewJSONHandler(&logs, nil)))
	if err != nil {
		t.Fatal(err)
	}
	if RegisterCredentialVersions(api, nil, credentialPrincipal, credentialAuthorization, credentialUnused) == nil || RegisterCredentialVersions(api, &storage.CredentialStore{}, nil, credentialAuthorization, credentialUnused) == nil || RegisterCredentialVersions(api, &storage.CredentialStore{}, credentialPrincipal, nil, credentialUnused) == nil || RegisterCredentialVersions(api, &storage.CredentialStore{}, credentialPrincipal, credentialAuthorization, nil) == nil {
		t.Fatal("incomplete configuration installed")
	}
	credentialStatus(t, api, credentialVersionRequest("GET", credentialVersionPath, ""), 404, "NOT_FOUND")
	if RegisterCredentialVersions(api, &storage.CredentialStore{}, credentialPrincipal, credentialAuthorization, credentialUnused) != nil {
		t.Fatal("register")
	}
	credentialStatus(t, api, credentialVersionRequest("GET", credentialVersionPath, ""), 503, "CREDENTIAL_ADMISSION_UNAVAILABLE")
	credentialStatus(t, api, credentialVersionRequest("DELETE", credentialVersionPath, credentialRevokeBody), 503, "CREDENTIAL_ADMISSION_UNAVAILABLE")
	credentialSafe(t, logs.String())
}

func TestCredentialVersionsHTTPReceiptValidation(t *testing.T) {
	for _, method := range []string{"GET", "DELETE"} {
		for _, kind := range []string{"id", "version", "device", "device-mismatch", "created", "revoked-before-created", "missing-revocation"} {
			if method == "GET" && (kind == "missing-revocation" || kind == "device-mismatch") {
				continue
			}
			t.Run(method+kind, func(t *testing.T) {
				var logs bytes.Buffer
				m := credentialMetadataFixture()
				at := m.CreatedAt.Add(time.Second)
				m.RevokedAt = &at
				switch kind {
				case "id":
					m.CredentialID = "other"
				case "version":
					m.Version = 2
				case "device":
					m.DeviceID = "bad/id"
				case "device-mismatch":
					m.DeviceID = "other-device"
				case "created":
					m.CreatedAt = time.Time{}
				case "revoked-before-created":
					at = m.CreatedAt.Add(-time.Second)
				case "missing-revocation":
					m.RevokedAt = nil
				}
				manager := credentialManagerStub{get: func(context.Context, storage.CredentialIdentity, string, int64, storage.CredentialAuthorizer) (storage.CredentialMetadata, error) {
					return m, nil
				}, revoke: func(context.Context, storage.CredentialIdentity, storage.CredentialReference, storage.CredentialAuthorizer, storage.CredentialRevokeGuard) (storage.CredentialMetadata, bool, error) {
					return m, false, nil
				}}
				api := credentialVersionsAPI(t, manager, credentialPrincipal, &logs)
				body := ""
				if method == "DELETE" {
					body = credentialRevokeBody
				}
				credentialStatus(t, api, credentialVersionRequest(method, credentialVersionPath, body), 503, "CREDENTIAL_STORE_UNAVAILABLE")
			})
		}
	}
}

func TestCredentialVersionsHTTPActualTLS(t *testing.T) {
	var logs bytes.Buffer
	m := credentialMetadataFixture()
	manager := credentialManagerStub{
		get: func(context.Context, storage.CredentialIdentity, string, int64, storage.CredentialAuthorizer) (storage.CredentialMetadata, error) {
			return m, nil
		},
		revoke: func(context.Context, storage.CredentialIdentity, storage.CredentialReference, storage.CredentialAuthorizer, storage.CredentialRevokeGuard) (storage.CredentialMetadata, bool, error) {
			at := m.CreatedAt.Add(time.Second)
			m.RevokedAt = &at
			return m, false, nil
		},
	}
	api := credentialVersionsAPI(t, manager, credentialPrincipal, &logs)
	server := httptest.NewTLSServer(api)
	defer server.Close()
	for _, method := range []string{"GET", "DELETE"} {
		body := ""
		if method == "DELETE" {
			body = credentialRevokeBody
		}
		r, err := http.NewRequest(method, server.URL+credentialVersionPath, strings.NewReader(body))
		if err != nil {
			t.Fatal(err)
		}
		r.Header = credentialVersionRequest(method, credentialVersionPath, body).Header
		response, err := server.Client().Do(r)
		if err != nil {
			t.Fatal(err)
		}
		output, err := io.ReadAll(response.Body)
		response.Body.Close()
		if err != nil || response.StatusCode != 200 {
			t.Fatalf("actual TLS metadata/revoke failed: %d %s", response.StatusCode, output)
		}
		credentialSafe(t, string(output))
	}
	credentialSafe(t, logs.String())
}
