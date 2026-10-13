package storage

import (
	"context"
	"reflect"
	"time"

	"github.com/jackc/pgx/v5"
	"vms.local/platform/camera/internal/credentialadmission"
)

func maintenanceDenied() error { return failure("CREDENTIAL_MAINTENANCE_UNAVAILABLE", nil) }

func confirmMaintenanceFence(lease *credentialadmission.MaintenanceLease, expected credentialadmission.Record) error {
	if lease == nil {
		return maintenanceDenied()
	}
	current, err := lease.Snapshot()
	if err != nil || !reflect.DeepEqual(current, expected) || lease.Commit(expected, expected) != nil {
		return maintenanceDenied()
	}
	return nil
}

// FenceCredentialDatabase is an explicit privileged maintenance primitive, never
// a runtime route. The caller exclusively owns the lease until the entire later
// maintenance procedure completes; do not concurrently Close/Commit that lease.
// expected must be a durably committed FENCED record with the reviewed last DB
// binding. Connect s to the SAME server's postgres control database, so retries
// can authenticate even after the target database refuses all new connections.
//
// Success closes target DB admission for every role (including owners), sets both
// fixed credential roles NOLOGIN cluster-wide, terminates their sessions anywhere
// in this cluster and ALL target DB sessions, then verifies drain and no prepared
// transactions. It never restores data/keys, disables budgets, opens accounts or
// releases the external fence. This is not an OS/network/admin trust boundary.
func (s *Store) FenceCredentialDatabase(ctx context.Context, lease *credentialadmission.MaintenanceLease, expected credentialadmission.Record, endpoint *CredentialEndpoint) error {
	if ctx == nil || ctx.Err() != nil || s == nil || s.pool == nil || endpoint == nil ||
		credentialadmission.Validate(expected) != nil || expected.State != credentialadmission.Fenced || expected.Binding == nil {
		return maintenanceDenied()
	}
	if _, ok := ctx.Deadline(); !ok {
		return maintenanceDenied()
	}
	b := *expected.Binding
	hash, err := CredentialAdmissionMigrationsSHA256()
	if err != nil || b.MigrationSetSHA256 != hash || endpoint.hash == "" || endpoint.hash != b.EndpointProfileSHA256 ||
		endpoint.database != b.DatabaseName || b.DatabaseName == "postgres" || b.DatabaseName == "template0" || b.DatabaseName == "template1" {
		return maintenanceDenied()
	}
	cfg := s.pool.Config().ConnConfig
	if cfg.Database != "postgres" || cfg.Host != endpoint.host || cfg.Port != endpoint.port || len(cfg.Fallbacks) != 0 ||
		cfg.User == b.WriterRole || cfg.User == b.BudgetRole || confirmMaintenanceFence(lease, expected) != nil {
		return maintenanceDenied()
	}
	conn, err := s.pool.Acquire(ctx)
	if err != nil {
		return maintenanceDenied()
	}
	defer conn.Release()
	if !endpoint.matchesTransport(conn.Conn().PgConn().Conn()) {
		return maintenanceDenied()
	}
	var identity bool
	err = conn.QueryRow(ctx, `SELECT session_user=current_user AND session_user::text=$1
AND pg_catalog.current_database()='postgres' AND r.rolsuper AND r.rolcanlogin
AND NOT pg_catalog.pg_is_in_recovery() AND NOT pg_catalog.current_setting('transaction_read_only')::boolean
AND EXISTS (SELECT 1 FROM pg_catalog.pg_database d WHERE d.datname=$2 AND NOT d.datistemplate AND d.datdba=r.oid)
FROM pg_catalog.pg_roles r WHERE r.rolname=current_user`, cfg.User, b.DatabaseName).Scan(&identity)
	if err != nil || !identity {
		return maintenanceDenied()
	}
	var safeRoles bool
	err = conn.QueryRow(ctx, `SELECT count(*)=2 AND bool_and(NOT (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls))
FROM pg_catalog.pg_roles WHERE rolname IN ('camera_credential_writer','camera_credential_budget')`).Scan(&safeRoles)
	if err != nil || !safeRoles || maintenancePreparedClear(ctx, conn, b.DatabaseName) != nil {
		return maintenanceDenied()
	}
	// Closing admission precedes termination: a killed client cannot reconnect.
	// These catalog changes commit together. A lost response requires a retry
	// under the SAME FENCED generation; never compensate by reopening the DB.
	if confirmMaintenanceFence(lease, expected) != nil {
		return maintenanceDenied()
	}
	tx, err := conn.BeginTx(ctx, pgx.TxOptions{IsoLevel: pgx.ReadCommitted})
	if err != nil {
		return maintenanceDenied()
	}
	defer func() {
		cleanup, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = tx.Rollback(cleanup)
	}()
	_, err = tx.Exec(ctx, `ALTER ROLE camera_credential_writer NOLOGIN;
ALTER ROLE camera_credential_budget NOLOGIN; ALTER DATABASE `+pgx.Identifier{b.DatabaseName}.Sanitize()+` ALLOW_CONNECTIONS false`)
	if err != nil || tx.Commit(ctx) != nil {
		return maintenanceDenied()
	}
	// Do not mistake pg_terminate_backend's signal-delivery acknowledgement for
	// completed termination. Poll an independent, refreshed activity snapshot.
	ticker := time.NewTicker(20 * time.Millisecond)
	defer ticker.Stop()
	for {
		if ctx.Err() != nil || confirmMaintenanceFence(lease, expected) != nil {
			return maintenanceDenied()
		}
		if _, err = conn.Exec(ctx, `SELECT pg_catalog.pg_stat_clear_snapshot()`); err != nil {
			return maintenanceDenied()
		}
		var sessions int
		err = conn.QueryRow(ctx, `SELECT count(*) FROM pg_catalog.pg_stat_activity WHERE pid<>pg_catalog.pg_backend_pid()
AND (datname=$1 OR usename IN ('camera_credential_writer','camera_credential_budget'))`, b.DatabaseName).Scan(&sessions)
		if err != nil {
			return maintenanceDenied()
		}
		if sessions == 0 {
			break
		}
		if _, err = conn.Exec(ctx, `SELECT pg_catalog.pg_terminate_backend(pid) FROM pg_catalog.pg_stat_activity WHERE pid<>pg_catalog.pg_backend_pid()
AND (datname=$1 OR usename IN ('camera_credential_writer','camera_credential_budget'))`, b.DatabaseName); err != nil {
			return maintenanceDenied()
		}
		select {
		case <-ctx.Done():
			return maintenanceDenied()
		case <-ticker.C:
		}
	}
	var closed bool
	err = conn.QueryRow(ctx, `SELECT NOT d.datallowconn
AND (SELECT count(*)=2 AND bool_and(NOT rolcanlogin) FROM pg_catalog.pg_roles WHERE rolname IN ('camera_credential_writer','camera_credential_budget'))
FROM pg_catalog.pg_database d WHERE d.datname=$1`, b.DatabaseName).Scan(&closed)
	if err != nil || !closed || maintenancePreparedClear(ctx, conn, b.DatabaseName) != nil || confirmMaintenanceFence(lease, expected) != nil {
		return maintenanceDenied()
	}
	return nil
}

func maintenancePreparedClear(ctx context.Context, conn interface {
	QueryRow(context.Context, string, ...any) pgx.Row
}, database string) error {
	var clear bool
	err := conn.QueryRow(ctx, `SELECT NOT EXISTS (SELECT 1 FROM pg_catalog.pg_prepared_xacts WHERE database=$1
OR owner IN ('camera_credential_writer','camera_credential_budget'))`, database).Scan(&clear)
	if err != nil || !clear {
		return maintenanceDenied()
	}
	return nil
}
