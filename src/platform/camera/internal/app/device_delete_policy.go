package app

import (
	"context"

	"github.com/jackc/pgx/v5"
	"vms.local/platform/camera/internal/storage"
)

// This server-selected profile has no managed device/session/adapter creators.
// It is not an external device activity detector. Future usage admission must
// share DeleteDevice's device advisory and row locks before starting usage.
func registryOnlyDeviceDeleteGuard(mode string, capabilities map[string]string) storage.DeviceDeleteGuard {
	permitted := registryOnlyDeletionPermitted(mode, capabilities)
	return func(ctx context.Context, _ pgx.Tx, _ string) (storage.DeviceUsage, error) {
		if err := ctx.Err(); err != nil {
			return storage.DeviceUsageUnknown, err
		}
		if !permitted {
			return storage.DeviceUsageUnknown, nil
		}
		return storage.DeviceUsageUnused, nil
	}
}
