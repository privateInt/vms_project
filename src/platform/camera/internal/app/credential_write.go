package app

import (
	"context"
	"errors"
	"math"
	"net/http"
	"strconv"
	"time"

	"vms.local/platform/camera/internal/contracts"
	"vms.local/platform/camera/internal/storage"
	"vms.local/platform/internal/httpapi"
)

// CredentialPrincipalResolver consumes trusted middleware context, never body
// fields or caller identity headers. allowed represents secret-management rights;
// the store separately verifies device and credential rights in both transactions.
type CredentialPrincipalResolver func(context.Context) (scopeID, principalID string, allowed bool, err error)

type credentialVersionWriter interface {
	WriteVersion(context.Context, storage.CredentialIdentity, storage.CredentialWrite, storage.CredentialAuthorizer) (storage.CredentialMetadata, bool, error)
}

// RegisterCredentialWrites is an explicit integration entrypoint. The current
// camera executable does not call it. A concrete store retains its whole-operation
// admission guard; inspection-only stores reject all business calls before IO.
func RegisterCredentialWrites(a *httpapi.API, store *storage.CredentialStore, principal CredentialPrincipalResolver, authorize storage.CredentialAuthorizer) error {
	if a == nil || store == nil || principal == nil || authorize == nil {
		return errors.New("credential HTTP configuration unavailable")
	}
	registerCredentialWrites(a, store, principal, authorize)
	return nil
}

func registerCredentialWrites(a *httpapi.API, store credentialVersionWriter, principal CredentialPrincipalResolver, authorize storage.CredentialAuthorizer) {
	a.Handle("/api/v1/credentials/{credential_id}/versions", func(w http.ResponseWriter, r *http.Request) {
		identity, ok := credentialHTTPIdentity(w, r, principal)
		if !ok {
			return
		}
		if !httpapi.RequireMethod(w, r, http.MethodPost) {
			return
		}
		if r.URL.RawQuery != "" || r.URL.ForceQuery {
			badQuery(w, r)
			return
		}
		id := r.PathValue("credential_id")
		if !contracts.ValidDeviceID(id) {
			httpapi.Fail(w, r, 422, "CONTRACT_INVALID", "Invalid credential ID", nil)
			return
		}
		for _, name := range []string{"If-Match", "If-None-Match", "If-Unmodified-Since", "If-Modified-Since", "If-Range"} {
			if _, present := r.Header[http.CanonicalHeaderKey(name)]; present {
				httpapi.Fail(w, r, 400, "PRECONDITION_HEADER_UNSUPPORTED", "Use expected_version in the JSON body", nil)
				return
			}
		}
		keys := r.Header.Values("Idempotency-Key")
		if len(keys) != 1 || !contracts.ValidIdempotencyKey(keys[0]) {
			httpapi.Fail(w, r, 400, "IDEMPOTENCY_KEY_INVALID", "One valid Idempotency-Key is required", nil)
			return
		}
		var input contracts.CredentialVersionWrite
		defer input.Clear()
		if !httpapi.DecodeJSON(w, r, &input) {
			return
		}
		if violations := input.Validate(); len(violations) > 0 {
			httpapi.Fail(w, r, 422, "CONTRACT_INVALID", "Contract validation failed", violations)
			return
		}
		secret, err := input.Secret()
		if err != nil {
			httpapi.Fail(w, r, 422, "CONTRACT_INVALID", "Contract validation failed", nil)
			return
		}
		ctx, cancel := context.WithTimeout(r.Context(), 8*time.Second)
		defer cancel()
		identity.IdempotencyKey = keys[0]
		metadata, replay, err := store.WriteVersion(ctx, identity, storage.CredentialWrite{
			CredentialID: id, DeviceID: input.DeviceID, ExpectedVersion: input.ExpectedVersion,
			Target: storage.CredentialTarget{Protocol: input.Protocol, Host: input.Host, Port: int(input.Port)}, Secret: secret,
		}, authorize)
		if err != nil {
			credentialWriteError(w, r, err)
			return
		}
		// Permit only a consistent metadata receipt, including success replay. Never
		// serialize the private input, writer implementation or returned DB error.
		if metadata.CredentialID != id || metadata.DeviceID != input.DeviceID || input.ExpectedVersion == math.MaxInt64 || metadata.Version != input.ExpectedVersion+1 || metadata.CreatedAt.IsZero() || metadata.RevokedAt != nil {
			httpapi.Fail(w, r, 503, "CREDENTIAL_STORE_UNAVAILABLE", "Credential store is unavailable", nil)
			return
		}
		w.Header().Set("Idempotency-Replayed", strconv.FormatBool(replay))
		httpapi.WriteJSON(w, http.StatusCreated, map[string]any{"credential": metadata, "request_id": w.Header().Get("X-Request-ID")})
	})
}

func credentialWriteError(w http.ResponseWriter, r *http.Request, err error) {
	var failure *storage.Error
	if errors.As(err, &failure) {
		switch failure.Code {
		case "CONTRACT_INVALID":
			httpapi.Fail(w, r, 422, failure.Code, "Contract validation failed", nil)
			return
		case "CREDENTIAL_EXISTS", "CREDENTIAL_UNAVAILABLE", "CREDENTIAL_VERSION_CONFLICT", "CREDENTIAL_VERSION_EXHAUSTED", "DEVICE_UNAVAILABLE", "IDEMPOTENCY_CONFLICT", "CREDENTIAL_IN_USE":
			httpapi.Fail(w, r, 409, failure.Code, "Credential request conflicts with current state", nil)
			return
		case "CREDENTIAL_AUTHORIZATION_UNAVAILABLE", "CREDENTIAL_ADMISSION_UNAVAILABLE", "CREDENTIAL_USAGE_UNAVAILABLE":
			httpapi.Fail(w, r, 503, failure.Code, "Credential access is unavailable", nil)
			return
		}
	}
	httpapi.Fail(w, r, 503, "CREDENTIAL_STORE_UNAVAILABLE", "Credential store is unavailable; retry with the same idempotency key", nil)
}
