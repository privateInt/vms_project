//go:build linux

package storage

import (
	"bytes"
	"context"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"net/url"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"syscall"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgxpool"
	"vms.local/platform/camera/internal/credentialadmission"
)

type boundaryState struct {
	Host                                                        string
	Port                                                        uint16
	InitialUser, InitialPassword, MaintenancePassword, SourceIP string
	Policy                                                      credentialadmission.Policy
	Record                                                      credentialadmission.Record
}

func boundaryBase(t *testing.T) string {
	t.Helper()
	base := os.Getenv("CAMERA_BOUNDARY_BASE")
	if !filepath.IsAbs(base) || filepath.Clean(base) != base || os.Getenv("CAMERA_TEST_ALLOW_SCHEMA_RESET") != "1" {
		t.Fatal("explicit disposable boundary fixture required")
	}
	return base
}
func boundaryPhase(t *testing.T, phase string) {
	t.Helper()
	prefix := "CREDENTIAL_BOUNDARY_PHASE_OK:"
	if os.Getenv("CAMERA_BOUNDARY_LOCAL_ONLY") == "1" {
		prefix = "LOCAL_BOUNDARY_PHASE_OK:"
	}
	t.Log(prefix + phase)
}
func boundarySave(t *testing.T, path string, value any, mode os.FileMode) {
	t.Helper()
	body, err := json.Marshal(value)
	if err != nil || os.WriteFile(path, body, mode) != nil || os.Chmod(path, mode) != nil {
		t.Fatal("synthetic fixture save failed")
	}
}
func boundaryRead(t *testing.T, probe bool) boundaryState {
	t.Helper()
	name := "state.json"
	if probe {
		name = "probe/state.json"
	}
	body, err := os.ReadFile(filepath.Join(boundaryBase(t), name))
	var value boundaryState
	if err != nil || json.Unmarshal(body, &value) != nil || value.Host == "" || value.Record.Binding == nil {
		t.Fatal("private fixture state unavailable")
	}
	return value
}
func boundaryEndpoint(t *testing.T, s boundaryState) *CredentialEndpoint {
	t.Helper()
	body, err := os.ReadFile(filepath.Join(boundaryBase(t), "tls/ca.crt"))
	p, e := NewCredentialEndpoint(s.Host, s.Port, "vms_camera_test", "verify-full", "boundary-db", body)
	if err != nil || e != nil {
		t.Fatal("synthetic TLS endpoint unavailable")
	}
	return p
}
func boundaryCertificate(t *testing.T, probe bool, kind string) tls.Certificate {
	t.Helper()
	dir := "tls"
	if probe {
		dir = "probe"
	}
	pair, err := tls.LoadX509KeyPair(filepath.Join(boundaryBase(t), dir, kind+".crt"), filepath.Join(boundaryBase(t), dir, kind+".key"))
	if err != nil {
		t.Fatal("private synthetic client certificate unavailable")
	}
	return pair
}
func boundaryDSN(s boundaryState, role, database string) string {
	password := s.MaintenancePassword
	if role == s.InitialUser {
		password = s.InitialPassword
	}
	u := url.URL{Scheme: "postgres", User: url.UserPassword(role, password), Host: net.JoinHostPort(s.Host, fmt.Sprint(s.Port)), Path: "/" + database, RawQuery: "sslmode=verify-full"}
	return u.String()
}
func boundaryConfig(t *testing.T, s boundaryState, role, db, source, cert string, probe, secure bool) *pgx.ConnConfig {
	t.Helper()
	u, _ := url.Parse(boundaryDSN(s, role, db))
	u.RawQuery = "sslmode=disable"
	cfg, err := pgx.ParseConfig(u.String())
	if err != nil {
		t.Fatal("synthetic connection config unavailable")
	}
	cfg.Fallbacks = nil
	cfg.ConnectTimeout = 3 * time.Second
	cfg.RuntimeParams = map[string]string{"application_name": "vms-isolated-boundary", "statement_timeout": "10000"}
	dialer := &net.Dialer{Timeout: 3 * time.Second}
	if source != "" {
		dialer.LocalAddr = &net.TCPAddr{IP: net.ParseIP(source)}
	}
	cfg.DialFunc = dialer.DialContext
	if secure {
		ca, err := os.ReadFile(filepath.Join(boundaryBase(t), "tls/ca.crt"))
		roots := x509.NewCertPool()
		if err != nil || !roots.AppendCertsFromPEM(ca) {
			t.Fatal("synthetic CA unavailable")
		}
		cfg.TLSConfig = &tls.Config{MinVersion: tls.VersionTLS12, ServerName: "boundary-db", RootCAs: roots}
		if cert != "" {
			cfg.TLSConfig.Certificates = []tls.Certificate{boundaryCertificate(t, probe, cert)}
		}
	}
	return cfg
}
func boundaryStore(t *testing.T, ctx context.Context, s boundaryState, role, db string) *Store {
	t.Helper()
	cfg := boundaryConfig(t, s, role, db, "", "client", false, true)
	poolcfg, err := pgxpool.ParseConfig(boundaryDSN(s, role, db))
	if err != nil {
		t.Fatal("fixture pool config unavailable")
	}
	poolcfg.ConnConfig = cfg
	poolcfg.MaxConns = 1
	pool, err := pgxpool.NewWithConfig(ctx, poolcfg)
	if err != nil || pool.Ping(ctx) != nil {
		if pool != nil {
			pool.Close()
		}
		t.Fatal("synthetic authenticated owner unavailable")
	}
	return &Store{pool: pool}
}
func boundaryMaintenance(t *testing.T, ctx context.Context, s boundaryState) *Store {
	t.Helper()
	store, err := OpenCredentialMaintenanceDatabase(ctx, boundaryDSN(s, CredentialMaintenanceRole, "postgres"), boundaryEndpoint(t, s), s.SourceIP, boundaryCertificate(t, false, "client"))
	if err != nil {
		t.Fatal("maintenance mTLS control unavailable", err)
	}
	return store
}
func boundaryLease(t *testing.T, ctx context.Context, s boundaryState) *credentialadmission.MaintenanceLease {
	t.Helper()
	l, err := credentialadmission.AcquireMaintenance(ctx, s.Policy)
	if err != nil {
		t.Fatal("exclusive synthetic authority unavailable")
	}
	got, err := l.Snapshot()
	if err != nil || !reflect.DeepEqual(got, s.Record) {
		_ = l.Close()
		t.Fatal("pinned synthetic authority changed")
	}
	return l
}
func boundaryDenied(t *testing.T, ctx context.Context, cfg *pgx.ConnConfig, expected ...string) {
	t.Helper()
	c, err := pgx.ConnectConfig(ctx, cfg)
	if err == nil {
		_ = c.Close(ctx)
		t.Fatal("forbidden new authentication succeeded")
	}
	code := "28000"
	if len(expected) == 1 {
		code = expected[0]
	}
	var pg *pgconn.PgError
	if !errors.As(err, &pg) || pg.Code != code {
		t.Fatal("expected exact authentication rejection, not another failure")
	}
}
func boundaryAtomicHBA(t *testing.T, base string, body []byte) {
	t.Helper()
	dir := filepath.Join(base, "hba")
	tmp := filepath.Join(dir, "candidate.conf")
	f, err := os.OpenFile(tmp, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0644)
	if err != nil {
		t.Fatal("fresh isolated HBA candidate required")
	}
	_, e := f.Write(body)
	e2 := f.Sync()
	e3 := f.Close()
	if e != nil || e2 != nil || e3 != nil || os.Rename(tmp, filepath.Join(dir, "pg_hba.conf")) != nil {
		t.Fatal("isolated HBA commit failed")
	}
	parent, err := os.Open(dir)
	if err != nil {
		t.Fatal("isolated HBA directory unavailable")
	}
	defer parent.Close()
	if parent.Sync() != nil {
		t.Fatal("isolated HBA directory fsync failed")
	}
}

func TestNativeCredentialMaintenanceBoundaryFixture(t *testing.T) {
	if os.Getenv("CAMERA_BOUNDARY_PHASE") != "prepare" {
		t.Skip("dedicated boundary fixture preparation required")
	}
	if os.Geteuid() != 0 {
		t.Fatal("synthetic fixture owner required")
	}
	// Explicit public traversal modes must work under a restrictive owner umask.
	mask := syscall.Umask(0077)
	defer syscall.Umask(mask)
	base := boundaryBase(t)
	if os.Mkdir(base, 0755) != nil || os.Chmod(base, 0755) != nil {
		t.Fatal("fresh fixture required")
	}
	for _, dir := range []string{"tls", "probe", "hba", "authority"} {
		if os.Mkdir(filepath.Join(base, dir), 0755) != nil || os.Chmod(filepath.Join(base, dir), 0755) != nil {
			t.Fatal("fixture directory creation failed")
		}
	}
	files := maintenanceCertificates(t)
	for name, body := range files {
		mode := os.FileMode(0644)
		if filepath.Ext(name) == ".key" {
			mode = 0600
		}
		if os.WriteFile(filepath.Join(base, "tls", name), body, mode) != nil || os.Chmod(filepath.Join(base, "tls", name), mode) != nil {
			t.Fatal("synthetic certificate save failed")
		}
	}
	uid := 10001
	if os.Getenv("CAMERA_BOUNDARY_LOCAL_ONLY") == "1" {
		uid = 0
	}
	for _, name := range []string{"client.crt", "client.key"} {
		p := filepath.Join(base, "probe", name)
		if os.WriteFile(p, files[name], 0400) != nil || os.Chown(p, uid, uid) != nil || os.Chmod(p, 0400) != nil {
			t.Fatal("synthetic probe certificate save failed")
		}
	}
	// Keep the directory private to the owner until seed writes the probe state.
	if os.Chmod(filepath.Join(base, "probe"), 0700) != nil || os.Chmod(filepath.Join(base, "authority"), 0750) != nil {
		t.Fatal("fixture ownership failed")
	}
	// Bootstrap ONLY: Unix trust permits postgres image initialization. The
	// final complete file rejects local sockets and every unapproved network.
	initial := []byte("local all all trust\nhost all all 0.0.0.0/0 scram-sha-256\nhost all all ::/0 scram-sha-256\n")
	if os.WriteFile(filepath.Join(base, "hba/pg_hba.conf"), initial, 0644) != nil || os.Chmod(filepath.Join(base, "hba/pg_hba.conf"), 0644) != nil {
		t.Fatal("bootstrap fixture HBA save failed")
	}
	boundaryPhase(t, "prepare")
}

func TestNativeCredentialMaintenanceBoundaryOwner(t *testing.T) {
	phase := os.Getenv("CAMERA_BOUNDARY_PHASE")
	if phase != "seed" && phase != "fence" && phase != "reopen" && phase != "retry" {
		t.Skip("dedicated isolated boundary owner phase required")
	}
	if os.Geteuid() != 0 || os.Getenv("CAMERA_TEST_ENGINE") == "pglite" {
		t.Fatal("native privileged fixture required")
	}
	base := boundaryBase(t)
	ctx, cancel := context.WithTimeout(context.Background(), 40*time.Second)
	defer cancel()
	if phase == "seed" {
		u, err := url.Parse(os.Getenv("CAMERA_TEST_DATABASE_URL"))
		if err != nil || u.Path != "/vms_camera_test" || u.User == nil {
			t.Fatal("disposable DB required")
		}
		ips, err := net.LookupHost(u.Hostname())
		if err != nil || len(ips) != 1 {
			t.Fatal("single fixture endpoint required")
		}
		port := u.Port()
		n := uint16(5432)
		if port != "" {
			var number int
			if _, err := fmt.Sscan(port, &number); err != nil || number < 1 || number > 65535 {
				t.Fatal("fixture port invalid")
			}
			n = uint16(number)
		}
		s := boundaryState{Host: net.ParseIP(ips[0]).String(), Port: n, InitialUser: u.User.Username()}
		s.InitialPassword, _ = u.User.Password()
		owner := boundaryStore(t, ctx, s, s.InitialUser, "vms_camera_test")
		defer owner.Close()
		var random [24]byte
		if _, err := rand.Read(random[:]); err != nil {
			t.Fatal("synthetic password generation failed")
		}
		s.MaintenancePassword = hex.EncodeToString(random[:])
		if _, err := owner.MigrateCredentialAdmission(ctx); err != nil {
			t.Fatal("fixture schema9 migration failed")
		}
		if _, err := owner.pool.Exec(ctx, "CREATE ROLE camera_maintenance LOGIN SUPERUSER PASSWORD '"+s.MaintenancePassword+"'; CREATE ROLE camera_credential_writer LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD '"+s.MaintenancePassword+"'; CREATE ROLE camera_credential_budget LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD '"+s.MaintenancePassword+"'; ALTER DATABASE vms_camera_test OWNER TO camera_maintenance"); err != nil {
			t.Fatal("fresh synthetic roles required")
		}
		if owner.pool.QueryRow(ctx, "SELECT pg_catalog.host(pg_catalog.inet_client_addr())").Scan(&s.SourceIP) != nil {
			t.Fatal("fixture maintenance source unavailable")
		}
		if owner.EnrollCredentialEncryptionKey(ctx, credentialOldEnc) != nil {
			t.Fatal("budget sentinel setup failed")
		}
		if _, err := owner.pool.Exec(ctx, "UPDATE camera.credential_encryption_budgets SET uses=42 WHERE key_id=$1", credentialOldEnc); err != nil {
			t.Fatal("budget sentinel setup failed")
		}
		p := boundaryEndpoint(t, s)
		db := admissionDatabaseFixture(t)
		putAdmissionMarker(t, owner, ctx, db)
		r, _ := credentialadmission.NewFenced(db.DeploymentID, db.OperationID, "2026-10-07T00:00:00Z")
		s.Policy = credentialadmission.Policy{Directory: filepath.Join(base, "authority"), OwnerUID: os.Geteuid(), RuntimeGID: os.Getegid()}
		if os.Getenv("CAMERA_BOUNDARY_RESUME_ONLY") == "1" && os.Getenv("CAMERA_BOUNDARY_LOCAL_ONLY") != "1" {
			s.Policy.RuntimeGID = 10001
			if os.Chown(s.Policy.Directory, 0, 10001) != nil {
				t.Fatal("runtime authority group unavailable")
			}
		}
		s.Policy.LockIdentity, err = credentialadmission.Bootstrap(ctx, s.Policy, r)
		if err != nil {
			t.Fatal("fixture authority bootstrap failed")
		}
		l, err := credentialadmission.AcquireMaintenance(ctx, s.Policy)
		if err != nil {
			t.Fatal("fixture authority unavailable")
		}
		defer l.Close()
		b := credentialadmission.Binding{DatabaseID: db.DatabaseID, DatabaseName: db.DatabaseName, SchemaVersion: 9, MigrationSetSHA256: db.MigrationSetSHA256, EndpointProfileSHA256: p.hash, KeyBundleSHA256: digestBytes([]byte("synthetic binding; no loaded business keys")), ActiveEncryptionKeyID: credentialOldEnc, ActiveIdempotencyKeyID: credentialOldMac, WriterRole: "camera_credential_writer", BudgetRole: "camera_credential_budget"}
		if os.Getenv("CAMERA_BOUNDARY_RESTORE_ONLY") == "1" {
			raw, e := os.ReadFile(filepath.Join(base, "keys/previous/key-bundle.json"))
			if e != nil {
				t.Fatal("protected restore fixture absent")
			}
			b.KeyBundleSHA256 = digestBytes(raw)
		}
		prepared, e := credentialadmission.NextPrepare(r, b, "2026-10-07T00:00:00Z")
		if e != nil || l.Commit(r, prepared) != nil {
			t.Fatal("fixture prepare failed")
		}
		s.Record, _ = credentialadmission.NextOpen(prepared, "2026-10-07T00:00:00Z")
		if l.Commit(prepared, s.Record) != nil {
			t.Fatal("fixture OPEN failed")
		}
		boundarySave(t, filepath.Join(base, "state.json"), s, 0600)
		probe := filepath.Join(base, "probe/state.json")
		boundarySave(t, probe, s, 0400)
		uid := 10001
		if os.Getenv("CAMERA_BOUNDARY_LOCAL_ONLY") == "1" {
			uid = 0
		}
		if os.Chown(probe, uid, uid) != nil || os.Chmod(filepath.Join(base, "probe"), 0500) != nil || os.Chown(filepath.Join(base, "probe"), uid, uid) != nil {
			t.Fatal("probe private state ownership failed")
		}
		maint := boundaryMaintenance(t, ctx, s)
		maint.Close()
		boundaryPhase(t, "seed")
		return
	}
	s := boundaryRead(t, false)
	p := boundaryEndpoint(t, s)
	l := boundaryLease(t, ctx, s)
	defer l.Close()
	maint := boundaryMaintenance(t, ctx, s)
	defer maint.Close()
	if phase == "fence" {
		next, e := credentialadmission.NextFence(s.Record, "55555555-5555-4555-8555-555555555555", "2026-10-07T01:00:00Z")
		if e != nil || l.Commit(s.Record, next) != nil {
			t.Fatal("durable external fence failed")
		}
		s.Record = next
		if maint.FenceCredentialDatabase(ctx, l, s.Record, p) != nil {
			t.Fatal("actual DB fence failed")
		}
		body, e := CredentialMaintenanceHBA(p.database, s.SourceIP)
		if e != nil {
			t.Fatal("maintenance policy failed")
		}
		boundaryAtomicHBA(t, base, body)
		var reloaded bool
		if maint.pool.QueryRow(ctx, "SELECT pg_catalog.pg_reload_conf()").Scan(&reloaded) != nil || !reloaded {
			t.Fatal("HBA reload signal failed")
		}
		// A reload signal/disk view alone is not an activation receipt: wait for a
		// fresh correct-password connection WITHOUT the required cert to be rejected.
		for {
			c, err := pgx.ConnectConfig(ctx, boundaryConfig(t, s, CredentialMaintenanceRole, "postgres", s.SourceIP, "", false, true))
			if err != nil {
				var pg *pgconn.PgError
				if errors.As(err, &pg) && pg.Code == "28000" {
					break
				}
				t.Fatal("unexpected HBA activation probe failure")
			}
			_ = c.Close(ctx)
			select {
			case <-ctx.Done():
				t.Fatal("HBA activation did not reject missing certificate")
			case <-time.After(20 * time.Millisecond):
			}
		}
		fresh := boundaryMaintenance(t, ctx, s)
		defer fresh.Close()
		if fresh.InspectCredentialMaintenanceHBA(ctx, l, s.Record, p, s.SourceIP) != nil {
			t.Fatal("disk/session HBA inspection failed")
		}
		// Disk tampering must fail inspection even while the already loaded
		// policy still rejects off-source clients. Never reload the bad file.
		boundaryAtomicHBA(t, base, append(bytes.Clone(body), []byte("host all all 0.0.0.0/0 trust\n")...))
		assertMaintenanceDenied(t, fresh.InspectCredentialMaintenanceHBA(ctx, l, s.Record, p, s.SourceIP))
		boundaryAtomicHBA(t, base, body)
		if fresh.InspectCredentialMaintenanceHBA(ctx, l, s.Record, p, s.SourceIP) != nil {
			t.Fatal("restored exact disk policy unavailable")
		}
		boundaryDenied(t, ctx, boundaryConfig(t, s, s.InitialUser, "postgres", s.SourceIP, "client", false, true))
		boundaryDenied(t, ctx, boundaryConfig(t, s, CredentialMaintenanceRole, "postgres", s.SourceIP, "wrong-client", false, true), "28P01")
		boundaryDenied(t, ctx, boundaryConfig(t, s, CredentialMaintenanceRole, "postgres", s.SourceIP, "client", false, false))
		// The unmodified Docker acceptance ALWAYS probes the isolated socket.
		// UID0-only local namespaces may prohibit Unix bind; their diagnostic
		// phases have a different prefix and cannot pass the native runner.
		if os.Getenv("CAMERA_BOUNDARY_LOCAL_ONLY") != "1" {
			socket := os.Getenv("CAMERA_BOUNDARY_SOCKET")
			if socket == "" {
				t.Fatal("isolated Unix socket probe required")
			}
			cfg := boundaryConfig(t, s, s.InitialUser, "postgres", "", "", false, false)
			cfg.Host = socket
			boundaryDenied(t, ctx, cfg)
		}
		boundarySave(t, filepath.Join(base, "state.json"), s, 0600)
		boundaryPhase(t, "fence")
		return
	}
	if s.Record.State != credentialadmission.Fenced || maint.InspectCredentialMaintenanceHBA(ctx, l, s.Record, p, s.SourceIP) != nil {
		t.Fatal("pinned FENCED maintenance boundary unavailable")
	}
	if phase == "reopen" {
		// Test-only reconnect: no product reopen API is implemented. Only the native
		// runner may reach this phase after its actual off-source rejection proof.
		if _, err := maint.pool.Exec(ctx, "ALTER DATABASE vms_camera_test ALLOW_CONNECTIONS true"); err != nil {
			t.Fatal("isolated maintenance reconnect failed")
		}
		target, err := OpenCredentialMaintenanceDatabase(ctx, boundaryDSN(s, CredentialMaintenanceRole, "vms_camera_test"), p, s.SourceIP, boundaryCertificate(t, false, "client"))
		if err != nil {
			t.Fatal("authorized fresh mTLS target authentication failed")
		}
		defer target.Close()
		if _, err := target.pool.Exec(ctx, "CREATE TABLE camera.boundary_sentinel(id integer PRIMARY KEY); INSERT INTO camera.boundary_sentinel VALUES(1)"); err != nil {
			t.Fatal("maintenance target write failed")
		}
		boundaryPhase(t, "reopen")
		return
	}
	target, err := OpenCredentialMaintenanceDatabase(ctx, boundaryDSN(s, CredentialMaintenanceRole, "vms_camera_test"), p, s.SourceIP, boundaryCertificate(t, false, "client"))
	if err != nil {
		t.Fatal("recreated maintenance connection failed")
	}
	var count int
	var uses int64
	if target.pool.QueryRow(ctx, "SELECT count(*) FROM camera.boundary_sentinel").Scan(&count) != nil || count != 1 || target.pool.QueryRow(ctx, "SELECT uses FROM camera.credential_encryption_budgets WHERE key_id=$1", credentialOldEnc).Scan(&uses) != nil || uses != 42 {
		target.Close()
		t.Fatal("retry changed committed sentinel/budget")
	}
	target.Close()
	if maint.FenceCredentialDatabase(ctx, l, s.Record, p) != nil {
		t.Fatal("final isolated DB fence failed")
	}
	if got, e := l.Snapshot(); e != nil || !reflect.DeepEqual(got, s.Record) {
		t.Fatal("retry changed external authority")
	}
	boundaryPhase(t, "retry")
}

func TestNativeCredentialMaintenanceBoundaryClient(t *testing.T) {
	phase := os.Getenv("CAMERA_BOUNDARY_PHASE")
	if phase != "client" && phase != "client-local" {
		t.Skip("native separate-source boundary client required")
	}
	if phase == "client" {
		if os.Geteuid() != 10001 || os.Getegid() != 10001 {
			t.Fatal("separate runtime UID required")
		}
		status, err := os.ReadFile("/proc/self/status")
		if err != nil {
			t.Fatal("runtime capability status unavailable")
		}
		// Reuse the tested exact CapEff parser; all effective capabilities must be 0.
		var found bool
		for _, line := range strings.Split(string(status), "\n") {
			if strings.HasPrefix(line, "CapEff:") {
				found = true
				if strings.TrimSpace(strings.TrimPrefix(line, "CapEff:")) != "0000000000000000" {
					t.Fatal("runtime capabilities must be zero")
				}
			}
		}
		if !found {
			t.Fatal("runtime capabilities missing")
		}
		var mount syscall.Statfs_t
		if syscall.Statfs(boundaryBase(t), &mount) != nil || mount.Flags&1 == 0 {
			t.Fatal("actual read-only probe mount required")
		}
	} else if os.Getenv("CAMERA_BOUNDARY_LOCAL_ONLY") != "1" {
		t.Fatal("explicit local diagnostic fixture required")
	}
	mode := os.Getenv("CAMERA_BOUNDARY_PROBE")
	if mode != "before" && mode != "closed" && mode != "open" {
		t.Fatal("boundary probe selector invalid")
	}
	s := boundaryRead(t, true)
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	source := ""
	if phase == "client-local" {
		source = "127.0.0.2"
	}
	for _, db := range []string{"postgres", "vms_camera_test"} {
		cfg := boundaryConfig(t, s, CredentialMaintenanceRole, db, source, "client", true, true)
		if mode == "before" {
			c, err := pgx.ConnectConfig(ctx, cfg)
			if err != nil {
				t.Fatal("pre-fence valid credential/TLS probe failed")
			}
			var address string
			if c.QueryRow(ctx, "SELECT pg_catalog.host(pg_catalog.inet_client_addr())").Scan(&address) != nil || address == s.SourceIP {
				_ = c.Close(ctx)
				t.Fatal("actual probe source must differ from maintenance")
			}
			_ = c.Close(ctx)
		} else {
			boundaryDenied(t, ctx, cfg)
		}
	}
	boundaryPhase(t, "client-"+mode)
}
