package app

import (
	"context"
	"errors"
	"net/http"
	"net/url"
	"strconv"
	"time"

	"vms.local/platform/camera/internal/contracts"
	"vms.local/platform/camera/internal/storage"
	"vms.local/platform/internal/httpapi"
)

// The development token authenticates one stable shared principal. Token rotation
// does not change idempotency scope; caller-supplied identity headers are ignored.
const developmentPrincipal = "development:shared-token"

func registerDevices(a *httpapi.API, s *storage.Store, guard storage.DeviceDeleteGuard) {
	a.Handle("/api/v1/devices", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet && r.Method != http.MethodPost {
			w.Header().Set("Allow", "GET, POST")
			httpapi.Fail(w, r, 405, "METHOD_NOT_ALLOWED", "Method is not supported", nil)
			return
		}
		query, err := url.ParseQuery(r.URL.RawQuery)
		if err != nil {
			badQuery(w, r)
			return
		}
		if r.Method == http.MethodPost {
			if len(query) != 0 {
				badQuery(w, r)
				return
			}
			keys := r.Header.Values("Idempotency-Key")
			if len(keys) != 1 || !contracts.ValidIdempotencyKey(keys[0]) {
				httpapi.Fail(w, r, 400, "IDEMPOTENCY_KEY_INVALID", "One Idempotency-Key of 1 to 128 visible ASCII characters is required", nil)
				return
			}
			var input contracts.DeviceCreate
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
			device, replay, err := s.CreateDevice(ctx, developmentPrincipal, keys[0], input)
			if err != nil {
				deviceError(w, r, err)
				return
			}
			w.Header().Set("Location", "/api/v1/devices/"+device.DeviceID)
			w.Header().Set("Idempotency-Replayed", strconv.FormatBool(replay))
			httpapi.WriteJSON(w, 201, map[string]any{"device": device, "request_id": w.Header().Get("X-Request-ID")})
			return
		}
		limit := 50
		for key, values := range query {
			if (key != "limit" && key != "cursor") || len(values) != 1 || values[0] == "" {
				badQuery(w, r)
				return
			}
		}
		if value := query.Get("limit"); value != "" {
			limit, err = strconv.Atoi(value)
			if err != nil || limit < 1 || limit > 200 {
				badQuery(w, r)
				return
			}
		}
		after, err := contracts.DecodeDeviceCursor(query.Get("cursor"))
		if err != nil {
			badQuery(w, r)
			return
		}
		if !hasStore(w, r, s) {
			return
		}
		ctx, cancel := context.WithTimeout(r.Context(), 8*time.Second)
		defer cancel()
		items, more, err := s.ListDevices(ctx, after, limit)
		if err != nil {
			deviceError(w, r, err)
			return
		}
		var next *string
		if more {
			value := contracts.EncodeDeviceCursor(items[len(items)-1].DeviceID)
			next = &value
		}
		httpapi.WriteJSON(w, 200, map[string]any{"items": items, "next_cursor": next, "request_id": w.Header().Get("X-Request-ID")})
	})
	a.Handle("/api/v1/devices/{device_id}", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet && r.Method != http.MethodPatch && r.Method != http.MethodDelete {
			w.Header().Set("Allow", "GET, PATCH, DELETE")
			httpapi.Fail(w, r, 405, "METHOD_NOT_ALLOWED", "Method is not supported", nil)
			return
		}
		if r.URL.RawQuery != "" || (r.Method != http.MethodGet && r.URL.ForceQuery) {
			badQuery(w, r)
			return
		}
		id := r.PathValue("device_id")
		if !contracts.ValidDeviceID(id) {
			httpapi.Fail(w, r, 422, "CONTRACT_INVALID", "Invalid device ID", nil)
			return
		}
		if r.Method == http.MethodPatch {
			updateDevice(w, r, s, id)
			return
		}
		if r.Method == http.MethodDelete {
			deleteDevice(w, r, s, id, guard)
			return
		}
		if !hasStore(w, r, s) {
			return
		}
		ctx, cancel := context.WithTimeout(r.Context(), 8*time.Second)
		defer cancel()
		device, err := s.GetDevice(ctx, id)
		if err != nil {
			deviceError(w, r, err)
			return
		}
		httpapi.WriteJSON(w, 200, map[string]any{"device": device, "request_id": w.Header().Get("X-Request-ID")})
	})
}
func badQuery(w http.ResponseWriter, r *http.Request) {
	httpapi.Fail(w, r, 400, "QUERY_INVALID", "Invalid or repeated query parameter", nil)
}
func hasStore(w http.ResponseWriter, r *http.Request, s *storage.Store) bool {
	if s != nil {
		return true
	}
	httpapi.Fail(w, r, 503, "REGISTRY_DISABLED", "Camera registry database is not configured", nil)
	return false
}
func deviceError(w http.ResponseWriter, r *http.Request, err error) {
	var e *storage.Error
	if errors.As(err, &e) {
		switch e.Code {
		case "DEVICE_NOT_FOUND":
			httpapi.Fail(w, r, 404, e.Code, "Device was not found", nil)
			return
		case "DEVICE_EXISTS", "IDEMPOTENCY_CONFLICT":
			httpapi.Fail(w, r, 409, e.Code, "Registration conflicts with an existing request or device", nil)
			return
		case "DEVICE_VERSION_CONFLICT":
			httpapi.Fail(w, r, 409, e.Code, "Device version changed; read the current device before submitting a new request", nil)
			return
		case "DEVICE_VERSION_EXHAUSTED":
			httpapi.Fail(w, r, 409, e.Code, "Device version cannot be increased", nil)
			return
		case "DEVICE_HAS_ACTIVE_SOURCES":
			httpapi.Fail(w, r, 409, e.Code, "Delete each active source registration before deleting the device", nil)
			return
		case "DEVICE_IN_USE":
			httpapi.Fail(w, r, 409, e.Code, "Device has managed usage that must end before deletion", nil)
			return
		case "DEVICE_USAGE_UNAVAILABLE":
			httpapi.Fail(w, r, 503, e.Code, "Device usage cannot be confirmed; retry with the same idempotency key", nil)
			return
		}
	}
	httpapi.Fail(w, r, 503, "DATABASE_UNAVAILABLE", "Device registry is temporarily unavailable; retry with the same idempotency key", nil)
}
