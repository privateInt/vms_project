package storage

import "context"

// CheckReady holds the same external lease as business methods. It verifies
// actual keys/endpoints/marker/grants and budget without consuming a use.
// This does not activate HTTP, device IO or an operational restore workflow.
func (c *CredentialStore) CheckReady(ctx context.Context) error {
	lease, err := c.beginCredentialOperation(ctx)
	if err != nil {
		return err
	}
	defer lease.Close()
	if err = c.checkCredentialPermissions(ctx); err != nil {
		return err
	}
	return lease.Check(ctx)
}

func (c *CredentialStore) checkCredentialPermissions(ctx context.Context) error {
	var allowed bool
	err := c.data.pool.QueryRow(ctx, `SELECT has_schema_privilege(current_user,'camera','USAGE')
AND has_table_privilege(current_user,'camera.schema_migrations','SELECT')
AND has_table_privilege(current_user,'camera.devices','SELECT')
AND has_table_privilege(current_user,'camera.credentials','SELECT')
AND has_table_privilege(current_user,'camera.credentials','INSERT')
AND has_table_privilege(current_user,'camera.credential_versions','SELECT')
AND has_table_privilege(current_user,'camera.credential_versions','INSERT')
AND has_table_privilege(current_user,'camera.credential_requests','SELECT')
AND has_table_privilege(current_user,'camera.credential_requests','INSERT')
AND has_column_privilege(current_user,'camera.credentials','head_version','UPDATE')
AND has_column_privilege(current_user,'camera.credentials','updated_at','UPDATE')
AND has_column_privilege(current_user,'camera.credential_versions','revoked_at','UPDATE')`).Scan(&allowed)
	if err != nil || !allowed {
		return failure("CREDENTIAL_PERMISSIONS_NOT_READY", nil)
	}
	err = c.budget.pool.QueryRow(ctx, `SELECT has_schema_privilege(current_user,'camera','USAGE')
AND has_function_privilege(current_user,'camera.reserve_credential_encryption_use(text)','EXECUTE')
AND has_function_privilege(current_user,'camera.credential_encryption_key_ready(text)','EXECUTE')`).Scan(&allowed)
	if err != nil || !allowed {
		return failure("CREDENTIAL_PERMISSIONS_NOT_READY", nil)
	}
	if err = c.budget.pool.QueryRow(ctx, "SELECT camera.credential_encryption_key_ready($1)", c.keys.ActiveEncryptionID()).Scan(&allowed); err != nil || !allowed {
		return failure("CREDENTIAL_ENCRYPTION_KEY_UNAVAILABLE", nil)
	}
	return nil
}
