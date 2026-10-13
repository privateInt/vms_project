//go:build linux

package storage

import (
	"context"
	"crypto/x509"
	"encoding/json"
	"errors"
	"net"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
)

const registryTLSPrefix = "REGISTRY_TLS_PHASE_OK:"

// The current Store.CheckReady requires schema8. This read-only probe checks the
// legacy image's exact schema7 ledger without invoking current migrations.
func registryTLSSchema7(t *testing.T, ctx context.Context, s *Store) {
	t.Helper()
	migrations, e := loadMigrations(migrationFiles)
	if e != nil || len(migrations) < 7 {
		t.Fatal("schema7 source history required")
	}
	rows, e := s.pool.Query(ctx, "SELECT version,name,checksum FROM camera.schema_migrations ORDER BY version")
	if e != nil {
		t.Fatal("schema7 ledger unavailable")
	}
	defer rows.Close()
	count := 0
	for rows.Next() {
		var version int
		var name, checksum string
		if rows.Scan(&version, &name, &checksum) != nil || count >= 7 || version != count+1 ||
			name != migrations[count].name || checksum != migrations[count].checksum {
			t.Fatal("exact schema7 ledger required")
		}
		count++
	}
	if rows.Err() != nil || count != 7 {
		t.Fatal("complete schema7 ledger required")
	}
	var legacy bool
	if s.pool.QueryRow(ctx, `SELECT to_regprocedure('camera.device_has_active_credentials(text)') IS NULL
 AND to_regclass('camera.credential_versions') IS NULL`).Scan(&legacy) != nil || !legacy {
		t.Fatal("schema8 must not be activated by the TLS rehearsal")
	}
}

func registryTLSFixture(t *testing.T, local bool) databaseTLSFixture {
	t.Helper()
	var f databaseTLSFixture
	if json.Unmarshal(databaseTLSRead(t, "endpoint.json"), &f) != nil || f.Database != "vms_camera" || f.Port == 0 {
		t.Fatal("explicit schema7 registry TLS fixture required")
	}
	if !local && (f.Kind != "isolated-registry-tls-schema7" || f.ServerName != "camera-db.vms.internal") {
		t.Fatal("native registry TLS profile required")
	}
	if local && (f.Kind != "local-registry-tls-diagnostic" || f.ServerName != "localhost") {
		t.Fatal("local diagnostic profile required")
	}
	seen := map[string]bool{}
	for _, raw := range []string{f.Host, f.RuntimeIP, f.MaintenanceIP, f.OffSourceIP} {
		ip := net.ParseIP(raw)
		if ip == nil || ip.To4() == nil || ip.String() != raw || ip.IsUnspecified() || ip.IsMulticast() || (!local && seen[raw]) {
			t.Fatal("explicit registry fixture addresses required")
		}
		seen[raw] = true
	}
	return f
}

func registryTLSDSNPolicy(raw, role, host, base string, port uint16) bool {
	u, e := url.Parse(raw)
	if e != nil || u.Scheme != "postgres" || u.User == nil || u.User.Username() != role ||
		u.Hostname() != host || u.Port() != strconv.Itoa(int(port)) || u.Path != "/vms_camera" ||
		u.Fragment != "" || u.Opaque != "" || !filepath.IsAbs(base) || filepath.Clean(base) != base {
		return false
	}
	pw, ok := u.User.Password()
	if !ok || pw == "" {
		return false
	}
	q, e := url.ParseQuery(u.RawQuery)
	want := map[string]string{"sslmode": "verify-full", "sslrootcert": filepath.Join(base, "ca.pem")}
	if role == "camera_migrator" {
		want["sslcert"], want["sslkey"] = filepath.Join(base, "maintenance.pem"), filepath.Join(base, "maintenance.key")
	} else if role != "camera_runtime" {
		return false
	}
	if e != nil || len(q) != len(want) {
		return false
	}
	for name, value := range want {
		if len(q[name]) != 1 || q[name][0] != value {
			return false
		}
	}
	return true
}

func registryTLSDsn(t *testing.T, name string) string {
	t.Helper()
	return strings.TrimSpace(string(databaseTLSRead(t, name)))
}

func registryTLSRejected(t *testing.T, ctx context.Context, dsn, kind string) {
	t.Helper()
	s, e := Open(ctx, dsn)
	if s != nil {
		s.Close()
	}
	if e == nil {
		t.Fatal("unsafe registry transport unexpectedly admitted")
	}
	var pg *pgconn.PgError
	var unknown x509.UnknownAuthorityError
	var hostname x509.HostnameError
	valid := (kind == "ca" && errors.As(e, &unknown)) || (kind == "hostname" && errors.As(e, &hostname)) ||
		(errors.As(e, &pg) && pg.Code == kind)
	if !valid {
		if pg != nil {
			t.Fatalf("expected authentication cause %s; got SQLSTATE %s", kind, pg.Code)
		}
		t.Fatal("expected TLS/authentication cause required, not an unrelated startup failure")
	}
}

func registryTLSRuntime(t *testing.T, f databaseTLSFixture, prefix string) {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 45*time.Second)
	defer cancel()
	dsn := registryTLSDsn(t, "runtime-dsn")
	if !registryTLSDSNPolicy(dsn, "camera_runtime", f.ServerName, databaseTLSBase(t), f.Port) {
		t.Fatal("explicit verified runtime DSN required")
	}
	s, e := Open(ctx, dsn)
	if e != nil {
		t.Fatal("registry runtime TLS unavailable")
	}
	defer s.Close()
	registryTLSSchema7(t, ctx, s)
	databaseTLSIdentity(t, ctx, s, f, "camera_runtime", "vms_camera", f.RuntimeIP, "")
	var safe bool
	if s.pool.QueryRow(ctx, `SELECT NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls
 AND NOT pg_has_role(current_user,'camera_migrator','MEMBER')
 AND NOT has_schema_privilege(current_user,'camera','CREATE') FROM pg_roles WHERE rolname=current_user`).Scan(&safe) != nil || !safe {
		t.Fatal("registry runtime least privilege required")
	}
	for _, statement := range []string{"CREATE TABLE camera.tls_illegal(id integer)", "SET ROLE camera_migrator"} {
		_, e = s.pool.Exec(ctx, statement)
		var pg *pgconn.PgError
		if !errors.As(e, &pg) || pg.Code != "42501" {
			t.Fatal("runtime escalation must fail with insufficient privilege")
		}
	}
	t.Log(prefix + "runtime-schema7-tls")
	registryTLSRejected(t, ctx, registryTLSDsn(t, "wrong-ca-dsn"), "ca")
	registryTLSRejected(t, ctx, registryTLSDsn(t, "wrong-host-dsn"), "hostname")
	registryTLSRejected(t, ctx, registryTLSDsn(t, "plaintext-dsn"), "28000")
	u, _ := url.Parse(dsn)
	u.User = url.UserPassword("camera_runtime", "synthetic-wrong-password")
	registryTLSRejected(t, ctx, u.String(), "28P01")
	u, _ = url.Parse(dsn)
	u.Path = "/postgres"
	registryTLSRejected(t, ctx, u.String(), "28000")
	t.Log(prefix + "runtime-auth-denials")
}

func registryTLSMigrator(t *testing.T, f databaseTLSFixture, prefix string, local bool) {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 35*time.Second)
	defer cancel()
	dsn := registryTLSDsn(t, "migrator-dsn")
	if !registryTLSDSNPolicy(dsn, "camera_migrator", f.ServerName, databaseTLSBase(t), f.Port) {
		t.Fatal("explicit certificate-authenticated migrator DSN required")
	}
	s, e := Open(ctx, dsn)
	if e != nil {
		t.Fatal("registry migrator mTLS unavailable")
	}
	databaseTLSIdentity(t, ctx, s, f, "camera_migrator", "vms_camera", f.MaintenanceIP, "/CN=camera_maintenance")
	s.Close()
	t.Log(prefix + "migrator-mtls")
	u, _ := url.Parse(dsn)
	q := u.Query()
	q.Del("sslcert")
	q.Del("sslkey")
	u.RawQuery = q.Encode()
	registryTLSRejected(t, ctx, u.String(), "28000")
	u, _ = url.Parse(dsn)
	q = u.Query()
	q.Set("sslcert", filepath.Join(databaseTLSBase(t), "wrong-client.pem"))
	q.Set("sslkey", filepath.Join(databaseTLSBase(t), "wrong-client.key"))
	u.RawQuery = q.Encode()
	registryTLSRejected(t, ctx, u.String(), "28000")
	if !local {
		registryTLSRejected(t, ctx, registryTLSDsn(t, "runtime-dsn"), "28000")
	}
	t.Log(prefix + "migrator-auth-denials")
}

func TestNativeRegistryTLSRuntime(t *testing.T) {
	if os.Getenv("CAMERA_REGISTRY_TLS_MODE") != "runtime" {
		t.Skip("isolated native runtime required")
	}
	databaseTLSNativeSupply(t, 65532, []string{"endpoint.json", "ca.pem", "wrong-ca.pem", "runtime-dsn", "plaintext-dsn", "wrong-ca-dsn", "wrong-host-dsn"})
	status, err := os.ReadFile("/proc/1/status")
	if err != nil {
		t.Fatal("actual API process identity required")
	}
	identityFields := 0
	for _, line := range strings.Split(string(status), "\n") {
		fields := strings.Fields(line)
		if len(fields) > 0 && (fields[0] == "Uid:" || fields[0] == "Gid:") {
			if len(fields) != 5 {
				t.Fatal("actual API process identity invalid")
			}
			for _, id := range fields[1:] {
				if id != "65532" {
					t.Fatal("API process must run as the verified runtime UID/GID")
				}
			}
			identityFields++
		}
	}
	if identityFields != 2 {
		t.Fatal("API UID and GID required")
	}
	registryTLSRuntime(t, registryTLSFixture(t, false), registryTLSPrefix)
}

func TestNativeRegistryTLSMigrator(t *testing.T) {
	if os.Getenv("CAMERA_REGISTRY_TLS_MODE") != "migrator" {
		t.Skip("isolated native migrator required")
	}
	databaseTLSNativeSupply(t, 10002, []string{"endpoint.json", "ca.pem", "maintenance.pem", "maintenance.key", "wrong-client.pem", "wrong-client.key", "migrator-dsn", "runtime-dsn"})
	registryTLSMigrator(t, registryTLSFixture(t, false), registryTLSPrefix, false)
}

func TestNativeRegistryTLSOffSource(t *testing.T) {
	if os.Getenv("CAMERA_REGISTRY_TLS_MODE") != "offsource" {
		t.Skip("isolated native off-source required")
	}
	databaseTLSNativeSupply(t, 10003, []string{"endpoint.json", "ca.pem", "maintenance.pem", "maintenance.key", "migrator-dsn", "runtime-dsn"})
	_ = registryTLSFixture(t, false)
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	for _, name := range []string{"runtime-dsn", "migrator-dsn"} {
		registryTLSRejected(t, ctx, registryTLSDsn(t, name), "28000")
	}
	t.Log(registryTLSPrefix + "offsource-auth-denials")
}

// This separate LOCAL parent cannot produce native acceptance. It has no UID/RO claim.
func TestRegistryTLSLocalTransport(t *testing.T) {
	if os.Getenv("CAMERA_REGISTRY_TLS_MODE") != "local-transport" {
		t.Skip("explicit local TLS diagnostic required")
	}
	f := registryTLSFixture(t, true)
	prefix := "LOCAL_" + registryTLSPrefix
	registryTLSRuntime(t, f, prefix)
	registryTLSMigrator(t, f, prefix, true)
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	for _, name := range []string{"runtime-dsn", "migrator-dsn"} {
		cfg, e := pgx.ParseConfig(registryTLSDsn(t, name))
		if e != nil {
			t.Fatal("local transport config unavailable")
		}
		cfg.DialFunc = (&net.Dialer{Timeout: 3 * time.Second, LocalAddr: &net.TCPAddr{IP: net.ParseIP(f.OffSourceIP)}}).DialContext
		c, e := pgx.ConnectConfig(ctx, cfg)
		if c != nil {
			_ = c.Close(ctx)
		}
		var pg *pgconn.PgError
		if !errors.As(e, &pg) || pg.Code != "28000" {
			t.Fatal("local wrong source authentication must fail")
		}
	}
	t.Log(prefix + "offsource-auth-denials")
}

func TestRegistryTLSInputPolicy(t *testing.T) {
	dsn := "postgres://camera_runtime:synthetic@camera-db.vms.internal:5432/vms_camera?sslmode=verify-full&sslrootcert=%2Fregistry-runtime%2Fca.pem"
	if !registryTLSDSNPolicy(dsn, "camera_runtime", "camera-db.vms.internal", "/registry-runtime", 5432) {
		t.Fatal("explicit runtime profile rejected")
	}
	for _, bad := range []string{strings.Replace(dsn, "verify-full", "prefer", 1), dsn + "&servicefile=/tmp/unsafe",
		dsn + "&sslmode=disable", strings.Replace(dsn, "camera_runtime", "camera_admin", 1),
		strings.Replace(dsn, "vms_camera?", "postgres?", 1), strings.Replace(dsn, "%2Fca.pem", "%2Fwrong.pem", 1)} {
		if registryTLSDSNPolicy(bad, "camera_runtime", "camera-db.vms.internal", "/registry-runtime", 5432) {
			t.Fatal("fallback, ambient file, wrong role or wrong trust input admitted")
		}
	}
}
