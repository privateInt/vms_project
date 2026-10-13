package app

import (
	"context"
	"errors"
	"net/http"
	"strconv"
	"time"

	"vms.local/platform/camera/internal/contracts"
	"vms.local/platform/camera/internal/storage"
	"vms.local/platform/internal/httpapi"
)

func sourceResponse(w http.ResponseWriter, status int, source contracts.VideoSource) {
	httpapi.WriteJSON(w, status, map[string]any{"source": source, "registration_state": "REGISTERED", "runtime_verified": false, "request_id": w.Header().Get("X-Request-ID")})
}

func registerSources(a *httpapi.API, s *storage.Store, guard storage.SourceDeleteGuard) {
	a.Handle("/api/v1/sources", func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodGet {
			listSources(w, r, s)
			return
		}
		if r.Method != http.MethodPost {
			w.Header().Set("Allow", "GET, POST")
			httpapi.Fail(w, r, 405, "METHOD_NOT_ALLOWED", "Method is not supported", nil)
			return
		}
		if r.URL.RawQuery != "" {
			badQuery(w, r)
			return
		}
		keys := r.Header.Values("Idempotency-Key")
		if len(keys) != 1 || !contracts.ValidIdempotencyKey(keys[0]) {
			httpapi.Fail(w, r, 400, "IDEMPOTENCY_KEY_INVALID", "One Idempotency-Key of 1 to 128 visible ASCII characters is required", nil)
			return
		}
		var input contracts.SourceCreate
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
		source, replay, err := s.CreateSource(ctx, developmentPrincipal, keys[0], input)
		if err != nil {
			sourceError(w, r, err)
			return
		}
		w.Header().Set("Location", "/api/v1/sources/"+source.SourceID)
		w.Header().Set("Idempotency-Replayed", strconv.FormatBool(replay))
		sourceResponse(w, 201, source)
	})
	a.Handle("/api/v1/sources/{source_id}", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet && r.Method != http.MethodPatch && r.Method != http.MethodDelete {
			w.Header().Set("Allow", "GET, PATCH, DELETE")
			httpapi.Fail(w, r, 405, "METHOD_NOT_ALLOWED", "Method is not supported", nil)
			return
		}
		if r.URL.RawQuery != "" || ((r.Method == http.MethodPatch || r.Method == http.MethodDelete) && r.URL.ForceQuery) {
			badQuery(w, r)
			return
		}
		id := r.PathValue("source_id")
		if !contracts.ValidDeviceID(id) {
			httpapi.Fail(w, r, 422, "CONTRACT_INVALID", "Invalid source ID", nil)
			return
		}
		if r.Method == http.MethodDelete {
			deleteSource(w, r, s, id, guard)
			return
		}
		if r.Method == http.MethodPatch {
			updateSource(w, r, s, id)
			return
		}
		if !hasStore(w, r, s) {
			return
		}
		ctx, cancel := context.WithTimeout(r.Context(), 8*time.Second)
		defer cancel()
		source, err := s.GetSource(ctx, id)
		if err != nil {
			sourceError(w, r, err)
			return
		}
		sourceResponse(w, 200, source)
	})
}

func sourceError(w http.ResponseWriter, r *http.Request, err error) {
	var e *storage.Error
	if errors.As(err, &e) {
		switch e.Code {
		case "SOURCE_NOT_FOUND":
			httpapi.Fail(w, r, 404, e.Code, "Source was not found", nil)
			return
		case "SOURCE_IN_USE":
			httpapi.Fail(w, r, 409, e.Code, "Source has active usage; deletion is not allowed", nil)
			return
		case "SOURCE_USAGE_UNAVAILABLE":
			httpapi.Fail(w, r, 503, e.Code, "Source usage could not be verified; deletion is not allowed", nil)
			return
		case "DEVICE_UNAVAILABLE":
			httpapi.Fail(w, r, 409, e.Code, "Parent device is missing or deleted", nil)
			return
		case "SOURCE_VERSION_CONFLICT":
			httpapi.Fail(w, r, 409, e.Code, "Source version changed; read the current source before submitting a new request", nil)
			return
		case "SOURCE_VERSION_EXHAUSTED":
			httpapi.Fail(w, r, 409, e.Code, "Source version cannot be increased", nil)
			return
		case "SOURCE_EXISTS", "SOURCE_CHANNEL_EXISTS", "IDEMPOTENCY_CONFLICT":
			httpapi.Fail(w, r, 409, e.Code, "Registration conflicts with an existing source, channel or request", nil)
			return
		}
	}
	httpapi.Fail(w, r, 503, "DATABASE_UNAVAILABLE", "Source registry is temporarily unavailable; retry with the same idempotency key", nil)
}
