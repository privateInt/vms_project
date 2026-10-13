package storage

import (
	"context"
	"encoding/json"
	"math"
	"path/filepath"

	"github.com/jackc/pgx/v5"
	"vms.local/platform/camera/internal/credentialadmission"
	"vms.local/platform/camera/internal/credentialcrypto"
)

// These interfaces are private. Only the concrete file authority is installed
// by production constructors; synthetic schema-8 regression guards live in tests.
type credentialOperationGuard interface {
	acquire(context.Context, *CredentialStore) (credentialOperationLease, error)
}
type credentialOperationLease interface {
	Check(context.Context) error
	CheckTx(context.Context, pgx.Tx, string) error
	Close() error
}
type credentialFileGuard struct {
	policy   credentialadmission.Policy
	expected credentialadmission.Record
	endpoint *CredentialEndpoint
}
type credentialFileLease struct {
	read     *credentialadmission.ReadLease
	guard    *credentialFileGuard
	database CredentialAdmissionDatabase
	ms       []migration
}

func admissionDenied() error { return failure("CREDENTIAL_ADMISSION_UNAVAILABLE", nil) }

// NewAdmittedCredentialStore pins a reviewed external authority, OPEN record and
// approved endpoint. It performs no DB IO. Every operation acquires the actual
// read-only authority lease before any IO and holds it until return or unwinding.
// No callbacks, HTTP-supplied evidence or automatic record rediscovery are accepted.
func NewAdmittedCredentialStore(data, budget *Store, keys *credentialcrypto.Keyring, policy credentialadmission.Policy, expected credentialadmission.Record, endpoint *CredentialEndpoint) (*CredentialStore, error) {
	c, err := NewCredentialStore(data, budget, keys)
	if err != nil {
		return nil, admissionDenied()
	}
	if credentialadmission.Validate(expected) != nil || expected.State != credentialadmission.Open || expected.Binding == nil || expected.Generation == math.MaxInt64 || len(expected.SeenEncryptionKeyIDs) == credentialadmission.MaxSeen ||
		!filepath.IsAbs(policy.Directory) || filepath.Clean(policy.Directory) != policy.Directory || policy.Directory == "/" || policy.OwnerUID < 0 || policy.RuntimeGID < 0 || policy.LockIdentity.Inode == 0 || endpoint == nil || endpoint.hash == "" {
		return nil, admissionDenied()
	}
	// JSON round-trip owns the binding pointer and history slice as well as the
	// value fields. Subsequent edits to caller-owned configuration cannot repin us.
	raw, err := json.Marshal(expected)
	if err != nil {
		return nil, admissionDenied()
	}
	pinned, err := credentialadmission.Parse(raw)
	if err != nil {
		return nil, admissionDenied()
	}
	c.admission = &credentialFileGuard{policy, pinned, endpoint}
	return c, nil
}

func (g *credentialFileGuard) acquire(ctx context.Context, c *CredentialStore) (credentialOperationLease, error) {
	read, err := credentialadmission.AcquireReadOnly(ctx, g.policy, g.expected)
	if err != nil {
		return nil, admissionDenied()
	}
	ms, err := loadAdmissionMigrations()
	b := g.expected.Binding
	l := &credentialFileLease{read: read, guard: g, ms: ms, database: CredentialAdmissionDatabase{g.expected.DeploymentID, g.expected.Generation, g.expected.OperationID, b.DatabaseID, b.DatabaseName, int(b.SchemaVersion), b.MigrationSetSHA256}}
	if err != nil || l.Check(ctx) != nil || c.CheckCredentialAdmissionBindings(ctx, g.expected, g.endpoint) != nil ||
		c.withCredentialTx(ctx, l, c.data, "camera_credential_writer", func(pgx.Tx) error { return nil }) != nil ||
		c.withCredentialTx(ctx, l, c.budget, "camera_credential_budget", func(pgx.Tx) error { return nil }) != nil || l.Check(ctx) != nil {
		_ = l.Close()
		return nil, admissionDenied()
	}
	return l, nil
}
func (l *credentialFileLease) Check(ctx context.Context) error {
	if ctx == nil || ctx.Err() != nil || l.read.Check() != nil {
		return admissionDenied()
	}
	return nil
}
func (l *credentialFileLease) CheckTx(ctx context.Context, tx pgx.Tx, role string) error {
	if l.Check(ctx) != nil || !l.guard.endpoint.matchesTransport(tx.Conn().PgConn().Conn()) || checkCredentialAdmissionDatabaseTx(ctx, tx, l.database, role, l.ms) != nil || checkCredentialRuntimePermissionsTx(ctx, tx, role) != nil {
		return admissionDenied()
	}
	return nil
}
func (l *credentialFileLease) Close() error { return l.read.Close() }

func checkCredentialRuntimePermissionsTx(ctx context.Context, tx pgx.Tx, role string) error {
	query := `SELECT has_schema_privilege(current_user,'camera','USAGE')
AND has_table_privilege(current_user,'camera.devices','SELECT')
AND has_table_privilege(current_user,'camera.credentials','SELECT')
AND has_table_privilege(current_user,'camera.credentials','INSERT')
AND has_table_privilege(current_user,'camera.credential_versions','SELECT')
AND has_table_privilege(current_user,'camera.credential_versions','INSERT')
AND has_table_privilege(current_user,'camera.credential_requests','SELECT')
AND has_table_privilege(current_user,'camera.credential_requests','INSERT')
AND has_column_privilege(current_user,'camera.credentials','head_version','UPDATE')
AND has_column_privilege(current_user,'camera.credentials','updated_at','UPDATE')
AND has_column_privilege(current_user,'camera.credential_versions','revoked_at','UPDATE')`
	if role == "camera_credential_budget" {
		query = `SELECT has_schema_privilege(current_user,'camera','USAGE')
AND has_function_privilege(current_user,'camera.reserve_credential_encryption_use(text)','EXECUTE')
AND has_function_privilege(current_user,'camera.credential_encryption_key_ready(text)','EXECUTE')`
	} else if role != "camera_credential_writer" {
		return admissionDenied()
	}
	var allowed bool
	if tx.QueryRow(ctx, query).Scan(&allowed) != nil || !allowed {
		return admissionDenied()
	}
	return nil
}

func (c *CredentialStore) beginCredentialOperation(ctx context.Context) (credentialOperationLease, error) {
	if c == nil || c.admission == nil || ctx == nil || ctx.Err() != nil {
		return nil, admissionDenied()
	}
	l, err := c.admission.acquire(ctx, c)
	if err != nil || l == nil {
		if l != nil {
			_ = l.Close()
		}
		return nil, admissionDenied()
	}
	return l, nil
}

// WithTx completes rollback/commit (also on panic) before the outer operation
// releases its file lease. Inspect the actual connection for each transaction,
// including the separate committed budget transaction and both data phases.
func (c *CredentialStore) withCredentialTx(ctx context.Context, lease credentialOperationLease, s *Store, role string, fn func(pgx.Tx) error) error {
	if lease.Check(ctx) != nil {
		return admissionDenied()
	}
	return s.WithTx(ctx, func(tx pgx.Tx) error {
		if lease.CheckTx(ctx, tx, role) != nil {
			return admissionDenied()
		}
		if err := fn(tx); err != nil {
			return err
		}
		return lease.Check(ctx)
	})
}

func (c *CredentialStore) reserveCredentialUse(ctx context.Context, lease credentialOperationLease) (credentialcrypto.Reservation, error) {
	id := c.keys.ActiveEncryptionID()
	var result credentialcrypto.Reservation
	err := c.withCredentialTx(ctx, lease, c.budget, "camera_credential_budget", func(tx pgx.Tx) error {
		var use int64
		if err := tx.QueryRow(ctx, "SELECT camera.reserve_credential_encryption_use($1)", id).Scan(&use); err != nil {
			return failure("CREDENTIAL_STORE_UNAVAILABLE", err)
		}
		if use < 0 {
			return failure("CREDENTIAL_ENCRYPTION_KEY_UNAVAILABLE", nil)
		}
		if use == 0 {
			return failure("CREDENTIAL_ENCRYPTION_BUDGET_EXHAUSTED", nil)
		}
		if uint64(use) > credentialcrypto.MaxEncryptionUse {
			return failure("CREDENTIAL_STORE_UNAVAILABLE", nil)
		}
		result = credentialcrypto.Reservation{KeyID: id, Use: uint64(use)}
		return nil
	})
	if err != nil {
		return credentialcrypto.Reservation{}, err
	}
	return result, nil
}
