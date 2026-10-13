package storage

import (
	"context"
	"reflect"
	"strconv"

	"vms.local/platform/camera/internal/credentialadmission"
	"vms.local/platform/camera/internal/credentialcrypto"
)

// AuthorizeRestoredCredentialOpen records OPEN intent for an exact committed,
// unused restore candidate, under the maintenance-only boundary and exclusive
// lease. It never restores, repairs a marker, enrolls/resets a budget, changes
// HBA, enables LOGIN or starts runtime. Trusted orchestration installs/verifies
// its runtime boundary and enables accounts only AFTER durable OPEN. It must
// release this exclusive lease before runtime's public whole-operation leases.
//
// A lost/uncertain response requires a fresh lease and this exact prepared/opened
// pair. An exact durable OPEN retry only confirms intent; it does not rewind
// post-OPEN uses or assert runtime readiness. Never compensate by restoring.
func (control *Store) AuthorizeRestoredCredentialOpen(ctx context.Context, lease *credentialadmission.MaintenanceLease,
	prepared, opened credentialadmission.Record, endpoint *CredentialEndpoint, sourceIP string, target *Store,
	candidate, previous, backup *credentialcrypto.Keyring, restored CredentialAdmissionDatabase) error {
	if ctx == nil || ctx.Err() != nil || lease == nil || control == nil || target == nil || candidate == nil || prepared.State != credentialadmission.Prepared {
		return maintenanceDenied()
	}
	if _, ok := ctx.Deadline(); !ok {
		return maintenanceDenied()
	}
	next, err := credentialadmission.NextOpen(prepared, opened.WrittenAt)
	if err != nil || !reflect.DeepEqual(next, opened) {
		return maintenanceDenied()
	}
	current, err := lease.Snapshot()
	if err != nil {
		return maintenanceDenied()
	}
	if reflect.DeepEqual(current, opened) {
		return confirmMaintenanceFence(lease, opened)
	}
	if !reflect.DeepEqual(current, prepared) ||
		control.restoredCredentialCandidate(ctx, lease, prepared, endpoint, sourceIP, target, candidate, previous, backup, restored, false) != nil {
		return maintenanceDenied()
	}
	// A successful candidate inspection is not OPEN; commit the same exact
	// pair durably before any later account/HBA/runtime action.
	if lease.Commit(prepared, opened) != nil {
		return maintenanceDenied()
	}
	return confirmMaintenanceFence(lease, opened)
}

// CredentialRestoredRuntimeHBA is a COMPLETE source-pinned runtime policy for
// this restore unit. The maintenance source retains mTLS; the distinct runtime
// source can authenticate only the two fixed roles, only to the target DB,
// using SCRAM over TLS. Runtime verifies server CA/name with its approved
// endpoint. This builder neither installs/reloads nor proves active rules.
func CredentialRestoredRuntimeHBA(database, maintenanceIP, runtimeIP string) ([]byte, error) {
	maintenance, err := CredentialMaintenanceHBA(database, maintenanceIP)
	_, bits := maintenanceSource(runtimeIP)
	if err != nil || bits == 0 || maintenanceIP == runtimeIP {
		return nil, maintenanceDenied()
	}
	// Insert after the maintenance rule and before both universal rejects.
	prefix := string(maintenance[:len(maintenance)-len("host all all 0.0.0.0/0 reject\nhost all all ::/0 reject\n")])
	return []byte(prefix + "hostssl \"" + database + "\" camera_credential_writer,camera_credential_budget " +
		runtimeIP + "/" + strconv.Itoa(bits) + " scram-sha-256\nhost all all 0.0.0.0/0 reject\nhost all all ::/0 reject\n"), nil
}
