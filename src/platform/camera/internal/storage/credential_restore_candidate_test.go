package storage

import (
	"context"
	"testing"
	"time"
	"vms.local/platform/camera/internal/credentialadmission"
)

func TestCredentialRestoreCandidateRejectsMissingAuthority(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	var control *Store
	for _, c := range []context.Context{nil, context.Background(), ctx} {
		assertMaintenanceDenied(t, control.PrepareRestoredCredentialDatabase(c, nil, credentialadmission.Record{}, nil, "", nil, nil, nil, nil, CredentialAdmissionDatabase{}))
	}
}
