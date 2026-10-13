package storage

import (
	"context"
	"errors"

	"github.com/jackc/pgx/v5"
	"vms.local/platform/camera/internal/contracts"
)

// GetVersionMetadata is management inspection, not a reference check, decrypt,
// readiness assertion or connection authorization. Revoked versions remain visible
// to authorized managers, including after parent deletion. No budget is reserved.
func (c *CredentialStore) GetVersionMetadata(ctx context.Context, identity CredentialIdentity, credentialID string, version int64, authorize CredentialAuthorizer) (CredentialMetadata, error) {
	if !identity.valid(false) || !contracts.ValidDeviceID(credentialID) || version < 1 {
		return CredentialMetadata{}, failure("CONTRACT_INVALID", nil)
	}
	lease, err := c.beginCredentialOperation(ctx)
	if err != nil {
		return CredentialMetadata{}, err
	}
	defer lease.Close()
	var result CredentialMetadata
	err = c.withCredentialTx(ctx, lease, c.data, "camera_credential_writer", func(tx pgx.Tx) error {
		if authorize == nil {
			return failure("CREDENTIAL_AUTHORIZATION_UNAVAILABLE", nil)
		}
		// Scope/device ownership is immutable. Derive the real device internally;
		// caller headers or body cannot select a different device for authorization.
		var deviceID string
		err := tx.QueryRow(ctx, "SELECT device_id FROM camera.credentials WHERE scope_id=$1 AND credential_id=$2", identity.ScopeID, credentialID).Scan(&deviceID)
		if errors.Is(err, pgx.ErrNoRows) {
			return failure("CREDENTIAL_UNAVAILABLE", nil)
		}
		if err != nil || !contracts.ValidDeviceID(deviceID) {
			return failure("CREDENTIAL_STORE_UNAVAILABLE", nil)
		}
		reference := CredentialReference{CredentialID: credentialID, DeviceID: deviceID, Version: version}
		if err = authorizeCredential(ctx, tx, authorize, accessFor(identity, reference, "MANAGE")); err != nil {
			return err
		}
		// Select safe metadata only. Never load target, ciphertext or request journal.
		result, err = scanCredentialMetadata(tx.QueryRow(ctx, `SELECT c.credential_id,c.device_id,v.version,v.created_at,v.revoked_at
FROM camera.credentials c JOIN camera.credential_versions v USING (credential_id)
WHERE c.scope_id=$1 AND c.device_id=$2 AND c.credential_id=$3 AND v.version=$4`, identity.ScopeID, deviceID, credentialID, version))
		if errors.Is(err, pgx.ErrNoRows) {
			return failure("CREDENTIAL_UNAVAILABLE", nil)
		}
		if err != nil || !contractsCredentialMetadata(result) {
			return failure("CREDENTIAL_STORE_UNAVAILABLE", nil)
		}
		return nil
	})
	if err != nil {
		return CredentialMetadata{}, err
	}
	if err = lease.Check(ctx); err != nil {
		return CredentialMetadata{}, err
	}
	return result, nil
}
