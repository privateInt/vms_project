package app

import (
	"context"
	"net/http"
	"net/url"
	"strconv"
	"time"

	"vms.local/platform/camera/internal/contracts"
	"vms.local/platform/camera/internal/storage"
	"vms.local/platform/internal/httpapi"
)

func listSources(w http.ResponseWriter, r *http.Request, s *storage.Store) {
	query, err := url.ParseQuery(r.URL.RawQuery)
	if err != nil {
		badQuery(w, r)
		return
	}
	for key, values := range query {
		if (key != "limit" && key != "cursor" && key != "device_id") || len(values) != 1 || values[0] == "" {
			badQuery(w, r)
			return
		}
	}
	limit := 50
	if value := query.Get("limit"); value != "" {
		limit, err = strconv.Atoi(value)
		if err != nil || limit < 1 || limit > 200 {
			badQuery(w, r)
			return
		}
	}
	deviceID := query.Get("device_id")
	after, err := contracts.DecodeSourceCursor(query.Get("cursor"), deviceID)
	if err != nil {
		badQuery(w, r)
		return
	}
	if !hasStore(w, r, s) {
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 8*time.Second)
	defer cancel()
	items, more, err := s.ListSources(ctx, after, deviceID, limit)
	if err != nil {
		sourceError(w, r, err)
		return
	}
	var next *string
	if more {
		value := contracts.EncodeSourceCursor(items[len(items)-1].SourceID, deviceID)
		next = &value
	}
	httpapi.WriteJSON(w, 200, map[string]any{"items": items, "next_cursor": next, "request_id": w.Header().Get("X-Request-ID")})
}
