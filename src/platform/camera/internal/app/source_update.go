package app

import (
	"context"
	"net/http"
	"strconv"
	"time"

	"vms.local/platform/camera/internal/contracts"
	"vms.local/platform/camera/internal/storage"
	"vms.local/platform/internal/httpapi"
)

// Authentication, method, query and path checks run in the enclosing route.
func updateSource(w http.ResponseWriter, r *http.Request, s *storage.Store, id string) {
	for _, name := range []string{"If-Match", "If-None-Match", "If-Unmodified-Since"} {
		if _, present := r.Header[http.CanonicalHeaderKey(name)]; present {
			httpapi.Fail(w, r, 400, "PRECONDITION_HEADER_UNSUPPORTED", "Use expected_version in the JSON body for the version condition", nil)
			return
		}
	}
	keys := r.Header.Values("Idempotency-Key")
	if len(keys) != 1 || !contracts.ValidIdempotencyKey(keys[0]) {
		httpapi.Fail(w, r, 400, "IDEMPOTENCY_KEY_INVALID", "One Idempotency-Key of 1 to 128 visible ASCII characters is required", nil)
		return
	}
	var input contracts.SourceUpdate
	if !httpapi.DecodeJSON(w, r, &input) {
		return
	}
	if violations := input.Validate(); len(violations) > 0 {
		httpapi.Fail(w, r, 422, "CONTRACT_INVALID", "Contract validation failed", violations)
		return
	}
	if !hasStore(w, r, s) {
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 8*time.Second)
	defer cancel()
	source, replay, err := s.UpdateSource(ctx, developmentPrincipal, keys[0], id, input)
	if err != nil {
		sourceError(w, r, err)
		return
	}
	w.Header().Set("Idempotency-Replayed", strconv.FormatBool(replay))
	sourceResponse(w, http.StatusOK, source)
}
