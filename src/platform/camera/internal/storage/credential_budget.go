package storage

import (
	"context"
	"vms.local/platform/camera/internal/credentialcrypto"
)

// EnrollCredentialEncryptionKey is a schema-owner operation for a genuinely new
// key ID. It never resets/reactivates an existing key, even after exhaustion.
// The caller must obtain the new independent key through protected key management.
func (s *Store) EnrollCredentialEncryptionKey(ctx context.Context, id string) error {
	if !credentialKeyID.MatchString(id) {
		return failure("CONTRACT_INVALID", nil)
	}
	_, err := s.pool.Exec(ctx, "INSERT INTO camera.credential_encryption_budgets(key_id) VALUES ($1)", id)
	if stateCode(err) == "23505" {
		return failure("CREDENTIAL_ENCRYPTION_KEY_ALREADY_ENROLLED", nil)
	}
	if err != nil {
		return failure("CREDENTIAL_STORE_UNAVAILABLE", err)
	}
	return nil
}

// DisableCredentialEncryption is an owner-only maintenance operation. A restore
// workflow MUST fence writes before admitting traffic; DB snapshots alone cannot
// prove the per-key lifetime high-water mark. New writes require a fresh key ID.
func (s *Store) DisableCredentialEncryption(ctx context.Context) error {
	_, err := s.pool.Exec(ctx, "UPDATE camera.credential_encryption_budgets SET enabled=false")
	if err != nil {
		return failure("CREDENTIAL_STORE_UNAVAILABLE", err)
	}
	return nil
}

// ReserveCredentialEncryptionUse executes in its own committed implicit
// transaction. Never call the SQL function from the data transaction. A lost
// response may consume a use; it must never cause its number to be reused.
func (s *Store) ReserveCredentialEncryptionUse(ctx context.Context, id string) (credentialcrypto.Reservation, error) {
	if !credentialKeyID.MatchString(id) {
		return credentialcrypto.Reservation{}, failure("CONTRACT_INVALID", nil)
	}
	var use int64
	if err := s.pool.QueryRow(ctx, "SELECT camera.reserve_credential_encryption_use($1)", id).Scan(&use); err != nil {
		return credentialcrypto.Reservation{}, failure("CREDENTIAL_STORE_UNAVAILABLE", err)
	}
	if use < 0 {
		return credentialcrypto.Reservation{}, failure("CREDENTIAL_ENCRYPTION_KEY_UNAVAILABLE", nil)
	}
	if use == 0 {
		return credentialcrypto.Reservation{}, failure("CREDENTIAL_ENCRYPTION_BUDGET_EXHAUSTED", nil)
	}
	if uint64(use) > credentialcrypto.MaxEncryptionUse {
		return credentialcrypto.Reservation{}, failure("CREDENTIAL_STORE_UNAVAILABLE", nil)
	}
	return credentialcrypto.Reservation{KeyID: id, Use: uint64(use)}, nil
}

// Fixed roles must be created separately by an isolated/bootstrap workflow.
// This never broadens camera_runtime to read ciphertext or private target policy.
func (s *Store) ProvisionCredentialRuntime(ctx context.Context) error {
	_, err := s.pool.Exec(ctx, `GRANT USAGE ON SCHEMA camera TO camera_credential_writer, camera_credential_budget;
GRANT SELECT ON camera.devices TO camera_credential_writer;
GRANT SELECT ON camera.schema_migrations TO camera_credential_writer;
GRANT SELECT, INSERT ON camera.credentials, camera.credential_versions, camera.credential_requests TO camera_credential_writer;
GRANT UPDATE (head_version,updated_at) ON camera.credentials TO camera_credential_writer;
GRANT UPDATE (revoked_at) ON camera.credential_versions TO camera_credential_writer;
GRANT EXECUTE ON FUNCTION camera.reserve_credential_encryption_use(text) TO camera_credential_budget;
GRANT EXECUTE ON FUNCTION camera.credential_encryption_key_ready(text) TO camera_credential_budget;`)
	if err != nil {
		return failure("CREDENTIAL_RUNTIME_GRANT_FAILED", err)
	}
	return nil
}
