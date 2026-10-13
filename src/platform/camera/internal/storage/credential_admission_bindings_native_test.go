//go:build linux

package storage

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"net"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"vms.local/platform/camera/internal/credentialadmission"
	"vms.local/platform/camera/internal/credentialcrypto"
)

func syntheticBindingBundle() []byte {
	key := func(v byte) string {
		return base64.StdEncoding.EncodeToString([]byte(strings.Repeat(string([]byte{v}), 32)))
	}
	raw, _ := json.Marshal(map[string]any{"format_version": 1, "encryption": map[string]any{"active_key_id": "enc-1111111111111111", "keys": map[string]string{"enc-1111111111111111": key(1)}}, "idempotency": map[string]any{"active_key_id": "idem-2222222222222222", "keys": map[string]string{"idem-2222222222222222": key(2)}}})
	return raw
}

// The fixture is built separately before starting the disposable TLS DB.
func TestNativeCredentialBindingFixture(t *testing.T) {
	if os.Getenv("CAMERA_BINDING_TEST_PHASE") != "prepare" {
		t.Skip("isolated fixture preparation not enabled")
	}
	if os.Geteuid() != 0 {
		t.Fatal("isolated fixture owner required")
	}
	base := "/exchange/fixture"
	if err := os.Mkdir(base, 0755); err != nil {
		t.Fatal("fresh isolated fixture required", err)
	}
	if err := os.Chmod(base, 0755); err != nil {
		t.Fatal(err)
	}
	ca, cert, key := endpointCertificates(t)
	dir := base + "/tls"
	if err := os.Mkdir(dir, 0755); err != nil {
		t.Fatal(err)
	}
	_ = os.Chmod(dir, 0755)
	for name, raw := range map[string][]byte{"ca.crt": ca, "server.crt": cert, "server.key": key} {
		p := dir + "/" + name
		if err := os.WriteFile(p, raw, 0600); err != nil {
			t.Fatal(err)
		}
		if name != "server.key" {
			_ = os.Chmod(p, 0644)
		}
	}
	dir = base + "/keys"
	if err := os.Mkdir(dir, 0700); err != nil {
		t.Fatal(err)
	}
	p := dir + "/key-bundle.json"
	if err := os.WriteFile(p, syntheticBindingBundle(), 0400); err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{dir, p} {
		if err := os.Chown(name, 10001, 10001); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.Chmod(dir, 0500); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(p, 0400); err != nil {
		t.Fatal(err)
	}
	fmt.Println("CREDENTIAL_BINDING_PHASE_OK:prepare")
}

func bindingRecord(t *testing.T, p *CredentialEndpoint, ring *credentialcrypto.Keyring) credentialadmission.Record {
	t.Helper()
	db := admissionDatabaseFixture(t)
	hash, _, err := ring.ProtectedBundleReceipt()
	if err != nil {
		t.Fatal(err)
	}
	r, err := credentialadmission.NewFenced(db.DeploymentID, db.OperationID, "2026-10-07T00:00:00Z")
	if err != nil {
		t.Fatal(err)
	}
	b := credentialadmission.Binding{DatabaseID: db.DatabaseID, DatabaseName: db.DatabaseName, SchemaVersion: 9, MigrationSetSHA256: db.MigrationSetSHA256, EndpointProfileSHA256: p.SHA256(), KeyBundleSHA256: hash, ActiveEncryptionKeyID: ring.ActiveEncryptionID(), ActiveIdempotencyKeyID: ring.ActiveIdempotencyID(), WriterRole: "camera_credential_writer", BudgetRole: "camera_credential_budget"}
	r, err = credentialadmission.NextPrepare(r, b, "2026-10-07T00:00:00Z")
	if err != nil {
		t.Fatal(err)
	}
	r, err = credentialadmission.NextOpen(r, "2026-10-07T00:00:00Z")
	if err != nil {
		t.Fatal(err)
	}
	return r
}

func bindingRoleDSN(t *testing.T, s *Store, ip, mode string) string {
	t.Helper()
	cfg := s.pool.Config().ConnConfig
	u := url.URL{Scheme: "postgres", User: url.UserPassword(cfg.User, cfg.Password), Host: net.JoinHostPort(ip, fmt.Sprint(cfg.Port)), Path: "/" + cfg.Database, RawQuery: "sslmode=" + mode}
	return u.String()
}

// Native positive requires the actual separate UID and read-only key mount.
func TestNativeCredentialApprovedBindings(t *testing.T) {
	if os.Getenv("CAMERA_BINDING_TEST_PHASE") != "runtime" {
		t.Skip("native UID/RO/TLS binding runtime not enabled")
	}
	if os.Geteuid() != 10001 || os.Getegid() != 10001 {
		t.Fatal("native runtime UID/GID required")
	}
	path := "/exchange/fixture/keys/key-bundle.json"
	ring, err := credentialcrypto.LoadKeyBundleFile(path)
	if err != nil {
		t.Fatal(err)
	}
	before, readonly, err := ring.ProtectedBundleReceipt()
	if err != nil || !readonly {
		t.Fatal("actual read-only key receipt required")
	}
	ca, err := os.ReadFile("/exchange/fixture/tls/ca.crt")
	if err != nil {
		t.Fatal(err)
	}
	owner, writer, budget, ctx, _ := admissionStores(t)
	cfg := owner.pool.Config().ConnConfig
	addresses, err := net.LookupHost(cfg.Host)
	if err != nil || len(addresses) != 1 {
		t.Fatal("isolated single address required")
	}
	ip := net.ParseIP(addresses[0]).String()
	p, err := NewCredentialEndpoint(ip, cfg.Port, cfg.Database, "verify-full", "admission-db", ca)
	if err != nil {
		t.Fatal(err)
	}
	a, err := OpenCredentialAdmissionDatabase(ctx, bindingRoleDSN(t, writer, ip, "verify-full"), p, "camera_credential_writer")
	if err != nil {
		t.Fatal(err)
	}
	defer a.Close()
	b, err := OpenCredentialAdmissionDatabase(ctx, bindingRoleDSN(t, budget, ip, "verify-full"), p, "camera_credential_budget")
	if err != nil {
		t.Fatal(err)
	}
	defer b.Close()
	c, err := NewCredentialStore(a, b, ring)
	if err != nil {
		t.Fatal(err)
	}
	approved := bindingRecord(t, p, ring)
	db := admissionDatabaseFixture(t)
	putAdmissionMarker(t, owner, ctx, db)
	if err = owner.ProvisionCredentialRuntime(ctx); err != nil {
		t.Fatal(err)
	}
	if err = owner.EnrollCredentialEncryptionKey(ctx, ring.ActiveEncryptionID()); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 2; i++ {
		if err = c.CheckCredentialAdmissionBindings(ctx, approved, p); err != nil {
			t.Fatal(err)
		}
	}
	prepared := approved
	prepared.State = credentialadmission.Prepared
	if err = c.CheckCredentialAdmissionBindings(ctx, prepared, p); err != nil {
		t.Fatal("PREPARED inspection failed", err)
	}
	cases := map[string]func(*credentialadmission.Record){
		"key digest": func(r *credentialadmission.Record) { r.Binding.KeyBundleSHA256 = strings.Repeat("f", 64) },
		"endpoint":   func(r *credentialadmission.Record) { r.Binding.EndpointProfileSHA256 = strings.Repeat("f", 64) },
		"active encryption": func(r *credentialadmission.Record) {
			r.Binding.ActiveEncryptionKeyID = "enc-3333333333333333"
			r.SeenEncryptionKeyIDs = append(r.SeenEncryptionKeyIDs, "enc-3333333333333333")
		},
		"active hmac": func(r *credentialadmission.Record) { r.Binding.ActiveIdempotencyKeyID = "idem-4444444444444444" },
		"generation":  func(r *credentialadmission.Record) { r.Generation++ },
		"fenced":      func(r *credentialadmission.Record) { r.State = credentialadmission.Fenced },
	}
	for name, change := range cases {
		t.Run(name, func(t *testing.T) {
			r := approved
			binding := *r.Binding
			r.Binding = &binding
			r.SeenEncryptionKeyIDs = append([]string{}, r.SeenEncryptionKeyIDs...)
			change(&r)
			if c.CheckCredentialAdmissionBindings(ctx, r, p) == nil {
				t.Fatal("mismatch accepted")
			}
		})
	}
	parsed, _ := credentialcrypto.ParseKeyBundle(syntheticBindingBundle())
	unproved, _ := NewCredentialStore(a, b, parsed)
	if unproved.CheckCredentialAdmissionBindings(ctx, approved, p) == nil {
		t.Fatal("parser-only ring accepted")
	}
	temp := filepath.Join(t.TempDir(), "key-bundle.json")
	if err = os.Chmod(filepath.Dir(temp), 0700); err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(temp, syntheticBindingBundle(), 0400); err != nil {
		t.Fatal(err)
	}
	writable, err := credentialcrypto.LoadKeyBundleFile(temp)
	if err != nil {
		t.Fatal(err)
	}
	unproved, _ = NewCredentialStore(a, b, writable)
	if unproved.CheckCredentialAdmissionBindings(ctx, approved, p) == nil {
		t.Fatal("writable mount accepted")
	}
	unapproved, _ := NewCredentialStore(writer, budget, ring)
	if unapproved.CheckCredentialAdmissionBindings(ctx, approved, p) == nil {
		t.Fatal("legacy pools manufactured endpoint evidence")
	}
	missingBudget, _ := NewCredentialStore(a, a, ring)
	if missingBudget != nil {
		t.Fatal("same-pool accepted")
	}
	if _, err = OpenCredentialAdmissionDatabase(ctx, bindingRoleDSN(t, writer, ip, "disable"), p, "camera_credential_writer"); err == nil {
		t.Fatal("TLS downgrade accepted")
	}
	wrongCA, _, _ := endpointCertificates(t)
	wrong, _ := NewCredentialEndpoint(ip, cfg.Port, cfg.Database, "verify-full", "admission-db", wrongCA)
	if s, err := OpenCredentialAdmissionDatabase(ctx, bindingRoleDSN(t, writer, ip, "verify-full"), wrong, "camera_credential_writer"); err == nil {
		s.Close()
		t.Fatal("wrong CA authenticated")
	}
	wrongName, _ := NewCredentialEndpoint(ip, cfg.Port, cfg.Database, "verify-full", "different.invalid", ca)
	if s, err := OpenCredentialAdmissionDatabase(ctx, bindingRoleDSN(t, writer, ip, "verify-full"), wrongName, "camera_credential_writer"); err == nil {
		s.Close()
		t.Fatal("wrong hostname authenticated")
	}
	// Read-only inspection must not reserve a use, even after repeated failures.
	var uses int64
	if err = owner.pool.QueryRow(ctx, "SELECT uses FROM camera.credential_encryption_budgets WHERE key_id=$1", ring.ActiveEncryptionID()).Scan(&uses); err != nil || uses != 0 {
		t.Fatal("inspection consumed budget", err)
	}
	if _, err = owner.pool.Exec(ctx, "REVOKE SELECT ON camera.credential_admission_database FROM camera_credential_budget"); err != nil {
		t.Fatal(err)
	}
	if c.CheckCredentialAdmissionBindings(ctx, approved, p) == nil {
		t.Fatal("budget marker grant loss accepted")
	}
	if _, err = owner.pool.Exec(ctx, "GRANT SELECT ON camera.credential_admission_database TO camera_credential_budget"); err != nil {
		t.Fatal(err)
	}
	if err = c.CheckCredentialAdmissionBindings(ctx, approved, p); err != nil {
		t.Fatal("restored grant not rechecked", err)
	}
	if err = owner.DisableCredentialEncryption(ctx); err != nil {
		t.Fatal(err)
	}
	if c.CheckCredentialAdmissionBindings(ctx, approved, p) == nil {
		t.Fatal("disabled key accepted")
	}
	if hash, _, _ := ring.ProtectedBundleReceipt(); hash != before {
		t.Fatal("loaded receipt changed")
	}
	if err = os.WriteFile(path, []byte("synthetic denied mutation"), 0400); err == nil {
		t.Fatal("key mount writable")
	}
	fmt.Println("CREDENTIAL_BINDING_PHASE_OK:runtime")
}

// Native plaintext profile can be tested separately on a disposable local DB;
// it does not claim a successful read-only key binding check.
func TestNativeCredentialEndpointPlaintextAndNoFallback(t *testing.T) {
	nativeCredentialRequired(t)
	owner, ctx := testStore(t)
	writer := credentialRoleStore(t, owner, ctx, "camera_credential_writer")
	cfg := owner.pool.Config().ConnConfig
	addresses, err := net.LookupHost(cfg.Host)
	if err != nil || len(addresses) != 1 {
		t.Fatal("isolated single address required")
	}
	ip := net.ParseIP(addresses[0]).String()
	p, _ := NewCredentialEndpoint(ip, cfg.Port, cfg.Database, "disable", "", nil)
	s, err := OpenCredentialAdmissionDatabase(ctx, bindingRoleDSN(t, writer, ip, "disable"), p, "camera_credential_writer")
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	secureCA, _, _ := endpointCertificates(t)
	secure, _ := NewCredentialEndpoint(ip, cfg.Port, cfg.Database, "verify-full", "admission-db", secureCA)
	if s, err := OpenCredentialAdmissionDatabase(ctx, bindingRoleDSN(t, writer, ip, "verify-full"), secure, "camera_credential_writer"); err == nil {
		s.Close()
		t.Fatal("unapproved server authenticated or plaintext fallback used")
	}
	var missing *Store
	if _, err = NewCredentialStore(s, missing, nil); err == nil {
		t.Fatal("missing role/key accepted")
	}
}
