package storage

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"encoding/pem"
	"fmt"
	"math/big"
	"net"
	"strings"
	"testing"
	"time"

	"vms.local/platform/camera/internal/credentialadmission"
)

func endpointCertificates(t *testing.T) (caPEM, serverPEM, keyPEM []byte) {
	t.Helper()
	now := time.Now()
	caKey, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	ca := &x509.Certificate{SerialNumber: big.NewInt(1), NotBefore: now.Add(-time.Minute), NotAfter: now.Add(time.Hour), IsCA: true, BasicConstraintsValid: true, KeyUsage: x509.KeyUsageCertSign | x509.KeyUsageDigitalSignature}
	caRaw, err := x509.CreateCertificate(rand.Reader, ca, ca, &caKey.PublicKey, caKey)
	if err != nil {
		t.Fatal(err)
	}
	serverKey, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	server := &x509.Certificate{SerialNumber: big.NewInt(2), NotBefore: now.Add(-time.Minute), NotAfter: now.Add(time.Hour), DNSNames: []string{"admission-db"}, IPAddresses: []net.IP{net.ParseIP("127.0.0.1")}, KeyUsage: x509.KeyUsageDigitalSignature, ExtKeyUsage: []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth}, BasicConstraintsValid: true}
	serverRaw, err := x509.CreateCertificate(rand.Reader, server, ca, &serverKey.PublicKey, caKey)
	if err != nil {
		t.Fatal(err)
	}
	keyRaw, err := x509.MarshalPKCS8PrivateKey(serverKey)
	if err != nil {
		t.Fatal(err)
	}
	return pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: caRaw}), pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: serverRaw}), pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: keyRaw})
}

func TestCredentialEndpointCanonicalHashAndPrivacy(t *testing.T) {
	p, err := NewCredentialEndpoint("127.0.0.1", 5432, "vms_camera_test", "disable", "", nil)
	if err != nil {
		t.Fatal(err)
	}
	literal := `{"format_version":1,"host":"127.0.0.1","port":5432,"database":"vms_camera_test","tls_mode":"disable","tls_server_name":"","ca_sha256":"","writer_role":"camera_credential_writer","budget_role":"camera_credential_budget"}`
	if p.SHA256() != digestBytes([]byte(literal)) {
		t.Fatal("canonical hash changed")
	}
	ca, _, _ := endpointCertificates(t)
	secure, err := NewCredentialEndpoint("127.0.0.1", 5432, "vms_camera_test", "verify-full", "admission-db", ca)
	if err != nil {
		t.Fatal(err)
	}
	hash := secure.SHA256()
	ca[0] = 'X'
	if hash != secure.SHA256() || secure.caSHA256 == digestBytes(ca) {
		t.Fatal("profile aliases input bytes")
	}
	for _, value := range []any{p, secure, *secure} {
		if strings.Contains(fmt.Sprintf("%#v", value), "127.0.0.1") {
			t.Fatal("endpoint disclosed")
		}
		if _, err := json.Marshal(value); err == nil {
			t.Fatal("endpoint serialized")
		}
	}
}

func TestCredentialEndpointRejectsUnsupportedProfilesAndDSNs(t *testing.T) {
	ca, _, _ := endpointCertificates(t)
	for _, v := range []struct {
		host           string
		port           uint16
		db, mode, name string
		ca             []byte
	}{
		{"admission-db", 5432, "vms_camera_test", "disable", "", nil}, {"127.0.0.1,127.0.0.2", 5432, "vms_camera_test", "disable", "", nil}, {"/tmp", 5432, "vms_camera_test", "disable", "", nil}, {"::ffff:127.0.0.1", 5432, "vms_camera_test", "disable", "", nil},
		{"127.0.0.1", 0, "vms_camera_test", "disable", "", nil}, {"127.0.0.1", 5432, "unsafe/name", "disable", "", nil}, {"127.0.0.1", 5432, "vms_camera_test", "prefer", "", nil}, {"127.0.0.1", 5432, "vms_camera_test", "require", "", nil}, {"127.0.0.1", 5432, "vms_camera_test", "verify-ca", "admission-db", ca}, {"127.0.0.1", 5432, "vms_camera_test", "disable", "admission-db", nil}, {"127.0.0.1", 5432, "vms_camera_test", "verify-full", "", ca}, {"127.0.0.1", 5432, "vms_camera_test", "verify-full", "admission-db", []byte("private-value")},
	} {
		if p, err := NewCredentialEndpoint(v.host, v.port, v.db, v.mode, v.name, v.ca); p != nil || err == nil {
			t.Fatal("unsupported profile accepted")
		}
	}
	p, _ := NewCredentialEndpoint("127.0.0.1", 5432, "vms_camera_test", "disable", "", nil)
	valid := "postgres://camera_credential_writer:synthetic-secret@127.0.0.1:5432/vms_camera_test?sslmode=disable"
	for _, dsn := range []string{strings.Replace(valid, "5432", "5433", 1), strings.Replace(valid, "127.0.0.1", "127.0.0.2", 1), strings.Replace(valid, "writer:", "budget:", 1), strings.Replace(valid, "sslmode=disable", "sslmode=prefer", 1), valid + "&sslmode=disable", valid + "&host=other", valid + "&target_session_attrs=any", valid + "#fragment", strings.Replace(valid, ":synthetic-secret", "", 1)} {
		if cfg, err := p.config(dsn, "camera_credential_writer"); cfg != nil || err == nil || strings.Contains(fmt.Sprintf("%+v", err), "synthetic-secret") {
			t.Fatal("unsupported DSN accepted/disclosed")
		}
	}
	cfg, err := p.config(valid, "camera_credential_writer")
	if err != nil || cfg.ConnConfig.TLSConfig != nil || len(cfg.ConnConfig.Fallbacks) != 0 {
		t.Fatal("explicit profile failed", err)
	}
	changedPassword := strings.Replace(valid, "synthetic-secret", "different-password", 1)
	if _, err = p.config(changedPassword, "camera_credential_writer"); err != nil {
		t.Fatal("password improperly bound in endpoint hash", err)
	}
	t.Setenv("PGSERVICE", "unapproved-private-service")
	if _, err = p.config(valid, "camera_credential_writer"); err == nil {
		t.Fatal("ambient service accepted")
	}
}

func TestCredentialEndpointActualTLSVerification(t *testing.T) {
	ca, cert, key := endpointCertificates(t)
	pair, err := tls.X509KeyPair(cert, key)
	if err != nil {
		t.Fatal(err)
	}
	listener, err := tls.Listen("tcp", "127.0.0.1:0", &tls.Config{Certificates: []tls.Certificate{pair}, MinVersion: tls.VersionTLS12})
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	done := make(chan struct{})
	go func() {
		defer close(done)
		conn, err := listener.Accept()
		if err == nil {
			defer conn.Close()
			_ = conn.(*tls.Conn).Handshake()
			var b [1]byte
			_, _ = conn.Read(b[:])
		}
	}()
	port := uint16(listener.Addr().(*net.TCPAddr).Port)
	p, _ := NewCredentialEndpoint("127.0.0.1", port, "vms_camera_test", "verify-full", "admission-db", ca)
	cfg, err := p.config(fmt.Sprintf("postgres://camera_credential_writer:synthetic@127.0.0.1:%d/vms_camera_test?sslmode=verify-full", port), "camera_credential_writer")
	if err != nil {
		t.Fatal(err)
	}
	dialer := &net.Dialer{Timeout: time.Second}
	conn, err := tls.DialWithDialer(dialer, "tcp", listener.Addr().String(), cfg.ConnConfig.TLSConfig)
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	if !p.matchesTransport(conn) {
		t.Fatal("verified TLS refused")
	}
	other, _ := NewCredentialEndpoint("127.0.0.1", port, "vms_camera_test", "disable", "", nil)
	if other.matchesTransport(conn) {
		t.Fatal("TLS connection mislabeled plaintext")
	}
	differentCA, _, _ := endpointCertificates(t)
	wrong, _ := NewCredentialEndpoint("127.0.0.1", port, "vms_camera_test", "verify-full", "admission-db", differentCA)
	if wrong.matchesTransport(conn) {
		t.Fatal("different CA accepted")
	}
	_, _ = conn.Write([]byte{1})
	conn.Close()
	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("TLS fixture leaked")
	}
	var empty *CredentialStore
	if err := empty.CheckCredentialAdmissionBindings(context.Background(), credentialadmission.Record{}, p); err == nil {
		t.Fatal("nil bindings accepted")
	}
}
