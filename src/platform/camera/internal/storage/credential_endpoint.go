package storage

import (
	"context"
	"crypto/sha256"
	"crypto/tls"
	"crypto/x509"
	"encoding/hex"
	"encoding/json"
	"encoding/pem"
	"net"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"vms.local/platform/camera/internal/credentialcrypto"
)

// CredentialEndpoint is immutable and private. The first admission target uses
// a single canonical IP, with no DNS resolution/failover or Unix sockets.
type CredentialEndpoint struct {
	host, database, tlsMode, serverName, caSHA256, caDERHash, hash string
	port                                                           uint16
	roots                                                          *x509.CertPool
}

func (p CredentialEndpoint) String() string               { return "storage.CredentialEndpoint([redacted])" }
func (p CredentialEndpoint) GoString() string             { return p.String() }
func (p CredentialEndpoint) MarshalJSON() ([]byte, error) { return nil, credentialcrypto.ErrDisclosure }
func (p *CredentialEndpoint) SHA256() string {
	if p == nil {
		return ""
	}
	return p.hash
}

func digestBytes(raw []byte) string { sum := sha256.Sum256(raw); return hex.EncodeToString(sum[:]) }
func tlsIdentity(name string) bool {
	if ip := net.ParseIP(name); ip != nil {
		return ip.String() == name
	}
	if name == "" || len(name) > 253 || strings.ToLower(name) != name {
		return false
	}
	for _, label := range strings.Split(name, ".") {
		if len(label) == 0 || len(label) > 63 || label[0] == '-' || label[len(label)-1] == '-' {
			return false
		}
		for _, c := range label {
			if !(c >= 'a' && c <= 'z' || c >= '0' && c <= '9' || c == '-') {
				return false
			}
		}
	}
	return true
}

// NewCredentialEndpoint derives the CA digest/pool itself from one approved CA
// certificate's exact PEM bytes. No caller-supplied CA hash can stand in for it.
// Explicit disable has empty TLS identity/CA; verify-full requires both.
func NewCredentialEndpoint(host string, port uint16, database, tlsMode, serverName string, caPEM []byte) (*CredentialEndpoint, error) {
	denied := func() (*CredentialEndpoint, error) { return nil, failure("ADMISSION_BINDING_UNAVAILABLE", nil) }
	ip := net.ParseIP(host)
	if ip == nil || ip.String() != host || port == 0 || !admissionDatabaseName.MatchString(database) {
		return denied()
	}
	p := &CredentialEndpoint{host: host, port: port, database: database, tlsMode: tlsMode, serverName: serverName}
	switch tlsMode {
	case "disable":
		if serverName != "" || len(caPEM) != 0 {
			return denied()
		}
	case "verify-full":
		if !tlsIdentity(serverName) || len(caPEM) == 0 || len(caPEM) > 65536 {
			return denied()
		}
		block, rest := pem.Decode(caPEM)
		if block == nil || block.Type != "CERTIFICATE" || len(block.Headers) != 0 || len(strings.TrimSpace(string(rest))) != 0 || !strings.HasPrefix(string(caPEM), "-----BEGIN CERTIFICATE-----") {
			return denied()
		}
		ca, err := x509.ParseCertificate(block.Bytes)
		if err != nil || !ca.IsCA || !ca.BasicConstraintsValid || ca.KeyUsage&x509.KeyUsageCertSign == 0 {
			return denied()
		}
		p.roots = x509.NewCertPool()
		p.roots.AddCert(ca)
		p.caSHA256 = digestBytes(caPEM)
		p.caDERHash = digestBytes(ca.Raw)
	default:
		return denied()
	}
	raw, _ := json.Marshal(struct {
		FormatVersion int    `json:"format_version"`
		Host          string `json:"host"`
		Port          uint16 `json:"port"`
		Database      string `json:"database"`
		TLSMode       string `json:"tls_mode"`
		ServerName    string `json:"tls_server_name"`
		CASHA256      string `json:"ca_sha256"`
		WriterRole    string `json:"writer_role"`
		BudgetRole    string `json:"budget_role"`
	}{1, p.host, p.port, p.database, p.tlsMode, p.serverName, p.caSHA256, "camera_credential_writer", "camera_credential_budget"})
	p.hash = digestBytes(raw)
	return p, nil
}

func (p *CredentialEndpoint) config(dsn, role string) (*pgxpool.Config, error) {
	denied := func() (*pgxpool.Config, error) { return nil, failure("ADMISSION_BINDING_UNAVAILABLE", nil) }
	if p == nil || p.hash == "" || (role != "camera_credential_writer" && role != "camera_credential_budget") {
		return denied()
	}
	// No ambient service files/passfiles/TLS/options are part of this receipt.
	for _, e := range os.Environ() {
		if strings.HasPrefix(e, "PG") {
			return denied()
		}
	}
	u, err := url.Parse(dsn)
	if err != nil || (u.Scheme != "postgres" && u.Scheme != "postgresql") || u.User == nil || u.User.Username() != role || u.Opaque != "" || u.Fragment != "" || u.Path != "/"+p.database || u.Hostname() != p.host || u.Port() != strconv.Itoa(int(p.port)) {
		return denied()
	}
	password, ok := u.User.Password()
	if !ok || password == "" || len(password) > 4096 {
		return denied()
	}
	q, err := url.ParseQuery(u.RawQuery)
	if err != nil || len(q) != 1 || len(q["sslmode"]) != 1 || q["sslmode"][0] != p.tlsMode {
		return denied()
	}
	// Parse a complete, explicit plaintext bootstrap config, so pgx never reads
	// default CA/client cert files. Attach only this immutable policy's TLS pool.
	controlled := url.URL{Scheme: "postgres", User: url.UserPassword(role, password), Host: net.JoinHostPort(p.host, strconv.Itoa(int(p.port))), Path: "/" + p.database, RawQuery: "sslmode=disable"}
	cfg, err := pgxpool.ParseConfig(controlled.String())
	if err != nil {
		return denied()
	}
	cfg.MaxConns = 4
	cfg.MinConns = 0
	cfg.ConnConfig.ConnectTimeout = 5 * time.Second
	cfg.ConnConfig.DialFunc = (&net.Dialer{Timeout: 5 * time.Second}).DialContext
	cfg.ConnConfig.Fallbacks = nil
	cfg.ConnConfig.RuntimeParams = map[string]string{"application_name": "vms-camera-admission-storage", "timezone": "UTC", "statement_timeout": "15000", "lock_timeout": "5000", "idle_in_transaction_session_timeout": "30000"}
	if p.tlsMode == "verify-full" {
		cfg.ConnConfig.TLSConfig = &tls.Config{MinVersion: tls.VersionTLS12, ServerName: p.serverName, RootCAs: p.roots.Clone()}
	}
	return cfg, nil
}

// OpenCredentialAdmissionDatabase checks one explicitly approved connection;
// it never runs DDL or writes a marker/budget. Legacy Open creates no receipt.
func OpenCredentialAdmissionDatabase(ctx context.Context, dsn string, p *CredentialEndpoint, role string) (*Store, error) {
	cfg, err := p.config(dsn, role)
	if err != nil {
		return nil, err
	}
	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		return nil, failure("ADMISSION_BINDING_UNAVAILABLE", nil)
	}
	s := &Store{pool: pool, admissionEndpoint: p}
	check, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	conn, err := pool.Acquire(check)
	if err != nil {
		pool.Close()
		return nil, failure("ADMISSION_BINDING_UNAVAILABLE", nil)
	}
	matched := p.matchesTransport(conn.Conn().PgConn().Conn())
	conn.Release()
	if !matched {
		pool.Close()
		return nil, failure("ADMISSION_BINDING_UNAVAILABLE", nil)
	}
	return s, nil
}

func (p *CredentialEndpoint) matchesTransport(conn net.Conn) bool {
	if p == nil || conn == nil {
		return false
	}
	remote, ok := conn.RemoteAddr().(*net.TCPAddr)
	if !ok || remote.Port != int(p.port) || !remote.IP.Equal(net.ParseIP(p.host)) {
		return false
	}
	secure, isTLS := conn.(*tls.Conn)
	if p.tlsMode == "disable" {
		return !isTLS
	}
	if !isTLS {
		return false
	}
	state := secure.ConnectionState()
	if !state.HandshakeComplete || state.Version < tls.VersionTLS12 || state.ServerName != p.serverName || len(state.VerifiedChains) == 0 {
		return false
	}
	for _, chain := range state.VerifiedChains {
		if len(chain) > 0 && digestBytes(chain[len(chain)-1].Raw) == p.caDERHash {
			return true
		}
	}
	return false
}
