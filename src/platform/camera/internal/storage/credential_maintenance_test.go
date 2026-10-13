package storage

import (
	"context"
	"testing"
	"time"

	"vms.local/platform/camera/internal/credentialadmission"
)

func assertMaintenanceDenied(t *testing.T, err error) {
	t.Helper()
	safe, ok := err.(*Error)
	if !ok || safe.Code != "CREDENTIAL_MAINTENANCE_UNAVAILABLE" || safe.cause != nil || safe.SQLState != "" {
		t.Fatal("maintenance denial must be fixed and cause-free")
	}
}

func TestCredentialMaintenanceRejectsWithoutIO(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	r, _ := credentialadmission.NewFenced("11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222", "2026-10-07T00:00:00Z")
	for _, s := range []*Store{nil, {}} {
		for _, c := range []context.Context{nil, context.Background(), ctx} {
			assertMaintenanceDenied(t, s.FenceCredentialDatabase(c, nil, r, nil))
		}
	}
	assertMaintenanceDenied(t, confirmMaintenanceFence(nil, r))
	assertMaintenanceDenied(t, confirmMaintenanceFence(&credentialadmission.MaintenanceLease{}, r))
}
