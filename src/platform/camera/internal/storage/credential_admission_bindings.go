package storage

import (
	"context"
	"time"

	"github.com/jackc/pgx/v5"
	"vms.local/platform/camera/internal/credentialadmission"
)

// CheckCredentialAdmissionBindings compares approved values with actual loaded
// keys and both approved DB pools. It is a read-only foundation check, NOT an
// authorization guard. The caller's locked authority must supply the record.
// It does not hold an external lease or authorize any subsequent credential IO.
func (c *CredentialStore) CheckCredentialAdmissionBindings(ctx context.Context, r credentialadmission.Record, p *CredentialEndpoint) error {
	denied := func() error { return failure("ADMISSION_BINDING_UNAVAILABLE", nil) }
	if c == nil || c.keys == nil || c.data == nil || c.budget == nil || c.data.pool == nil || c.budget.pool == nil || c.data.pool == c.budget.pool || p == nil || p.hash == "" || credentialadmission.Validate(r) != nil || (r.State != "OPEN" && r.State != "PREPARED") || r.Binding == nil {
		return denied()
	}
	b := r.Binding
	keyHash, readOnly, err := c.keys.ProtectedBundleReceipt()
	if err != nil || !readOnly || keyHash != b.KeyBundleSHA256 || c.keys.ActiveEncryptionID() != b.ActiveEncryptionKeyID || c.keys.ActiveIdempotencyID() != b.ActiveIdempotencyKeyID || p.hash != b.EndpointProfileSHA256 || p.database != b.DatabaseName {
		return denied()
	}
	ms, err := loadAdmissionMigrations()
	if err != nil {
		return denied()
	}
	db := CredentialAdmissionDatabase{DeploymentID: r.DeploymentID, Generation: r.Generation, OperationID: r.OperationID, DatabaseID: b.DatabaseID, DatabaseName: b.DatabaseName, SchemaVersion: int(b.SchemaVersion), MigrationSetSHA256: b.MigrationSetSHA256}
	if !db.valid(admissionMigrationsHash(ms)) {
		return denied()
	}
	for _, v := range []struct {
		s    *Store
		role string
	}{{c.data, b.WriterRole}, {c.budget, b.BudgetRole}} {
		if v.s.admissionEndpoint == nil || v.s.admissionEndpoint.hash != p.hash {
			return denied()
		}
		cfg := v.s.pool.Config().ConnConfig
		if cfg.Host != p.host || cfg.Port != p.port || cfg.Database != p.database || cfg.User != v.role || len(cfg.Fallbacks) != 0 {
			return denied()
		}
		err = checkAdmissionPoolSnapshot(ctx, v.s, p, db, v.role, ms, b.ActiveEncryptionKeyID)
		if err != nil {
			return denied()
		}
	}
	return nil
}

func checkAdmissionPoolSnapshot(ctx context.Context, s *Store, p *CredentialEndpoint, db CredentialAdmissionDatabase, role string, ms []migration, keyID string) error {
	denied := func() error { return failure("ADMISSION_BINDING_UNAVAILABLE", nil) }
	conn, err := s.pool.Acquire(ctx)
	if err != nil {
		return denied()
	}
	defer conn.Release()
	if !p.matchesTransport(conn.Conn().PgConn().Conn()) {
		return denied()
	}
	tx, err := conn.BeginTx(ctx, pgx.TxOptions{IsoLevel: pgx.RepeatableRead, AccessMode: pgx.ReadOnly})
	if err != nil {
		return denied()
	}
	defer func() {
		cleanup, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = tx.Rollback(cleanup)
	}()
	if checkCredentialAdmissionDatabaseTx(ctx, tx, db, role, ms) != nil {
		return denied()
	}
	if role == "camera_credential_budget" {
		var ready bool
		if tx.QueryRow(ctx, "SELECT camera.credential_encryption_key_ready($1)", keyID).Scan(&ready) != nil || !ready {
			return denied()
		}
	}
	if tx.Commit(ctx) != nil {
		return denied()
	}
	return nil
}
