//go:build linux

package storage

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"errors"
	"net"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
)

type databaseTLSFixture struct {
	Kind, Host, Database, ServerName, RuntimeIP, MaintenanceIP, OffSourceIP string
	ServerCertificateSHA256, MaintenanceCertificateSHA256                   string
	Port                                                                    uint16
}

func databaseTLSBase(t *testing.T) string {
	t.Helper()
	base := os.Getenv("CAMERA_TLS_TEST_BASE")
	if !filepath.IsAbs(base) || filepath.Clean(base) != base {
		t.Fatal("explicit isolated TLS fixture required")
	}
	return base
}

func databaseTLSRead(t *testing.T, name string) []byte {
	t.Helper()
	path := filepath.Join(databaseTLSBase(t), name)
	info, err := os.Lstat(path)
	if err != nil || !info.Mode().IsRegular() || info.Mode().Perm() != 0400 || info.Size() < 1 || info.Size() > 32768 {
		t.Fatal("private isolated TLS input invalid")
	}
	st, ok := info.Sys().(*syscall.Stat_t)
	if !ok || int(st.Uid) != os.Geteuid() || st.Nlink != 1 {
		t.Fatal("private isolated TLS input owner/link invalid")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal("isolated TLS input unavailable")
	}
	return raw
}

func databaseTLSState(t *testing.T) databaseTLSFixture {
	t.Helper()
	var f databaseTLSFixture
	if json.Unmarshal(databaseTLSRead(t, "endpoint.json"), &f) != nil || f.Kind != "isolated-database-tls" ||
		f.Database != "vms_camera_tls_test" || f.ServerName != "camera-db.vms.internal" || f.Port == 0 {
		t.Fatal("isolated TLS endpoint invalid")
	}
	seen := map[string]bool{}
	for _, ip := range []string{f.Host, f.RuntimeIP, f.MaintenanceIP, f.OffSourceIP} {
		p := net.ParseIP(ip)
		if p == nil || p.To4() == nil || p.String() != ip || p.IsUnspecified() || p.IsMulticast() || seen[ip] {
			t.Fatal("distinct isolated IPs required")
		}
		seen[ip] = true
	}
	return f
}

func databaseTLSNativeSupply(t *testing.T, uid int, names []string) {
	t.Helper()
	if os.Geteuid() != uid || os.Getegid() != uid {
		t.Fatal("native separate TLS probe UID/GID required")
	}
	for _, e := range os.Environ() {
		if strings.HasPrefix(e, "PG") || strings.HasPrefix(e, "CAMERA_TEST_DATABASE_URL") {
			t.Fatal("ambient owner/PG connection forbidden")
		}
	}
	base := databaseTLSBase(t)
	info, err := os.Lstat(base)
	if err != nil || !info.IsDir() || info.Mode().Perm() != 0700 {
		t.Fatal("private TLS directory required")
	}
	st, ok := info.Sys().(*syscall.Stat_t)
	if !ok || int(st.Uid) != uid || int(st.Gid) != uid {
		t.Fatal("separate TLS directory owner required")
	}
	var fs syscall.Statfs_t
	if syscall.Statfs(base, &fs) != nil || fs.Flags&1 == 0 {
		t.Fatal("actual read-only TLS mount required")
	}
	entries, err := os.ReadDir(base)
	if err != nil || len(entries) != len(names) {
		t.Fatal("exact isolated TLS supply required")
	}
	allowed := map[string]bool{}
	for _, name := range names {
		allowed[name] = true
		_ = databaseTLSRead(t, name)
	}
	for _, entry := range entries {
		if !allowed[entry.Name()] {
			t.Fatal("unexpected TLS supply including owner/CA signing key forbidden")
		}
	}
	if file, e := os.OpenFile(filepath.Join(base, "write-probe"), os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600); e == nil {
		_ = file.Close()
		_ = os.Remove(filepath.Join(base, "write-probe"))
		t.Fatal("TLS mount unexpectedly writable")
	} else if !errors.Is(e, syscall.EROFS) {
		t.Fatal("read-only mount rejection required, not a different filesystem error")
	}
}

func databaseTLSEndpoint(t *testing.T, f databaseTLSFixture, ca, name string) *CredentialEndpoint {
	t.Helper()
	p, err := NewCredentialEndpoint(f.Host, f.Port, f.Database, "verify-full", name, databaseTLSRead(t, ca))
	if err != nil {
		t.Fatal("isolated reviewed TLS endpoint unavailable")
	}
	return p
}

func databaseTLSDSN(t *testing.T, role string) string {
	t.Helper()
	return strings.TrimSpace(string(databaseTLSRead(t, role+"-dsn")))
}

func databaseTLSCertificate(t *testing.T, prefix string) tls.Certificate {
	t.Helper()
	pair, err := tls.X509KeyPair(databaseTLSRead(t, prefix+".pem"), databaseTLSRead(t, prefix+".key"))
	if err != nil {
		t.Fatal("isolated client certificate unavailable")
	}
	return pair
}

func databaseTLSIdentity(t *testing.T, ctx context.Context, s *Store, f databaseTLSFixture, role, db, source, dn string) {
	t.Helper()
	c, err := s.pool.Acquire(ctx)
	if err != nil {
		t.Fatal("isolated TLS authenticated connection unavailable")
	}
	defer c.Release()
	var user, session, database, server, client, version, clientDN string
	var port int
	var secure bool
	err = c.QueryRow(ctx, `SELECT current_user,session_user,current_database(),host(inet_server_addr()),inet_server_port(),
host(inet_client_addr()),ssl,version,coalesce(client_dn,'') FROM pg_stat_ssl WHERE pid=pg_backend_pid()`).Scan(
		&user, &session, &database, &server, &port, &client, &secure, &version, &clientDN)
	transport, ok := c.Conn().PgConn().Conn().(*tls.Conn)
	if err != nil || !ok || user != role || session != role || database != db || server != f.Host ||
		port != int(f.Port) || client != source || !secure || (version != "TLSv1.2" && version != "TLSv1.3") || clientDN != dn {
		t.Fatal("actual role/source/TLS/database identity mismatch")
	}
	chain := transport.ConnectionState()
	if len(chain.PeerCertificates) < 1 || digestBytes(chain.PeerCertificates[0].Raw) != f.ServerCertificateSHA256 {
		t.Fatal("exact generated server certificate required")
	}
}

func databaseTLSRaw(t *testing.T, f databaseTLSFixture, role, database, source, cert string, secure bool) *pgx.ConnConfig {
	t.Helper()
	p := databaseTLSEndpoint(t, f, "ca.pem", f.ServerName)
	var cfg *pgx.ConnConfig
	if role == CredentialMaintenanceRole {
		pool, e := maintenanceConfig(databaseTLSDSN(t, role), p, f.MaintenanceIP, databaseTLSCertificate(t, "maintenance"))
		if e != nil {
			t.Fatal("isolated maintenance transport config unavailable")
		}
		cfg = pool.ConnConfig.Copy()
	} else {
		pool, e := p.config(databaseTLSDSN(t, role), role)
		if e != nil {
			t.Fatal("isolated runtime transport config unavailable")
		}
		cfg = pool.ConnConfig.Copy()
	}
	cfg.Database = database
	cfg.ConnectTimeout = 3 * time.Second
	cfg.DialFunc = (&net.Dialer{Timeout: 3 * time.Second, LocalAddr: &net.TCPAddr{IP: net.ParseIP(source)}}).DialContext
	cfg.Fallbacks = nil
	if !secure {
		cfg.TLSConfig = nil
	} else {
		cfg.TLSConfig = cfg.TLSConfig.Clone()
		cfg.TLSConfig.Certificates = nil
		if cert != "" {
			cfg.TLSConfig.Certificates = []tls.Certificate{databaseTLSCertificate(t, cert)}
		}
	}
	return cfg
}

func databaseTLSDenied(t *testing.T, ctx context.Context, cfg *pgx.ConnConfig, code string) {
	t.Helper()
	c, err := pgx.ConnectConfig(ctx, cfg)
	if err == nil {
		_ = c.Close(ctx)
		t.Fatal("forbidden authentication succeeded")
	}
	var pg *pgconn.PgError
	if !errors.As(err, &pg) {
		t.Fatal("exact authentication rejection required; no PostgreSQL error received")
	}
	if pg.Code != code {
		t.Fatalf("expected authentication SQLSTATE %s, received %s", code, pg.Code)
	}
}

func databaseTLSRuntime(t *testing.T, proof func(string)) {
	t.Helper()
	f := databaseTLSState(t)
	ctx, cancel := context.WithTimeout(context.Background(), 40*time.Second)
	defer cancel()
	p := databaseTLSEndpoint(t, f, "ca.pem", f.ServerName)
	for _, role := range []string{"camera_credential_writer", "camera_credential_budget"} {
		s, err := OpenCredentialAdmissionDatabase(ctx, databaseTLSDSN(t, role), p, role)
		if err != nil {
			t.Fatal("actual public runtime TLS opener failed")
		}
		databaseTLSIdentity(t, ctx, s, f, role, f.Database, f.RuntimeIP, "")
		var value string
		var elevated bool
		if s.pool.QueryRow(ctx, "SELECT value FROM tls_probe.sentinel WHERE id=1").Scan(&value) != nil || value != "isolated-only" ||
			s.pool.QueryRow(ctx, `SELECT rolsuper OR rolcreaterole OR rolcreatedb OR rolreplication OR rolbypassrls FROM pg_roles WHERE rolname=current_user`).Scan(&elevated) != nil || elevated {
			s.Close()
			t.Fatal("restricted runtime roles required")
		}
		for _, sql := range []string{"CREATE TABLE tls_probe.denied(id int)", "SET ROLE camera_maintenance"} {
			_, e := s.pool.Exec(ctx, sql)
			var pg *pgconn.PgError
			if !errors.As(e, &pg) || pg.Code != "42501" {
				s.Close()
				t.Fatal("runtime privilege escalation not rejected")
			}
		}
		s.Close()
	}
	proof("runtime-two-role-tls")
	for _, role := range []string{"camera_credential_writer", "camera_credential_budget"} {
		databaseTLSDenied(t, ctx, databaseTLSRaw(t, f, role, "postgres", f.RuntimeIP, "", true), "28000")
		databaseTLSDenied(t, ctx, databaseTLSRaw(t, f, role, f.Database, f.RuntimeIP, "", false), "28000")
		cfg := databaseTLSRaw(t, f, role, f.Database, f.RuntimeIP, "", true)
		cfg.Password = "synthetic-wrong-password"
		databaseTLSDenied(t, ctx, cfg, "28P01")
		for _, bad := range []struct{ ca, name string }{{"ca.pem", "wrong.vms.internal"}, {"wrong-ca.pem", f.ServerName}} {
			endpoint := databaseTLSEndpoint(t, f, bad.ca, bad.name)
			pool, e := endpoint.config(databaseTLSDSN(t, role), role)
			if e != nil {
				t.Fatal("negative TLS config unavailable")
			}
			c, e := pgx.ConnectConfig(ctx, pool.ConnConfig)
			if e == nil {
				_ = c.Close(ctx)
				t.Fatal("wrong CA/hostname unexpectedly authenticated")
			}
			var host x509.HostnameError
			var ca x509.UnknownAuthorityError
			if (bad.ca == "ca.pem" && !errors.As(e, &host)) || (bad.ca != "ca.pem" && !errors.As(e, &ca)) {
				t.Fatal("exact TLS verification failure required")
			}
		}
	}
	proof("runtime-denials")
}

func databaseTLSMaintenance(t *testing.T, proof func(string)) {
	t.Helper()
	f := databaseTLSState(t)
	ctx, cancel := context.WithTimeout(context.Background(), 40*time.Second)
	defer cancel()
	p := databaseTLSEndpoint(t, f, "ca.pem", f.ServerName)
	pair := databaseTLSCertificate(t, "maintenance")
	if len(pair.Certificate) != 1 || digestBytes(pair.Certificate[0]) != f.MaintenanceCertificateSHA256 {
		t.Fatal("exact generated maintenance certificate required")
	}
	for _, db := range []string{f.Database, "postgres"} {
		dsn := databaseTLSDSN(t, CredentialMaintenanceRole)
		if db == "postgres" {
			dsn = strings.Replace(dsn, "/"+f.Database+"?", "/postgres?", 1)
		}
		s, err := OpenCredentialMaintenanceDatabase(ctx, dsn, p, f.MaintenanceIP, pair)
		if err != nil {
			t.Fatal("actual public maintenance mTLS opener failed")
		}
		databaseTLSIdentity(t, ctx, s, f, CredentialMaintenanceRole, db, f.MaintenanceIP, "/CN=camera_maintenance")
		var hba, data string
		var valid bool
		if s.pool.QueryRow(ctx, "SELECT current_setting('hba_file'),current_setting('data_directory')").Scan(&hba, &data) != nil ||
			strings.HasPrefix(hba, data+"/") || hba == data || !filepath.IsAbs(hba) ||
			s.pool.QueryRow(ctx, "SELECT count(*)=6 AND bool_and(error IS NULL) FROM pg_hba_file_rules").Scan(&valid) != nil || !valid {
			s.Close()
			t.Fatal("complete parseable HBA outside PGDATA required")
		}
		s.Close()
	}
	proof("maintenance-mtls-target-control")
	for _, role := range []string{"camera_credential_writer", "camera_credential_budget"} {
		databaseTLSDenied(t, ctx, databaseTLSRaw(t, f, role, f.Database, f.MaintenanceIP, "", true), "28000")
	}
	for _, test := range []struct{ cert, code string }{{"", "28000"}, {"wrong-client", "28P01"}} {
		databaseTLSDenied(t, ctx, databaseTLSRaw(t, f, CredentialMaintenanceRole, f.Database, f.MaintenanceIP, test.cert, true), test.code)
	}
	cfg := databaseTLSRaw(t, f, CredentialMaintenanceRole, f.Database, f.MaintenanceIP, "maintenance", true)
	cfg.Password = "synthetic-wrong-password"
	databaseTLSDenied(t, ctx, cfg, "28P01")
	databaseTLSDenied(t, ctx, databaseTLSRaw(t, f, CredentialMaintenanceRole, f.Database, f.MaintenanceIP, "", false), "28000")
	proof("maintenance-denials")
}

func databaseTLSOffSource(t *testing.T, proof func(string)) {
	t.Helper()
	f := databaseTLSState(t)
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	for _, role := range []string{"camera_credential_writer", "camera_credential_budget", CredentialMaintenanceRole} {
		cert := ""
		if role == CredentialMaintenanceRole {
			cert = "maintenance"
		}
		databaseTLSDenied(t, ctx, databaseTLSRaw(t, f, role, f.Database, f.OffSourceIP, cert, true), "28000")
	}
	proof("offsource-denials")
}

func TestNativeDatabaseTLSRuntime(t *testing.T) {
	if os.Getenv("CAMERA_TLS_TEST_MODE") != "runtime" {
		t.Skip("dedicated isolated TLS runtime required")
	}
	databaseTLSNativeSupply(t, 10001, []string{"endpoint.json", "ca.pem", "wrong-ca.pem", "camera_credential_writer-dsn", "camera_credential_budget-dsn"})
	if os.Getenv("CAMERA_TLS_TEST_RECREATED") == "1" {
		databaseTLSRuntime(t, func(string) {})
		t.Log("DATABASE_TLS_PHASE_OK:runtime-recreated")
		return
	}
	t.Log("DATABASE_TLS_PHASE_OK:runtime-supply-ro-uid")
	databaseTLSRuntime(t, func(p string) { t.Log("DATABASE_TLS_PHASE_OK:" + p) })
}

func TestNativeDatabaseTLSMaintenance(t *testing.T) {
	if os.Getenv("CAMERA_TLS_TEST_MODE") != "maintenance" {
		t.Skip("dedicated isolated TLS maintenance required")
	}
	databaseTLSNativeSupply(t, 10002, []string{"endpoint.json", "ca.pem", "camera_credential_writer-dsn", "camera_credential_budget-dsn",
		"camera_maintenance-dsn", "maintenance.pem", "maintenance.key", "wrong-client.pem", "wrong-client.key"})
	t.Log("DATABASE_TLS_PHASE_OK:maintenance-supply-ro-uid")
	databaseTLSMaintenance(t, func(p string) { t.Log("DATABASE_TLS_PHASE_OK:" + p) })
}

func TestNativeDatabaseTLSOffSource(t *testing.T) {
	if os.Getenv("CAMERA_TLS_TEST_MODE") != "offsource" {
		t.Skip("dedicated isolated TLS offsource probe required")
	}
	databaseTLSNativeSupply(t, 10003, []string{"endpoint.json", "ca.pem", "camera_credential_writer-dsn", "camera_credential_budget-dsn",
		"camera_maintenance-dsn", "maintenance.pem", "maintenance.key"})
	t.Log("DATABASE_TLS_PHASE_OK:offsource-supply-ro-uid")
	databaseTLSOffSource(t, func(p string) { t.Log("DATABASE_TLS_PHASE_OK:" + p) })
}

// Local diagnostics use actual PostgreSQL/TLS on separate loopback addresses.
// They cannot produce the native UID/RO transcript and cannot pass its parser.
func TestDatabaseTLSLocalTransport(t *testing.T) {
	if os.Getenv("CAMERA_TLS_TEST_MODE") != "local-transport" {
		t.Skip("explicit local PostgreSQL TLS diagnostics required")
	}
	proof := func(p string) { t.Log("LOCAL_DATABASE_TLS_PHASE_OK:" + p) }
	databaseTLSRuntime(t, proof)
	databaseTLSMaintenance(t, proof)
	databaseTLSOffSource(t, proof)
}
