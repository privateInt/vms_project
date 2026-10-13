package app

import (
	"context"
	"encoding/json"
	"net/http/httptest"
	"testing"

	"vms.local/platform/camera/internal/storage"
)

func TestSourceDeleteRegistryOnlyPolicy(t *testing.T) {
	accepted := registryOnlySourceDeleteGuard("registry-only-v1", cameraCapabilities("implemented"))
	if usage, err := accepted(context.Background(), nil, "s1"); usage != storage.SourceUsageUnused || err != nil {
		t.Fatal("reviewed profile rejected")
	}
	for _, mode := range []string{"", "unknown", "runtime", "registry-only-v2"} {
		guard := registryOnlySourceDeleteGuard(mode, cameraCapabilities("implemented"))
		if usage, _ := guard(context.Background(), nil, "s1"); usage != storage.SourceUsageUnknown {
			t.Fatal("unreviewed mode allowed", mode)
		}
	}
	for key := range cameraCapabilities("implemented") {
		for _, change := range []string{"missing", "changed"} {
			caps := cameraCapabilities("implemented")
			if change == "missing" {
				delete(caps, key)
			} else {
				caps[key] = "unreviewed"
				if key == "source_sessions" || key == "source_consumers" || capsFromRuntime(key) {
					caps[key] = "implemented"
				}
			}
			guard := registryOnlySourceDeleteGuard("registry-only-v1", caps)
			if usage, _ := guard(context.Background(), nil, "s1"); usage != storage.SourceUsageUnknown {
				t.Fatal("unreviewed capability allowed", key, change)
			}
		}
	}
	for _, caps := range []map[string]string{nil, {}, cameraCapabilities("disabled"), cameraCapabilities("implemented")} {
		if caps != nil {
			caps["new_adapter"] = "implemented"
		}
		guard := registryOnlySourceDeleteGuard("registry-only-v1", caps)
		if usage, _ := guard(context.Background(), nil, "s1"); usage != storage.SourceUsageUnknown {
			t.Fatal("unknown profile allowed")
		}
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if usage, err := accepted(ctx, nil, "s1"); usage != storage.SourceUsageUnknown || err == nil {
		t.Fatal("cancellation allowed")
	}
}

func capsFromRuntime(key string) bool {
	return key == "onvif_ptz" || key == "rtsp_ingest" || key == "webrtc_signaling_ingest" || key == "recording"
}

func TestSourceDeleteUsageErrorResponses(t *testing.T) {
	for code, status := range map[string]int{"SOURCE_IN_USE": 409, "SOURCE_USAGE_UNAVAILABLE": 503} {
		w := httptest.NewRecorder()
		sourceError(w, httptest.NewRequest("DELETE", "/api/v1/sources/s1", nil), &storage.Error{Code: code})
		var value struct{ Error struct{ Code string } }
		if json.Unmarshal(w.Body.Bytes(), &value) != nil || w.Code != status || value.Error.Code != code {
			t.Fatal("usage rejection mapping", code, w.Code)
		}
	}
}
