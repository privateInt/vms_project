package storage

import (
	"bytes"
	"context"
	"crypto/tls"
	"crypto/x509"
	"net"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"vms.local/platform/camera/internal/credentialadmission"
)

const CredentialMaintenanceRole = "camera_maintenance"

func maintenanceSource(ip string) (net.IP, int) {
	p := net.ParseIP(ip)
	if p == nil || p.String() != ip || p.IsUnspecified() || p.IsMulticast() {
		return nil, 0
	}
	if p.To4() != nil {
		return p, 32
	}
	return p, 128
}

// CredentialMaintenanceHBA builds a COMPLETE, deny-by-default maintenance file,
// not an appendable fragment. Trusted deployment code must install it outside
// DB/key snapshots while durably FENCED and verify actual new authentications.
// This function neither installs/reloads a file nor permits a DB to reopen.
func CredentialMaintenanceHBA(database, sourceIP string) ([]byte, error) {
	_, bits := maintenanceSource(sourceIP)
	if bits == 0 || !admissionDatabaseName.MatchString(database) || database == "postgres" || database == "template0" || database == "template1" {
		return nil, maintenanceDenied()
	}
	// Quote the DB name: names such as all/replication must remain literal names.
	body := "# camera maintenance boundary v1; complete file\nlocal all all reject\n" +
		"hostssl \"" + database + "\",postgres camera_maintenance " + sourceIP + "/" + strconv.Itoa(bits) +
		" scram-sha-256 clientcert=verify-full\nhost all all 0.0.0.0/0 reject\nhost all all ::/0 reject\n"
	return []byte(body), nil
}

func maintenanceConfig(dsn string, p *CredentialEndpoint, sourceIP string, certificate tls.Certificate) (*pgxpool.Config, error) {
	ip, _ := maintenanceSource(sourceIP)
	if p == nil || p.tlsMode != "verify-full" || ip == nil || len(certificate.Certificate) != 1 || certificate.PrivateKey == nil {
		return nil, maintenanceDenied()
	}
	leaf, err := x509.ParseCertificate(certificate.Certificate[0])
	if err != nil || leaf.Subject.CommonName != CredentialMaintenanceRole || leaf.Subject.String() != "CN="+CredentialMaintenanceRole || leaf.IsCA {
		return nil, maintenanceDenied()
	}
	for _, e := range os.Environ() {
		if strings.HasPrefix(e, "PG") {
			return nil, maintenanceDenied()
		}
	}
	u, err := url.Parse(dsn)
	if err != nil || (u.Scheme != "postgres" && u.Scheme != "postgresql") || u.User == nil || u.User.Username() != CredentialMaintenanceRole ||
		u.Opaque != "" || u.Fragment != "" || (u.Path != "/postgres" && u.Path != "/"+p.database) || u.Hostname() != p.host || u.Port() != strconv.Itoa(int(p.port)) {
		return nil, maintenanceDenied()
	}
	password, exists := u.User.Password()
	query, err := url.ParseQuery(u.RawQuery)
	if !exists || password == "" || len(password) > 4096 || err != nil || len(query) != 1 || len(query["sslmode"]) != 1 || query["sslmode"][0] != "verify-full" {
		return nil, maintenanceDenied()
	}
	controlled := url.URL{Scheme: "postgres", User: url.UserPassword(CredentialMaintenanceRole, password), Host: net.JoinHostPort(p.host, strconv.Itoa(int(p.port))), Path: u.Path, RawQuery: "sslmode=disable"}
	cfg, err := pgxpool.ParseConfig(controlled.String())
	if err != nil {
		return nil, maintenanceDenied()
	}
	// Certificates and endpoint CA roots are owned by this config; no ambient
	// libpq files, fallback, DNS, SET ROLE, options or default client certificate.
	pair := certificate
	pair.Certificate = [][]byte{bytes.Clone(certificate.Certificate[0])}
	pair.Leaf = nil
	if len(certificate.OCSPStaple) != 0 || len(certificate.SignedCertificateTimestamps) != 0 {
		return nil, maintenanceDenied()
	}
	cfg.MaxConns, cfg.MinConns = 1, 0
	cfg.ConnConfig.ConnectTimeout = 5 * time.Second
	cfg.ConnConfig.Fallbacks = nil
	cfg.ConnConfig.DialFunc = (&net.Dialer{Timeout: 5 * time.Second, LocalAddr: &net.TCPAddr{IP: ip}}).DialContext
	cfg.ConnConfig.RuntimeParams = map[string]string{"application_name": "vms-camera-maintenance", "timezone": "UTC", "statement_timeout": "15000", "lock_timeout": "5000", "idle_in_transaction_session_timeout": "30000"}
	cfg.ConnConfig.TLSConfig = &tls.Config{MinVersion: tls.VersionTLS12, ServerName: p.serverName, RootCAs: p.roots.Clone(), Certificates: []tls.Certificate{pair}}
	return cfg, nil
}

// OpenCredentialMaintenanceDatabase is a trusted administrative connection,
// not a runtime admission or restore authorization. The reviewed endpoint,
// source address and client key/certificate come from protected deployment
// configuration, never HTTP. Keep the certificate private key immutable.
func OpenCredentialMaintenanceDatabase(ctx context.Context, dsn string, p *CredentialEndpoint, sourceIP string, certificate tls.Certificate) (*Store, error) {
	if ctx == nil || ctx.Err() != nil {
		return nil, maintenanceDenied()
	}
	if _, ok := ctx.Deadline(); !ok {
		return nil, maintenanceDenied()
	}
	cfg, err := maintenanceConfig(dsn, p, sourceIP, certificate)
	if err != nil {
		return nil, maintenanceDenied()
	}
	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		return nil, maintenanceDenied()
	}
	conn, err := pool.Acquire(ctx)
	if err != nil {
		pool.Close()
		return nil, maintenanceDenied()
	}
	local, ok := conn.Conn().PgConn().Conn().LocalAddr().(*net.TCPAddr)
	matched := ok && local.IP.Equal(net.ParseIP(sourceIP)) && p.matchesTransport(conn.Conn().PgConn().Conn())
	conn.Release()
	if !matched {
		pool.Close()
		return nil, maintenanceDenied()
	}
	return &Store{pool: pool, admissionEndpoint: p}, nil
}

// InspectCredentialMaintenanceHBA checks disk bytes, parse errors and this
// actual maintenance session. pg_hba_file_rules describes DISK content, not the
// last loaded rules. This inspection is deliberately not a reopen receipt.
// New positive/negative authentications and old-session drain remain mandatory.
func (s *Store) InspectCredentialMaintenanceHBA(ctx context.Context, lease *credentialadmission.MaintenanceLease, expected credentialadmission.Record, endpoint *CredentialEndpoint, sourceIP string) error {
	return s.inspectCredentialMaintenanceHBA(ctx, lease, expected, endpoint, sourceIP, false)
}

// PREPARED is accepted only by the restore candidate primitive, never by the public fence inspection.
func (s *Store) inspectCredentialMaintenanceHBA(ctx context.Context, lease *credentialadmission.MaintenanceLease, expected credentialadmission.Record, endpoint *CredentialEndpoint, sourceIP string, prepared bool) error {
	if ctx == nil || ctx.Err() != nil || s == nil || s.pool == nil || endpoint == nil || endpoint.tlsMode != "verify-full" ||
		credentialadmission.Validate(expected) != nil || (expected.State != credentialadmission.Fenced && !(prepared && expected.State == credentialadmission.Prepared)) || expected.Binding == nil ||
		expected.Binding.DatabaseName != endpoint.database || expected.Binding.EndpointProfileSHA256 != endpoint.hash {
		return maintenanceDenied()
	}
	if _, ok := ctx.Deadline(); !ok {
		return maintenanceDenied()
	}
	file, err := CredentialMaintenanceHBA(endpoint.database, sourceIP)
	cfg := s.pool.Config().ConnConfig
	if err != nil || cfg.Database != "postgres" || cfg.User != CredentialMaintenanceRole || cfg.Host != endpoint.host || cfg.Port != endpoint.port ||
		len(cfg.Fallbacks) != 0 || s.admissionEndpoint == nil || s.admissionEndpoint.hash != endpoint.hash || confirmMaintenanceFence(lease, expected) != nil {
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
	var allowed bool
	err = conn.QueryRow(ctx, `SELECT session_user=current_user AND session_user='camera_maintenance'
AND pg_catalog.current_database()='postgres' AND r.rolsuper AND r.rolcanlogin
AND pg_catalog.host(pg_catalog.inet_client_addr())=$1 AND ssl.ssl AND ssl.client_dn='/CN=camera_maintenance'
AND ssl.version IN ('TLSv1.2','TLSv1.3')
AND NOT pg_catalog.pg_is_in_recovery()
AND EXISTS (SELECT 1 FROM pg_catalog.pg_database d WHERE d.datname=$2 AND d.datdba=r.oid AND NOT d.datistemplate)
AND (SELECT count(*)=2 AND bool_and(NOT (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls))
FROM pg_catalog.pg_roles WHERE rolname IN ('camera_credential_writer','camera_credential_budget'))
FROM pg_catalog.pg_roles r,pg_catalog.pg_stat_ssl ssl WHERE r.rolname=current_user AND ssl.pid=pg_catalog.pg_backend_pid()`, sourceIP, endpoint.database).Scan(&allowed)
	if err != nil || !allowed {
		return maintenanceDenied()
	}
	var hbaPath, dataPath string
	if conn.QueryRow(ctx, `SELECT pg_catalog.current_setting('hba_file'),pg_catalog.current_setting('data_directory')`).Scan(&hbaPath, &dataPath) != nil ||
		!filepath.IsAbs(hbaPath) || filepath.Clean(hbaPath) != hbaPath || !filepath.IsAbs(dataPath) || filepath.Clean(dataPath) != dataPath ||
		dataPath == "/" || hbaPath == dataPath || strings.HasPrefix(hbaPath, dataPath+"/") {
		return maintenanceDenied()
	}
	var body []byte
	if conn.QueryRow(ctx, `SELECT pg_catalog.pg_read_binary_file(pg_catalog.current_setting('hba_file'),0,$1)`, len(file)+1).Scan(&body) != nil || !bytes.Equal(body, file) {
		return maintenanceDenied()
	}
	var valid bool
	if conn.QueryRow(ctx, `SELECT count(*)=4 AND bool_and(error IS NULL) FROM pg_catalog.pg_hba_file_rules`).Scan(&valid) != nil || !valid ||
		maintenancePreparedClear(ctx, conn, endpoint.database) != nil || confirmMaintenanceFence(lease, expected) != nil {
		return maintenanceDenied()
	}
	return nil
}
