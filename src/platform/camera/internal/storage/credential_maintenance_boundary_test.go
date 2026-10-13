package storage

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"math/big"
	"strings"
	"testing"
	"time"
)

func maintenanceCertificates(t *testing.T) map[string][]byte {
	t.Helper()
	now := time.Now()
	key, _ := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	ca := &x509.Certificate{SerialNumber: big.NewInt(1), NotBefore: now.Add(-time.Minute), NotAfter: now.Add(time.Hour), IsCA: true, BasicConstraintsValid: true, KeyUsage: x509.KeyUsageCertSign}
	der, err := x509.CreateCertificate(rand.Reader, ca, ca, &key.PublicKey, key)
	if err != nil {
		t.Fatal("synthetic CA creation failed")
	}
	files := map[string][]byte{"ca.crt": pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der})}
	for i, name := range []string{"server", "client", "wrong-client", "extra-subject"} {
		private, _ := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
		cert := &x509.Certificate{SerialNumber: big.NewInt(int64(i + 2)), NotBefore: now.Add(-time.Minute), NotAfter: now.Add(time.Hour), BasicConstraintsValid: true, KeyUsage: x509.KeyUsageDigitalSignature,
			Subject: pkix.Name{CommonName: CredentialMaintenanceRole}, ExtKeyUsage: []x509.ExtKeyUsage{x509.ExtKeyUsageClientAuth}}
		if name == "server" {
			cert.Subject.CommonName = "boundary-db"
			cert.DNSNames = []string{"boundary-db"}
			cert.ExtKeyUsage = []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth}
		} else if name == "wrong-client" {
			cert.Subject.CommonName = "unapproved-maintenance"
		} else if name == "extra-subject" {
			cert.Subject.Organization = []string{"unapproved-subject"}
		}
		body, e := x509.CreateCertificate(rand.Reader, cert, ca, &private.PublicKey, key)
		raw, e2 := x509.MarshalPKCS8PrivateKey(private)
		if e != nil || e2 != nil {
			t.Fatal("synthetic certificate creation failed")
		}
		files[name+".crt"] = pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: body})
		files[name+".key"] = pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: raw})
	}
	return files
}

func TestCredentialMaintenanceHBAExactPolicy(t *testing.T) {
	for _, source := range []string{"127.0.0.1", "2001:db8::1"} {
		body, err := CredentialMaintenanceHBA("all", source)
		if err != nil || !strings.Contains(string(body), `hostssl "all",postgres camera_maintenance `+source) ||
			!strings.Contains(string(body), "clientcert=verify-full") || strings.Contains(string(body), "include") || strings.Count(string(body), "\n") != 5 {
			t.Fatal("complete HBA policy differs")
		}
	}
	for _, source := range []string{"localhost", "0.0.0.0", "::", "224.0.0.1", "::ffff:127.0.0.1", "127.0.0.1/24", "127.0.0.1\nhost all all 0.0.0.0/0 trust"} {
		body, err := CredentialMaintenanceHBA("vms_camera_test", source)
		if body != nil {
			t.Fatal("unsupported source produced policy")
		}
		assertMaintenanceDenied(t, err)
	}
	for _, db := range []string{"postgres", "template0", "template1", "db,all", "db\"", "db\n", ""} {
		_, err := CredentialMaintenanceHBA(db, "127.0.0.1")
		assertMaintenanceDenied(t, err)
	}
}

func TestCredentialMaintenanceConnectionConfiguration(t *testing.T) {
	f := maintenanceCertificates(t)
	p, _ := NewCredentialEndpoint("127.0.0.1", 5432, "vms_camera_test", "verify-full", "boundary-db", f["ca.crt"])
	pair, _ := tls.X509KeyPair(f["client.crt"], f["client.key"])
	dsn := "postgres://camera_maintenance:synthetic-private@127.0.0.1:5432/postgres?sslmode=verify-full"
	cfg, err := maintenanceConfig(dsn, p, "127.0.0.2", pair)
	if err != nil || cfg.MaxConns != 1 || len(cfg.ConnConfig.Fallbacks) != 0 || cfg.ConnConfig.TLSConfig.InsecureSkipVerify || cfg.ConnConfig.TLSConfig.MinVersion != tls.VersionTLS12 {
		t.Fatal("strict maintenance config failed")
	}
	before := cfg.ConnConfig.TLSConfig.Certificates[0].Certificate[0][0]
	pair.Certificate[0][0] ^= 1
	if cfg.ConnConfig.TLSConfig.Certificates[0].Certificate[0][0] != before {
		t.Fatal("certificate DER aliases caller")
	}
	pair, _ = tls.X509KeyPair(f["client.crt"], f["client.key"])
	for _, value := range []string{strings.Replace(dsn, "maintenance:", "credential_writer:", 1), strings.Replace(dsn, "/postgres", "/other", 1), strings.Replace(dsn, "verify-full", "disable", 1), dsn + "&sslmode=verify-full", dsn + "&options=private", strings.Replace(dsn, "5432", "5433", 1)} {
		_, err := maintenanceConfig(value, p, "127.0.0.2", pair)
		assertMaintenanceDenied(t, err)
	}
	for _, kind := range []string{"wrong-client", "extra-subject"} {
		wrong, _ := tls.X509KeyPair(f[kind+".crt"], f[kind+".key"])
		_, err = maintenanceConfig(dsn, p, "127.0.0.2", wrong)
		assertMaintenanceDenied(t, err)
	}
	_, err = maintenanceConfig(dsn, p, "127.0.0.2", tls.Certificate{})
	assertMaintenanceDenied(t, err)
	_, err = OpenCredentialMaintenanceDatabase(context.Background(), dsn, p, "127.0.0.2", pair)
	assertMaintenanceDenied(t, err)
	t.Setenv("PGOPTIONS", "synthetic-private")
	_, err = maintenanceConfig(dsn, p, "127.0.0.2", pair)
	assertMaintenanceDenied(t, err)
}
