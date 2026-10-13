package storage

import (
	"context"
	"time"

	"github.com/jackc/pgx/v5"
	"vms.local/platform/camera/internal/credentialadmission"
	"vms.local/platform/camera/internal/credentialcrypto"
)

// PrepareRestoredCredentialDatabase is a privileged candidate preparation,
// NOT a dump/restore/reopen API. Trusted orchestration must already have restored
// an approved dump and exact key backup under the verified active maintenance
// boundary, holding this exclusive lease throughout. No LOGIN/OPEN is performed.
// PREPARED must be durably committed BEFORE calling. On ambiguous SQL commit,
// retry only this exact candidate: never restore again or reset its budget.
// restored is the independently approved backup marker, not discovered authority.
func (control *Store) PrepareRestoredCredentialDatabase(ctx context.Context, lease *credentialadmission.MaintenanceLease,
	prepared credentialadmission.Record, endpoint *CredentialEndpoint, sourceIP string, target *Store,
	candidate, previous, backup *credentialcrypto.Keyring, restored CredentialAdmissionDatabase) error {
	return control.restoredCredentialCandidate(ctx, lease, prepared, endpoint, sourceIP, target, candidate, previous, backup, restored, true)
}

// prepare=false verifies an already committed, unused candidate without repairing
// a restored marker or enrolling/resetting a budget. Used only before OPEN.
func (control *Store) restoredCredentialCandidate(ctx context.Context, lease *credentialadmission.MaintenanceLease,
	prepared credentialadmission.Record, endpoint *CredentialEndpoint, sourceIP string, target *Store,
	candidate, previous, backup *credentialcrypto.Keyring, restored CredentialAdmissionDatabase, prepare bool) error {
	if ctx == nil || ctx.Err() != nil || credentialadmission.Validate(prepared) != nil || prepared.State != credentialadmission.Prepared ||
		prepared.Binding == nil || candidate == nil || target == nil || target.pool == nil || endpoint == nil {
		return maintenanceDenied()
	}
	if _, ok := ctx.Deadline(); !ok {
		return maintenanceDenied()
	}
	b := *prepared.Binding
	hash, _, err := candidate.ProtectedBundleReceipt()
	if err != nil || hash != b.KeyBundleSHA256 || candidate.ActiveEncryptionID() != b.ActiveEncryptionKeyID ||
		candidate.ActiveIdempotencyID() != b.ActiveIdempotencyKeyID || candidate.CheckRestoreSuccessor(previous, backup) != nil {
		return maintenanceDenied()
	}
	for _, k := range []*credentialcrypto.Keyring{previous, backup} {
		if _, _, e := k.ProtectedBundleReceipt(); e != nil {
			return maintenanceDenied()
		}
	}
	ms, err := loadAdmissionMigrations()
	if err != nil || !restored.valid(admissionMigrationsHash(ms)) || restored.DeploymentID != prepared.DeploymentID ||
		restored.DatabaseName != b.DatabaseName || restored.DatabaseID == b.DatabaseID || restored.Generation >= prepared.Generation ||
		b.MigrationSetSHA256 != admissionMigrationsHash(ms) || b.DatabaseName != endpoint.database ||
		control.inspectCredentialMaintenanceHBA(ctx, lease, prepared, endpoint, sourceIP, true) != nil {
		return maintenanceDenied()
	}
	cfg := target.pool.Config().ConnConfig
	if cfg.User != CredentialMaintenanceRole || cfg.Database != b.DatabaseName || cfg.Host != endpoint.host || cfg.Port != endpoint.port ||
		len(cfg.Fallbacks) != 0 || target.admissionEndpoint == nil || target.admissionEndpoint.hash != endpoint.hash {
		return maintenanceDenied()
	}
	conn, err := target.pool.Acquire(ctx)
	if err != nil {
		return maintenanceDenied()
	}
	defer conn.Release()
	if !endpoint.matchesTransport(conn.Conn().PgConn().Conn()) {
		return maintenanceDenied()
	}
	tx, err := conn.BeginTx(ctx, pgx.TxOptions{IsoLevel: pgx.Serializable})
	if err != nil {
		return maintenanceDenied()
	}
	defer func() {
		c, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = tx.Rollback(c)
	}()
	var identity bool
	if tx.QueryRow(ctx, `SELECT session_user=current_user AND current_user='camera_maintenance' AND current_database()=$1
 AND host(inet_client_addr())=$2 AND ssl.ssl AND ssl.client_dn='/CN=camera_maintenance'
 AND r.rolsuper AND r.rolcanlogin AND NOT pg_is_in_recovery()
 FROM pg_roles r,pg_stat_ssl ssl WHERE r.rolname=current_user AND ssl.pid=pg_backend_pid()`, b.DatabaseName, sourceIP).Scan(&identity) != nil || !identity {
		return maintenanceDenied()
	}
	rows, err := tx.Query(ctx, "SELECT version,name,checksum FROM camera.schema_migrations ORDER BY version")
	if err != nil {
		return maintenanceDenied()
	}
	i := 0
	valid := true
	for rows.Next() {
		var v int
		var n, c string
		if rows.Scan(&v, &n, &c) != nil || i >= len(ms) || v != i+1 || n != ms[i].name || c != ms[i].checksum {
			valid = false
			break
		}
		i++
	}
	e := rows.Err()
	rows.Close()
	if !valid || e != nil || i != len(ms) {
		return maintenanceDenied()
	}
	if _, err = tx.Exec(ctx, "LOCK TABLE camera.credential_admission_database, camera.credential_encryption_budgets IN EXCLUSIVE MODE"); err != nil {
		return maintenanceDenied()
	}
	next := CredentialAdmissionDatabase{prepared.DeploymentID, prepared.Generation, prepared.OperationID, b.DatabaseID, b.DatabaseName, 9, b.MigrationSetSHA256}
	var actual CredentialAdmissionDatabase
	if tx.QueryRow(ctx, `SELECT deployment_id,generation,operation_id,database_id,database_name,schema_version,migration_set_sha256 FROM camera.credential_admission_database WHERE singleton=1`).Scan(&actual.DeploymentID, &actual.Generation, &actual.OperationID, &actual.DatabaseID, &actual.DatabaseName, &actual.SchemaVersion, &actual.MigrationSetSHA256) != nil || (actual != restored && actual != next) {
		return maintenanceDenied()
	}
	rows, err = tx.Query(ctx, `SELECT encryption_key_id,$1::text FROM camera.credential_versions UNION ALL SELECT $2::text,fingerprint_key_id FROM camera.credential_requests`, candidate.ActiveIdempotencyID(), previous.ActiveEncryptionID())
	if err != nil {
		return maintenanceDenied()
	}
	for rows.Next() {
		var enc, mac string
		if rows.Scan(&enc, &mac) != nil || enc == b.ActiveEncryptionKeyID || !candidate.HasHistoricalKeys(enc, mac) {
			valid = false
			break
		}
	}
	e = rows.Err()
	rows.Close()
	if !valid || e != nil {
		return maintenanceDenied()
	}
	var count int
	var uses int64
	var enabled bool
	if tx.QueryRow(ctx, "SELECT count(*) FROM camera.credential_encryption_budgets WHERE key_id=$1", b.ActiveEncryptionKeyID).Scan(&count) != nil {
		return maintenanceDenied()
	}
	if actual == restored {
		if !prepare || count != 0 {
			return maintenanceDenied()
		}
	} else {
		if count != 1 || tx.QueryRow(ctx, "SELECT uses,enabled FROM camera.credential_encryption_budgets WHERE key_id=$1", b.ActiveEncryptionKeyID).Scan(&uses, &enabled) != nil || uses != 0 || !enabled {
			return maintenanceDenied()
		}
		var oldEnabled int
		if tx.QueryRow(ctx, "SELECT count(*) FROM camera.credential_encryption_budgets WHERE key_id<>$1 AND enabled", b.ActiveEncryptionKeyID).Scan(&oldEnabled) != nil || oldEnabled != 0 {
			return maintenanceDenied()
		}
	}
	if actual == restored {
		if _, err = tx.Exec(ctx, "UPDATE camera.credential_encryption_budgets SET enabled=false"); err != nil {
			return maintenanceDenied()
		}
		if _, err = tx.Exec(ctx, "INSERT INTO camera.credential_encryption_budgets(key_id) VALUES($1)", b.ActiveEncryptionKeyID); err != nil {
			return maintenanceDenied()
		}
		if _, err = tx.Exec(ctx, `UPDATE camera.credential_admission_database SET deployment_id=$1,generation=$2,operation_id=$3,database_id=$4,database_name=$5,schema_version=$6,migration_set_sha256=$7,written_at=CURRENT_TIMESTAMP WHERE singleton=1`, next.DeploymentID, next.Generation, next.OperationID, next.DatabaseID, next.DatabaseName, next.SchemaVersion, next.MigrationSetSHA256); err != nil {
			return maintenanceDenied()
		}
	}
	if control.inspectCredentialMaintenanceHBA(ctx, lease, prepared, endpoint, sourceIP, true) != nil || tx.Commit(ctx) != nil {
		return maintenanceDenied()
	}
	if confirmMaintenanceFence(lease, prepared) != nil {
		return maintenanceDenied()
	}
	return nil
}
