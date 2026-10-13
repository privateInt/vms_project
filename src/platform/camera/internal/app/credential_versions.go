package app

import (
	"context"
	"crypto/tls"
	"errors"
	"net/http"
	"strconv"
	"time"

	"vms.local/platform/camera/internal/contracts"
	"vms.local/platform/camera/internal/storage"
	"vms.local/platform/internal/httpapi"
)

type credentialVersionManager interface {
	GetVersionMetadata(context.Context, storage.CredentialIdentity, string, int64, storage.CredentialAuthorizer) (storage.CredentialMetadata, error)
	RevokeVersion(context.Context, storage.CredentialIdentity, storage.CredentialReference, storage.CredentialAuthorizer, storage.CredentialRevokeGuard) (storage.CredentialMetadata, bool, error)
}

// Explicit integration only: main does not register these routes. There is no
// default unused guard. RevokeVersion holds actual device/credential locks while
// the supplied trusted guard proves reference, reservation and usage release.
func RegisterCredentialVersions(a *httpapi.API, store *storage.CredentialStore, principal CredentialPrincipalResolver, authorize storage.CredentialAuthorizer, guard storage.CredentialRevokeGuard) error {
	if a == nil || store == nil || principal == nil || authorize == nil || guard == nil {
		return errors.New("credential HTTP configuration unavailable")
	}
	registerCredentialVersions(a, store, principal, authorize, guard)
	return nil
}

// Same trusted identity and direct TLS checks for writes, inspection and revoke.
func credentialHTTPIdentity(w http.ResponseWriter, r *http.Request, principal CredentialPrincipalResolver) (storage.CredentialIdentity, bool) {
	if r.TLS == nil || !r.TLS.HandshakeComplete || r.TLS.Version < tls.VersionTLS12 {
		httpapi.Fail(w, r, 403, "CREDENTIAL_TRANSPORT_REQUIRED", "A protected TLS connection is required", nil)
		return storage.CredentialIdentity{}, false
	}
	scope, subject, allowed, err := principal(r.Context())
	if err != nil || !contracts.ValidDeviceID(scope) || !contracts.ValidDeviceID(subject) {
		httpapi.Fail(w, r, 503, "CREDENTIAL_AUTHORIZATION_UNAVAILABLE", "Credential authorization is unavailable", nil)
		return storage.CredentialIdentity{}, false
	}
	if !allowed {
		httpapi.Fail(w, r, 403, "FORBIDDEN", "Credential management permission is required", nil)
		return storage.CredentialIdentity{}, false
	}
	return storage.CredentialIdentity{ScopeID: scope, PrincipalID: subject}, true
}

func registerCredentialVersions(a *httpapi.API, store credentialVersionManager, principal CredentialPrincipalResolver, authorize storage.CredentialAuthorizer, guard storage.CredentialRevokeGuard) {
	a.Handle("/api/v1/credentials/{credential_id}/versions/{credential_version}", func(w http.ResponseWriter, r *http.Request) {
		identity, ok := credentialHTTPIdentity(w, r, principal)
		if !ok {
			return
		}
		if r.Method != http.MethodGet && r.Method != http.MethodDelete {
			w.Header().Set("Allow", "GET, DELETE")
			httpapi.Fail(w, r, 405, "METHOD_NOT_ALLOWED", "Method is not supported", nil)
			return
		}
		if r.URL.RawQuery != "" || r.URL.ForceQuery {
			badQuery(w, r)
			return
		}
		id := r.PathValue("credential_id")
		version, validVersion := contracts.ParseCredentialVersion(r.PathValue("credential_version"))
		if !contracts.ValidDeviceID(id) || !validVersion {
			httpapi.Fail(w, r, 422, "CONTRACT_INVALID", "Invalid credential ID or version", nil)
			return
		}
		for _, name := range []string{"If-Match", "If-None-Match", "If-Unmodified-Since", "If-Modified-Since", "If-Range"} {
			if _, present := r.Header[http.CanonicalHeaderKey(name)]; present {
				httpapi.Fail(w, r, 400, "PRECONDITION_HEADER_UNSUPPORTED", "Conditional headers are not supported", nil)
				return
			}
		}
		if r.Method == http.MethodGet {
			if r.ContentLength != 0 || len(r.TransferEncoding) != 0 || (r.Body != nil && r.Body != http.NoBody) {
				httpapi.Fail(w, r, 400, "BODY_UNEXPECTED", "This metadata request has no body", nil)
				return
			}
			ctx, cancel := context.WithTimeout(r.Context(), 8*time.Second)
			defer cancel()
			metadata, err := store.GetVersionMetadata(ctx, identity, id, version, authorize)
			if err != nil {
				credentialVersionError(w, r, err)
				return
			}
			if !credentialVersionReceipt(metadata, id, version) {
				credentialVersionError(w, r, errors.New("invalid receipt"))
				return
			}
			httpapi.WriteJSON(w, 200, map[string]any{"credential": metadata, "request_id": w.Header().Get("X-Request-ID")})
			return
		}
		keys := r.Header.Values("Idempotency-Key")
		if len(keys) != 1 || !contracts.ValidIdempotencyKey(keys[0]) {
			httpapi.Fail(w, r, 400, "IDEMPOTENCY_KEY_INVALID", "One valid Idempotency-Key is required", nil)
			return
		}
		var input contracts.CredentialRevoke
		if !httpapi.DecodeJSON(w, r, &input) {
			return
		}
		if violations := input.Validate(); len(violations) > 0 {
			httpapi.Fail(w, r, 422, "CONTRACT_INVALID", "Contract validation failed", violations)
			return
		}
		identity.IdempotencyKey = keys[0]
		ctx, cancel := context.WithTimeout(r.Context(), 8*time.Second)
		defer cancel()
		metadata, replay, err := store.RevokeVersion(ctx, identity, storage.CredentialReference{CredentialID: id, DeviceID: input.DeviceID, Version: version}, authorize, guard)
		if err != nil {
			credentialVersionError(w, r, err)
			return
		}
		if !credentialVersionReceipt(metadata, id, version) || metadata.DeviceID != input.DeviceID || metadata.RevokedAt == nil {
			credentialVersionError(w, r, errors.New("invalid receipt"))
			return
		}
		w.Header().Set("Idempotency-Replayed", strconv.FormatBool(replay))
		httpapi.WriteJSON(w, 200, map[string]any{"credential": metadata, "request_id": w.Header().Get("X-Request-ID")})
	})
}

func credentialVersionReceipt(metadata storage.CredentialMetadata, id string, version int64) bool {
	return metadata.CredentialID == id && metadata.Version == version && contracts.ValidDeviceID(metadata.DeviceID) && !metadata.CreatedAt.IsZero() && (metadata.RevokedAt == nil || !metadata.RevokedAt.Before(metadata.CreatedAt))
}

func credentialVersionError(w http.ResponseWriter, r *http.Request, err error) {
	var failure *storage.Error
	if r.Method == http.MethodGet && errors.As(err, &failure) && failure.Code == "CREDENTIAL_UNAVAILABLE" {
		httpapi.Fail(w, r, 404, failure.Code, "Credential metadata is unavailable", nil)
		return
	}
	credentialWriteError(w, r, err)
}
