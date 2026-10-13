package app

import (
	"context"

	"github.com/jackc/pgx/v5"
	"vms.local/platform/camera/internal/storage"
)

func cameraCapabilities(registry string) map[string]string {
	return map[string]string{
		"device_registry": registry, "device_update": registry, "device_delete": registry,
		"source_contract_validation": "implemented", "source_registry": registry,
		"source_list": registry, "source_update": registry, "source_delete": registry,
		"onvif_ptz": "planned", "rtsp_ingest": "planned",
		"webrtc_signaling_ingest": "planned", "recording": "planned",
		"source_sessions": "planned", "source_consumers": "planned",
	}
}

// Only the explicitly reviewed registry-only release can declare unused here.
// This is NOT a detector of external media activity. The constructor and main
// register no usage creators. Keep that premise in sync with this allowlist;
// future sessions/consumers/adapters must replace this policy with admission
// checks sharing the locked source transaction. Client input cannot select it.
// Missing, newly added or enabled capabilities deny rather than assume unused.
// Both deletion guards use this exact reviewed profile. A new capability must
// be reviewed for device and source usage together before extending it.
func registryOnlyDeletionPermitted(mode string, capabilities map[string]string) bool {
	expected := map[string]string{
		"device_registry": "implemented", "device_update": "implemented", "device_delete": "implemented",
		"source_contract_validation": "implemented", "source_registry": "implemented",
		"source_list": "implemented", "source_update": "implemented", "source_delete": "implemented",
		"onvif_ptz": "planned", "rtsp_ingest": "planned",
		"webrtc_signaling_ingest": "planned", "recording": "planned",
		"source_sessions": "planned", "source_consumers": "planned",
	}
	permitted := mode == "registry-only-v1" && len(capabilities) == len(expected)
	for key, value := range expected {
		if capabilities[key] != value {
			permitted = false
		}
	}
	return permitted
}

func registryOnlySourceDeleteGuard(mode string, capabilities map[string]string) storage.SourceDeleteGuard {
	permitted := registryOnlyDeletionPermitted(mode, capabilities)
	// Capture the reviewed decision, not a mutable map shared with the manifest.
	return func(ctx context.Context, _ pgx.Tx, _ string) (storage.SourceUsage, error) {
		if err := ctx.Err(); err != nil {
			return storage.SourceUsageUnknown, err
		}
		if !permitted {
			return storage.SourceUsageUnknown, nil
		}
		return storage.SourceUsageUnused, nil
	}
}
