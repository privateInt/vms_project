//go:build linux

package storage

// Trusted orchestration below is exclusively a synthetic disposable fixture.
// No host/production HBA, role, restore or activation entry point is exposed.
import (
	"context"
	"encoding/json"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"net"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"
	"vms.local/platform/camera/internal/credentialadmission"
	"vms.local/platform/camera/internal/credentialcrypto"
)

type boundaryResumeState struct {
	Policy                          credentialadmission.Policy
	Open                            credentialadmission.Record
	Prepared                        credentialadmission.Record
	RuntimeIP, Writer, Budget, Host string
	Port                            uint16
	First                           CredentialMetadata
}

func resumeProof(t *testing.T, phase string) {
	prefix := "CREDENTIAL_BOUNDARY_RESUME_PHASE_OK:"
	if os.Getenv("CAMERA_BOUNDARY_LOCAL_ONLY") == "1" {
		prefix = "LOCAL_BOUNDARY_RESUME_PHASE_OK:"
	}
	t.Log(prefix + phase)
}
func resumeRead(t *testing.T) boundaryResumeState {
	// The cap-limited maintenance owner cannot read UID10001 private files.
	// Keep its reviewed receipt in a separate root-owned 0600 file; only the
	// actual runtime reads the UID10001 copy from its RO private directory.
	name := "runtime/runtime.json"
	if os.Geteuid() == 0 {
		name = "resume.json"
	}
	raw, e := os.ReadFile(filepath.Join(boundaryBase(t), name))
	var s boundaryResumeState
	if e != nil || json.Unmarshal(raw, &s) != nil || credentialadmission.Validate(s.Open) != nil || s.Open.State != credentialadmission.Open {
		t.Fatal("private reviewed runtime fixture unavailable")
	}
	return s
}
func resumeAuthorize(t *testing.T, ctx context.Context, l *credentialadmission.MaintenanceLease, control, target *Store, s boundaryState, r boundaryResumeState) error {
	return control.AuthorizeRestoredCredentialOpen(ctx, l, r.Prepared, r.Open, boundaryEndpoint(t, s), s.SourceIP, target, restoreKeys(t, "candidate"), restoreKeys(t, "previous"), restoreKeys(t, "restored"), restoreReceipt(t).BackupMarker)
}
func TestNativeCredentialBoundaryResumeOwner(t *testing.T) {
	phase := os.Getenv("CAMERA_BOUNDARY_RESUME_PHASE")
	if phase == "" {
		t.Skip("dedicated disposable resume owner required")
	}
	if os.Geteuid() != 0 || os.Getenv("CAMERA_BOUNDARY_RESUME_ONLY") != "1" {
		t.Fatal("explicit disposable resume fixture required")
	}
	base := boundaryBase(t)
	s := boundaryRead(t, false)
	ctx, cancel := context.WithTimeout(context.Background(), 45*time.Second)
	defer cancel()
	if phase == "setup" {
		old := restoreReceipt(t)
		opened, e := credentialadmission.NextOpen(old.Prepared, "2026-10-07T03:00:00Z")
		if e != nil || !reflect.DeepEqual(s.Record, old.Prepared) {
			t.Fatal("exact committed restore candidate required")
		}
		ip := "127.0.0.2"
		uid := 0
		if os.Getenv("CAMERA_BOUNDARY_LOCAL_ONLY") != "1" {
			ips, e := net.LookupHost("boundary-client")
			if e != nil || len(ips) != 1 {
				t.Fatal("single disposable runtime source required")
			}
			ip = net.ParseIP(ips[0]).String()
			uid = 10001
		}
		if ip == s.SourceIP {
			t.Fatal("runtime source must differ from maintenance")
		}
		dir := filepath.Join(base, "runtime")
		if os.Mkdir(dir, 0700) != nil {
			t.Fatal("fresh runtime fixture required")
		}
		raw, e := os.ReadFile(filepath.Join(base, "keys/candidate/key-bundle.json"))
		if e != nil {
			t.Fatal("exact candidate bytes required")
		}
		r := boundaryResumeState{s.Policy, opened, old.Prepared, ip, boundaryDSN(s, "camera_credential_writer", "vms_camera_test"), boundaryDSN(s, "camera_credential_budget", "vms_camera_test"), s.Host, s.Port, old.First}
		boundarySave(t, filepath.Join(base, "resume.json"), r, 0600)
		boundarySave(t, filepath.Join(dir, "runtime.json"), r, 0400)
		if os.WriteFile(filepath.Join(dir, "key-bundle.json"), raw, 0400) != nil {
			t.Fatal("private runtime key copy failed")
		}
		clear(raw)
		for _, name := range []string{"runtime.json", "key-bundle.json"} {
			p := filepath.Join(dir, name)
			if os.Chown(p, uid, uid) != nil || os.Chmod(p, 0400) != nil {
				t.Fatal("runtime private supply permissions failed")
			}
		}
		if os.Chown(dir, uid, uid) != nil || os.Chmod(dir, 0500) != nil {
			t.Fatal("runtime private directory failed")
		}
		resumeProof(t, phase)
		return
	}
	r := resumeRead(t)
	l := boundaryLease(t, ctx, s)
	defer l.Close()
	control := boundaryMaintenance(t, ctx, s)
	defer control.Close()
	target := restoreTarget(t, ctx, s)
	defer target.Close()
	key := r.Open.Binding.ActiveEncryptionKeyID
	if phase == "open" {
		if credentialUses(t, target, ctx, key) != 0 {
			t.Fatal("unused candidate required before OPEN")
		}
		// An old backup marker cannot be repaired by OPEN authorization.
		if _, e := target.pool.Exec(ctx, "UPDATE camera.credential_admission_database SET database_id=$1", restoreReceipt(t).BackupMarker.DatabaseID); e != nil {
			t.Fatal("negative marker fixture failed")
		}
		if resumeAuthorize(t, ctx, l, control, target, s, r) == nil {
			t.Fatal("uncommitted marker authorized")
		}
		var marker string
		if target.pool.QueryRow(ctx, "SELECT database_id FROM camera.credential_admission_database").Scan(&marker) != nil || marker != restoreReceipt(t).BackupMarker.DatabaseID || credentialUses(t, target, ctx, key) != 0 {
			t.Fatal("OPEN repaired marker or budget")
		}
		if _, e := target.pool.Exec(ctx, "UPDATE camera.credential_admission_database SET database_id=$1", r.Open.Binding.DatabaseID); e != nil {
			t.Fatal("restore marker negative fixture failed")
		}
		changed := r
		changed.Open.Generation++
		if resumeAuthorize(t, ctx, l, control, target, s, changed) == nil {
			t.Fatal("different OPEN pair accepted")
		}
		if resumeAuthorize(t, ctx, l, control, target, s, r) != nil {
			t.Fatal("exact unused candidate OPEN failed")
		}
		s.Record = r.Open
		boundarySave(t, filepath.Join(base, "state.json"), s, 0600)
		// Intentionally return with maintenance-only HBA and both roles NOLOGIN.
		// The next fresh process proves the interrupted resume cannot write.
	} else if phase == "open-retry" {
		if resumeAuthorize(t, ctx, l, control, target, s, r) != nil || credentialUses(t, target, ctx, key) != 0 {
			t.Fatal("exact interrupted OPEN retry failed")
		}
	} else if phase == "enable" || phase == "enable-retry" {
		if confirmMaintenanceFence(l, r.Open) != nil {
			t.Fatal("durable exact OPEN required before account resume")
		}
		// Explicit fixture orchestration. Active HBA proof is actual new
		// maintenance authentication after reload, followed by runtime probes.
		body, e := CredentialRestoredRuntimeHBA("vms_camera_test", s.SourceIP, r.RuntimeIP)
		if e != nil {
			t.Fatal("reviewed runtime HBA unavailable")
		}
		if phase == "enable" {
			boundaryAtomicHBA(t, base, body)
			var loaded bool
			if control.pool.QueryRow(ctx, "SELECT pg_reload_conf()").Scan(&loaded) != nil || !loaded {
				t.Fatal("runtime HBA reload failed")
			}
			time.Sleep(100 * time.Millisecond)
		}
		var disk []byte
		var parsed bool
		if control.pool.QueryRow(ctx, "SELECT pg_read_binary_file(current_setting('hba_file'))").Scan(&disk) != nil || string(disk) != string(body) || control.pool.QueryRow(ctx, "SELECT count(*)=5 AND bool_and(error IS NULL) FROM pg_hba_file_rules").Scan(&parsed) != nil || !parsed {
			t.Fatal("exact parsed runtime HBA required")
		}
		fresh := boundaryMaintenance(t, ctx, s)
		fresh.Close()
		if confirmMaintenanceFence(l, r.Open) != nil {
			t.Fatal("OPEN changed before account resume")
		}
		if _, e := control.pool.Exec(ctx, "ALTER ROLE camera_credential_writer LOGIN; ALTER ROLE camera_credential_budget LOGIN"); e != nil {
			t.Fatal("explicit disposable account resume failed")
		}
		// Valid passwords from maintenance source cannot be runtime credentials.
		for _, role := range []string{"camera_credential_writer", "camera_credential_budget"} {
			boundaryDenied(t, ctx, boundaryConfig(t, s, role, "vms_camera_test", s.SourceIP, "", false, true))
		}
	} else if phase == "post-write-retry" {
		if credentialUses(t, target, ctx, key) != 1 || resumeAuthorize(t, ctx, l, control, target, s, r) != nil || credentialUses(t, target, ctx, key) != 1 {
			t.Fatal("OPEN retry rewound committed runtime budget")
		}
		if rehearsalRows(t, target, ctx, 1) != restoreReceipt(t).History || storedCredentialSecret(t, target, ctx, restoreKeys(t, "candidate"), 1) != credentialWrite(t, 0).Secret || storedCredentialSecret(t, target, ctx, restoreKeys(t, "candidate"), 2) != credentialWrite(t, 1).Secret {
			t.Fatal("restored historical/new ciphertext changed")
		}
	} else {
		t.Fatal("unknown resume owner phase")
	}
	if phase == "open" || phase == "open-retry" {
		var closed bool
		if control.pool.QueryRow(ctx, "SELECT count(*)=2 AND bool_and(NOT rolcanlogin) FROM pg_roles WHERE rolname IN ('camera_credential_writer','camera_credential_budget')").Scan(&closed) != nil || !closed {
			t.Fatal("accounts resumed before boundary phase")
		}
	}
	if confirmMaintenanceFence(l, r.Open) != nil {
		t.Fatal("exact final OPEN required")
	}
	resumeProof(t, phase)
}
func TestNativeCredentialBoundaryResumeRuntime(t *testing.T) {
	phase := os.Getenv("CAMERA_BOUNDARY_RESUME_PHASE")
	if phase == "" {
		t.Skip("dedicated disposable resume runtime required")
	}
	local := os.Getenv("CAMERA_BOUNDARY_LOCAL_ONLY") == "1"
	if !local {
		status, e := os.ReadFile("/proc/self/status")
		if os.Geteuid() != 10001 || os.Getegid() != 10001 || e != nil || !strings.Contains(string(status), "CapEff:\t0000000000000000") {
			t.Fatal("separate unprivileged runtime identity required")
		}
	}
	ctx, cancel := context.WithTimeout(context.Background(), 45*time.Second)
	defer cancel()
	base := boundaryBase(t)
	r := resumeRead(t)
	ca, e := os.ReadFile(filepath.Join(base, "tls/ca.crt"))
	if e != nil {
		t.Fatal("reviewed CA unavailable")
	}
	endpoint, e := NewCredentialEndpoint(r.Host, r.Port, "vms_camera_test", "verify-full", "boundary-db", ca)
	if e != nil {
		t.Fatal("approved endpoint unavailable")
	}
	if phase == "closed" {
		for _, role := range []string{"camera_credential_writer", "camera_credential_budget"} {
			s := boundaryRead(t, true)
			cfg := boundaryConfig(t, s, role, "vms_camera_test", r.RuntimeIP, "", true, true)
			boundaryDenied(t, ctx, cfg)
		}
		resumeProof(t, phase)
		return
	}
	var a, b *Store
	if local {
		probe := boundaryRead(t, true)
		makeStore := func(role string) *Store {
			cfg := boundaryConfig(t, probe, role, "vms_camera_test", r.RuntimeIP, "", true, true)
			return resumeLocalPool(t, ctx, cfg, endpoint)
		}
		a = makeStore("camera_credential_writer")
		b = makeStore("camera_credential_budget")
	} else {
		a, e = OpenCredentialAdmissionDatabase(ctx, r.Writer, endpoint, "camera_credential_writer")
		if e != nil {
			t.Fatal("actual writer TLS authentication failed")
		}
		b, e = OpenCredentialAdmissionDatabase(ctx, r.Budget, endpoint, "camera_credential_budget")
		if e != nil {
			a.Close()
			t.Fatal("actual budget TLS authentication failed")
		}
	}
	defer a.Close()
	defer b.Close()
	for _, store := range []*Store{a, b} {
		var source string
		if store.pool.QueryRow(ctx, "SELECT host(inet_client_addr())").Scan(&source) != nil || source != r.RuntimeIP {
			t.Fatal("actual runtime source mismatch")
		}
	}
	ring, e := credentialcrypto.LoadKeyBundleFile(filepath.Join(base, "runtime/key-bundle.json"))
	if e != nil {
		t.Fatal("protected runtime keys unavailable")
	}
	hash, ro, e := ring.ProtectedBundleReceipt()
	if e != nil || hash != r.Open.Binding.KeyBundleSHA256 || (!local && !ro) {
		t.Fatal("exact RO runtime keys required")
	}
	c, e := NewAdmittedCredentialStore(a, b, ring, r.Policy, r.Open, endpoint)
	if e != nil {
		t.Fatal("reviewed admitted runtime constructor failed")
	}
	if local {
		if c.CheckReady(ctx) == nil {
			t.Fatal("RW owner diagnostic must not pass public admission")
		}
		c.admission = boundaryRestoreSeedGuard{}
	} else {
		if c.CheckReady(ctx) != nil {
			t.Fatal("actual public RO admission readiness failed")
		}
		// A stale reviewed record must fail before budget/data IO.
		stale := r.Open
		stale.Binding = &credentialadmission.Binding{}
		*stale.Binding = *r.Open.Binding
		stale.Binding.DatabaseID = "77777777-7777-4777-8777-777777777777"
		denied, e := NewAdmittedCredentialStore(a, b, ring, r.Policy, stale, endpoint)
		if e != nil || denied.CheckReady(ctx) == nil {
			t.Fatal("stale authority authorized")
		}
	}
	// Runtime roles cannot directly inspect/reset budgets or mutate the marker.
	for _, store := range []*Store{a, b} {
		if _, e := store.pool.Exec(ctx, "UPDATE camera.credential_encryption_budgets SET uses=0"); e == nil {
			t.Fatal("runtime budget reset permitted")
		}
		if _, e := store.pool.Exec(ctx, "UPDATE camera.credential_admission_database SET generation=generation+1"); e == nil {
			t.Fatal("runtime marker mutation permitted")
		}
	}
	first, replay, e := c.WriteVersion(ctx, credentialIdentity("create"), credentialWrite(t, 0), authorizeCredentialForTest)
	if e != nil || !replay || first != r.First {
		t.Fatal("restored HMAC/history replay failed")
	}
	if phase == "write" {
		next, replay, e := c.WriteVersion(ctx, credentialIdentity("resume-update"), credentialWrite(t, 1), authorizeCredentialForTest)
		if e != nil || replay || next.Version != 2 {
			t.Fatal("new-key runtime write failed", e)
		}
	} else if phase == "recreated" {
		next, replay, e := c.WriteVersion(ctx, credentialIdentity("resume-update"), credentialWrite(t, 1), authorizeCredentialForTest)
		if e != nil || !replay || next.Version != 2 {
			t.Fatal("new process durable replay failed")
		}
	} else {
		t.Fatal("unknown runtime phase")
	}
	_, replay, e = c.WriteVersion(ctx, credentialIdentity("resume-update"), credentialWrite(t, 1), authorizeCredentialForTest)
	if e != nil || !replay {
		t.Fatal("new-key idempotent retry failed")
	}
	reference := CredentialReference{"credential-1", "parent", 2}
	if _, e = c.CheckReference(ctx, credentialIdentity("reference"), reference, credentialWrite(t, 1).Target, authorizeCredentialForTest); e != nil {
		t.Fatal("resumed reference failed")
	}
	// Correct maintenance credentials from runtime source remain rejected.
	probe := boundaryRead(t, true)
	for _, role := range []string{"camera_credential_writer", "camera_credential_budget"} {
		boundaryDenied(t, ctx, boundaryConfig(t, probe, role, "postgres", r.RuntimeIP, "", true, true))
		boundaryDenied(t, ctx, boundaryConfig(t, probe, role, "vms_camera_test", r.RuntimeIP, "", true, false))
		cfg := boundaryConfig(t, probe, role, "vms_camera_test", r.RuntimeIP, "", true, true)
		cfg.Password = "synthetic-invalid-password"
		boundaryDenied(t, ctx, cfg, "28P01")
	}
	boundaryDenied(t, ctx, boundaryConfig(t, probe, CredentialMaintenanceRole, "postgres", r.RuntimeIP, "client", true, true))
	resumeProof(t, phase)
}

// Test-only LOCAL pool for separate loopback diagnostics. No shipped runtime
// opener bypass; LOCAL receipts are rejected by the native acceptance parser.
func resumeLocalPool(t *testing.T, ctx context.Context, cfg *pgx.ConnConfig, p *CredentialEndpoint) *Store {
	t.Helper()
	pc, e := pgxpool.ParseConfig("postgres://unused@127.0.0.1/unused?sslmode=disable")
	if e != nil {
		t.Fatal("local pool config failed")
	}
	pc.ConnConfig = cfg
	pc.MaxConns = 1
	pool, e := pgxpool.NewWithConfig(ctx, pc)
	if e != nil || pool.Ping(ctx) != nil {
		if pool != nil {
			pool.Close()
		}
		t.Fatal("local approved role pool failed")
	}
	return &Store{pool: pool, admissionEndpoint: p}
}
