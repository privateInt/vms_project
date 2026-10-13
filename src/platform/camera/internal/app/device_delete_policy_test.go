package app

import (
	"context"
	"encoding/json"
	"net/http/httptest"
	"testing"

	"vms.local/platform/camera/internal/storage"
)

func TestDeviceDeleteRegistryOnlyPolicy(t *testing.T) {
	accepted := registryOnlyDeviceDeleteGuard("registry-only-v1", cameraCapabilities("implemented"))
	if usage, err := accepted(context.Background(), nil, "d1"); usage != storage.DeviceUsageUnused || err != nil {
		t.Fatal("reviewed profile rejected")
	}
	for _, mode := range []string{"", "unknown", "runtime", "registry-only-v2"} {
		guard := registryOnlyDeviceDeleteGuard(mode, cameraCapabilities("implemented"))
		if usage, _ := guard(context.Background(), nil, "d1"); usage != storage.DeviceUsageUnknown {
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
			guard := registryOnlyDeviceDeleteGuard("registry-only-v1", caps)
			if usage, _ := guard(context.Background(), nil, "d1"); usage != storage.DeviceUsageUnknown {
				t.Fatal("unreviewed capability allowed", key, change)
			}
		}
	}
	for _, caps := range []map[string]string{nil, {}, cameraCapabilities("disabled"), cameraCapabilities("implemented")} {
		if caps != nil {
			caps["new_adapter"] = "implemented"
		}
		guard := registryOnlyDeviceDeleteGuard("registry-only-v1", caps)
		if usage, _ := guard(context.Background(), nil, "d1"); usage != storage.DeviceUsageUnknown {
			t.Fatal("unknown profile allowed")
		}
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if usage, err := accepted(ctx, nil, "d1"); usage != storage.DeviceUsageUnknown || err == nil {
		t.Fatal("cancellation allowed")
	}
}

func TestDeviceDeleteUsageErrorResponses(t *testing.T) {
	for code, status := range map[string]int{"DEVICE_HAS_ACTIVE_SOURCES": 409, "DEVICE_IN_USE": 409, "DEVICE_USAGE_UNAVAILABLE": 503} {
		w := httptest.NewRecorder()
		deviceError(w, httptest.NewRequest("DELETE", "/api/v1/devices/d1", nil), &storage.Error{Code: code})
		var value struct{ Error struct{ Code string } }
		if json.Unmarshal(w.Body.Bytes(), &value) != nil || w.Code != status || value.Error.Code != code {
			t.Fatal("usage rejection mapping", code, w.Code)
		}
	}
}
