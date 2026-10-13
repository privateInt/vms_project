//go:build linux

package storage

import (
	"context"
	"fmt"
	"net"
	"net/url"
	"os"
	"reflect"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
	"vms.local/platform/camera/internal/credentialadmission"
)

func maintenanceFixture(t *testing.T) (*Store, *Store, *Store, *Store, context.Context, *CredentialEndpoint, credentialadmission.Policy, credentialadmission.Record, *credentialadmission.MaintenanceLease) {
	t.Helper()
	if os.Getenv("CAMERA_TEST_MAINTENANCE_FENCE") != "1" {
		t.Skip("explicit disposable maintenance fence runner required")
	}
	if os.Getenv("CAMERA_TEST_ENGINE") == "pglite" {
		t.Fatal("native session and account checks required")
	}
	owner, writer, budget, ctx, _ := admissionStores(t)
	cfg := owner.pool.Config().ConnConfig
	addresses, err := net.LookupHost(cfg.Host)
	if err != nil || len(addresses) != 1 {
		t.Fatal("one isolated server address required")
	}
	ip := net.ParseIP(addresses[0]).String()
	p, err := NewCredentialEndpoint(ip, cfg.Port, cfg.Database, "disable", "", nil)
	if err != nil {
		t.Fatal("synthetic endpoint unavailable")
	}
	u, _ := url.Parse(os.Getenv("CAMERA_TEST_DATABASE_URL"))
	u.Host = net.JoinHostPort(ip, fmt.Sprint(cfg.Port))
	u.Path = "/postgres"
	control, err := Open(ctx, u.String())
	if err != nil {
		t.Fatal("isolated privileged control connection unavailable")
	}
	t.Cleanup(control.Close)
	// Test cleanup ONLY: disposable fixture is reopened to allow later schema
	// regressions. The product primitive has no resume/compensation path.
	t.Cleanup(func() {
		cleanup, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		_, _ = control.pool.Exec(cleanup, `ALTER DATABASE vms_camera_test ALLOW_CONNECTIONS true;
ALTER ROLE camera_credential_writer LOGIN NOCREATEDB; ALTER ROLE camera_credential_budget LOGIN`)
		// Target sessions were deliberately terminated. Discard their cached
		// connections before the earlier fixture cleanups remove role grants.
		owner.pool.Reset()
	})
	dir := t.TempDir()
	if os.Chmod(dir, 0750) != nil {
		t.Fatal("authority directory unavailable")
	}
	policy := credentialadmission.Policy{Directory: dir, OwnerUID: os.Geteuid(), RuntimeGID: os.Getegid()}
	db := admissionDatabaseFixture(t)
	r, _ := credentialadmission.NewFenced(db.DeploymentID, db.OperationID, "2026-10-07T00:00:00Z")
	policy.LockIdentity, err = credentialadmission.Bootstrap(ctx, policy, r)
	if err != nil {
		t.Fatal("synthetic authority bootstrap failed")
	}
	l, err := credentialadmission.AcquireMaintenance(ctx, policy)
	if err != nil {
		t.Fatal("maintenance lease unavailable")
	}
	t.Cleanup(func() { _ = l.Close() })
	b := credentialadmission.Binding{DatabaseID: db.DatabaseID, DatabaseName: db.DatabaseName, SchemaVersion: 9,
		MigrationSetSHA256: db.MigrationSetSHA256, EndpointProfileSHA256: p.SHA256(),
		KeyBundleSHA256:       digestBytes([]byte("synthetic last binding; not a key receipt")),
		ActiveEncryptionKeyID: credentialOldEnc, ActiveIdempotencyKeyID: credentialOldMac,
		WriterRole: "camera_credential_writer", BudgetRole: "camera_credential_budget"}
	prepared, err := credentialadmission.NextPrepare(r, b, "2026-10-07T00:00:00Z")
	if err != nil || l.Commit(r, prepared) != nil {
		t.Fatal("synthetic PREPARED commit failed")
	}
	opened, _ := credentialadmission.NextOpen(prepared, "2026-10-07T00:00:00Z")
	if l.Commit(prepared, opened) != nil {
		t.Fatal("synthetic OPEN commit failed")
	}
	return owner, writer, budget, control, ctx, p, policy, opened, l
}

func maintenanceNextFence(t *testing.T, l *credentialadmission.MaintenanceLease, opened credentialadmission.Record) credentialadmission.Record {
	t.Helper()
	fenced, err := credentialadmission.NextFence(opened, "55555555-5555-4555-8555-555555555555", "2026-10-07T01:00:00Z")
	if err != nil || l.Commit(opened, fenced) != nil {
		t.Fatal("external fence commit failed")
	}
	return fenced
}

func maintenanceCatalog(t *testing.T, control *Store, ctx context.Context, closed bool) {
	t.Helper()
	var allow bool
	var logins int
	if control.pool.QueryRow(ctx, `SELECT datallowconn FROM pg_database WHERE datname='vms_camera_test'`).Scan(&allow) != nil || allow == closed ||
		control.pool.QueryRow(ctx, `SELECT count(*) FROM pg_roles WHERE rolname IN ('camera_credential_writer','camera_credential_budget') AND rolcanlogin`).Scan(&logins) != nil || (closed && logins != 0) || (!closed && logins != 2) {
		t.Fatal("unexpected database or role admission state")
	}
}

func TestNativeCredentialMaintenanceAuthorityAndIdentity(t *testing.T) {
	_, writer, _, control, ctx, p, _, opened, lease := maintenanceFixture(t)
	assertMaintenanceDenied(t, control.FenceCredentialDatabase(ctx, lease, opened, p))
	fenced := maintenanceNextFence(t, lease, opened)
	assertMaintenanceDenied(t, control.FenceCredentialDatabase(context.Background(), lease, fenced, p))
	canceled, stop := context.WithCancel(ctx)
	stop()
	assertMaintenanceDenied(t, control.FenceCredentialDatabase(canceled, lease, fenced, p))
	stale := fenced
	stale.Generation++
	assertMaintenanceDenied(t, control.FenceCredentialDatabase(ctx, lease, stale, p))
	wrong, _ := NewCredentialEndpoint(p.host, p.port+1, p.database, "disable", "", nil)
	assertMaintenanceDenied(t, control.FenceCredentialDatabase(ctx, lease, fenced, wrong))
	// A correctly authenticated runtime role is still NOT maintenance authority.
	u, _ := url.Parse(bindingRoleDSN(t, writer, p.host, "disable"))
	u.Path = "/postgres"
	unprivileged, err := Open(ctx, u.String())
	if err != nil {
		t.Fatal("synthetic runtime control authentication failed")
	}
	defer unprivileged.Close()
	assertMaintenanceDenied(t, unprivileged.FenceCredentialDatabase(ctx, lease, fenced, p))
	maintenanceCatalog(t, control, ctx, false)
	t.Log("CREDENTIAL_MAINTENANCE_PHASE_OK:authority-rejection")
	if _, err = control.pool.Exec(ctx, `ALTER ROLE camera_credential_writer CREATEDB`); err != nil {
		t.Fatal("unsafe role fixture failed")
	}
	assertMaintenanceDenied(t, control.FenceCredentialDatabase(ctx, lease, fenced, p))
	maintenanceCatalog(t, control, ctx, false)
	if _, err = control.pool.Exec(ctx, `ALTER ROLE camera_credential_writer NOCREATEDB`); err != nil {
		t.Fatal("role fixture repair failed")
	}
	_ = lease.Close()
	assertMaintenanceDenied(t, control.FenceCredentialDatabase(ctx, lease, fenced, p))
	maintenanceCatalog(t, control, ctx, false)
	t.Log("CREDENTIAL_MAINTENANCE_PHASE_OK:unsafe-role-rejection")
}

func TestNativeCredentialMaintenanceFenceAndRetry(t *testing.T) {
	owner, writer, budget, control, ctx, p, policy, opened, lease := maintenanceFixture(t)
	if _, err := owner.pool.Exec(ctx, `CREATE TABLE camera.maintenance_sentinel(id integer PRIMARY KEY, value integer NOT NULL);
INSERT INTO camera.maintenance_sentinel VALUES (1,0); GRANT SELECT,UPDATE ON camera.maintenance_sentinel TO camera_credential_writer`); err != nil {
		t.Fatal("noncooperative writer fixture failed")
	}
	if owner.EnrollCredentialEncryptionKey(ctx, credentialOldEnc) != nil {
		t.Fatal("budget sentinel enrollment failed")
	}
	if _, err := owner.pool.Exec(ctx, `UPDATE camera.credential_encryption_budgets SET uses=42 WHERE key_id=$1`, credentialOldEnc); err != nil {
		t.Fatal("budget sentinel failed")
	}
	raw, err := writer.pool.Acquire(ctx)
	if err != nil {
		t.Fatal("noncooperative session unavailable")
	}
	defer raw.Release()
	ownerRaw, err := owner.pool.Acquire(ctx)
	if err != nil {
		t.Fatal("noncooperative privileged target session unavailable")
	}
	defer ownerRaw.Release()
	budgetRaw, err := budget.pool.Acquire(ctx)
	if err != nil {
		t.Fatal("noncooperative budget session unavailable")
	}
	defer budgetRaw.Release()
	// A session under the fixed writer role in ANOTHER database must drain too;
	// unrelated privileged control sessions must survive.
	u, _ := url.Parse(bindingRoleDSN(t, writer, p.host, "disable"))
	u.Path = "/postgres"
	other, err := pgx.Connect(ctx, u.String())
	if err != nil {
		t.Fatal("cross-database role fixture failed")
	}
	defer other.Close(context.Background())
	fenced := maintenanceNextFence(t, lease, opened)
	if _, err = control.pool.Exec(ctx, `ALTER ROLE camera_credential_writer NOLOGIN`); err != nil {
		t.Fatal("partial account fence fixture failed")
	}
	if _, err = raw.Exec(ctx, `UPDATE camera.maintenance_sentinel SET value=1 WHERE id=1`); err != nil {
		t.Fatal("NOLOGIN unexpectedly terminated an existing session")
	}
	t.Log("CREDENTIAL_MAINTENANCE_PHASE_OK:no-login-existing-session")
	if err = control.FenceCredentialDatabase(ctx, lease, fenced, p); err != nil {
		t.Fatal("maintenance database fence failed", err)
	}
	maintenanceCatalog(t, control, ctx, true)
	for _, c := range []*pgx.Conn{raw.Conn(), ownerRaw.Conn(), budgetRaw.Conn(), other} {
		if _, err = c.Exec(ctx, `SELECT 1`); err == nil {
			t.Fatal("noncooperative session survived database drain")
		}
	}
	var sessions int
	if control.pool.QueryRow(ctx, `SELECT count(*) FROM pg_stat_activity WHERE datname='vms_camera_test'
OR usename IN ('camera_credential_writer','camera_credential_budget')`).Scan(&sessions) != nil || sessions != 0 {
		t.Fatal("database drain incomplete")
	}
	for _, dsn := range []string{bindingRoleDSN(t, writer, p.host, "disable"), bindingRoleDSN(t, budget, p.host, "disable"), bindingRoleDSN(t, owner, p.host, "disable")} {
		if c, err := pgx.Connect(ctx, dsn); err == nil {
			_ = c.Close(ctx)
			t.Fatal("closed database authenticated a new session")
		}
	}
	t.Log("CREDENTIAL_MAINTENANCE_PHASE_OK:closed-database-drain")
	// Recreate control connection and exclusive lease after a committed fence.
	// No target connection is needed, and no generation/login/use is reset.
	u, _ = url.Parse(bindingRoleDSN(t, control, p.host, "disable"))
	retry, err := Open(ctx, u.String())
	if err != nil {
		t.Fatal("new control connection unavailable after fence")
	}
	defer retry.Close()
	_ = lease.Close()
	next, err := credentialadmission.AcquireMaintenance(ctx, policy)
	if err != nil {
		t.Fatal("retry lease unavailable")
	}
	defer next.Close()
	if retry.FenceCredentialDatabase(ctx, next, fenced, p) != nil {
		t.Fatal("committed fence retry failed")
	}
	got, err := next.Snapshot()
	if err != nil || !reflect.DeepEqual(got, fenced) {
		t.Fatal("retry changed external authority")
	}
	maintenanceCatalog(t, control, ctx, true)
	// Only the disposable fixture opens again to inspect preserved table rows.
	if _, err = control.pool.Exec(ctx, `ALTER DATABASE vms_camera_test ALLOW_CONNECTIONS true`); err != nil {
		t.Fatal("fixture inspection setup failed")
	}
	u, _ = url.Parse(bindingRoleDSN(t, owner, p.host, "disable"))
	inspect, err := Open(ctx, u.String())
	if err != nil {
		t.Fatal("fixture inspection connection failed")
	}
	defer inspect.Close()
	var value int
	var uses int64
	var enabled bool
	if inspect.pool.QueryRow(ctx, `SELECT value FROM camera.maintenance_sentinel WHERE id=1`).Scan(&value) != nil || value != 1 ||
		inspect.pool.QueryRow(ctx, `SELECT uses,enabled FROM camera.credential_encryption_budgets WHERE key_id=$1`, credentialOldEnc).Scan(&uses, &enabled) != nil || uses != 42 || !enabled {
		t.Fatal("fence changed committed data or budget")
	}
	t.Log("CREDENTIAL_MAINTENANCE_PHASE_OK:interrupted-fence-retry")
}

func TestNativeCredentialMaintenancePreparedTransactions(t *testing.T) {
	owner, _, _, control, ctx, p, _, opened, lease := maintenanceFixture(t)
	var maximum int
	if control.pool.QueryRow(ctx, `SELECT current_setting('max_prepared_transactions')::integer`).Scan(&maximum) != nil || maximum == 0 {
		t.Fatal("native prepared transaction fixture required")
	}
	if _, err := owner.pool.Exec(ctx, `CREATE TABLE camera.maintenance_prepared(id integer)`); err != nil {
		t.Fatal("prepared transaction fixture setup failed")
	}
	conn, err := owner.pool.Acquire(ctx)
	if err != nil {
		t.Fatal("prepared transaction fixture session failed")
	}
	defer conn.Release()
	if _, err = conn.Exec(ctx, `BEGIN; INSERT INTO camera.maintenance_prepared VALUES (1); PREPARE TRANSACTION 'vms-maintenance-synthetic'`); err != nil {
		t.Fatal("native transaction prepare failed")
	}
	pending := true
	t.Cleanup(func() {
		if pending {
			cleanup, cancel := context.WithTimeout(context.Background(), 5*time.Second)
			defer cancel()
			_, _ = owner.pool.Exec(cleanup, `ROLLBACK PREPARED 'vms-maintenance-synthetic'`)
		}
	})
	fenced := maintenanceNextFence(t, lease, opened)
	assertMaintenanceDenied(t, control.FenceCredentialDatabase(ctx, lease, fenced, p))
	maintenanceCatalog(t, control, ctx, false)
	if r, err := lease.Snapshot(); err != nil || !reflect.DeepEqual(r, fenced) {
		t.Fatal("failed fence discarded external FENCED")
	}
	t.Log("CREDENTIAL_MAINTENANCE_PHASE_OK:prepared-transaction-rejection")
	if _, err = conn.Exec(ctx, `ROLLBACK PREPARED 'vms-maintenance-synthetic'`); err != nil {
		t.Fatal("fixture prepared transaction rollback failed")
	}
	pending = false
	if control.FenceCredentialDatabase(ctx, lease, fenced, p) != nil {
		t.Fatal("fence retry after audited fixture rollback failed")
	}
	maintenanceCatalog(t, control, ctx, true)
	t.Log("CREDENTIAL_MAINTENANCE_PHASE_OK:prepared-drain-retry")
}
