//go:build linux

package storage

// Only the disposable runner calls these destructive fixture phases. No
// production restore entry point, automatic OPEN or runtime LOGIN is provided.
import (
	"context"
	"crypto/rand"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"

	"vms.local/platform/camera/internal/credentialadmission"
	"vms.local/platform/camera/internal/credentialcrypto"
)

// Test-only seed guard: schema 9 was explicitly migrated by the disposable seed.
// This writes synthetic backup history before fencing; it is not runtime admission evidence.
type boundaryRestoreSeedGuard struct{}

func (boundaryRestoreSeedGuard) acquire(ctx context.Context, c *CredentialStore) (credentialOperationLease, error) {
	return fixtureCredentialLease{}, ctx.Err()
}

type boundaryRestoreReceipt struct {
	BackupMarker          CredentialAdmissionDatabase
	History               string
	First                 CredentialMetadata
	DumpHash, KeyHash     string
	BackupUses, HighWater int64
	Prepared              credentialadmission.Record
}

func restoreProof(t *testing.T, phase string) {
	t.Helper()
	prefix := "CREDENTIAL_BOUNDARY_RESTORE_PHASE_OK:"
	if os.Getenv("CAMERA_BOUNDARY_LOCAL_ONLY") == "1" {
		prefix = "LOCAL_BOUNDARY_RESTORE_PHASE_OK:"
	}
	t.Log(prefix + phase)
}
func restoreKeys(t *testing.T, name string) *credentialcrypto.Keyring {
	t.Helper()
	k, e := credentialcrypto.LoadKeyBundleFile(filepath.Join(boundaryBase(t), "keys", name, "key-bundle.json"))
	if e != nil {
		t.Fatal("protected synthetic bundle unavailable")
	}
	return k
}
func restoreReceipt(t *testing.T) boundaryRestoreReceipt {
	t.Helper()
	raw, e := os.ReadFile(filepath.Join(boundaryBase(t), "restore.json"))
	var r boundaryRestoreReceipt
	if e != nil || json.Unmarshal(raw, &r) != nil || r.BackupMarker.DatabaseID == "" {
		t.Fatal("restore receipt absent")
	}
	return r
}
func saveRestore(t *testing.T, r boundaryRestoreReceipt) {
	boundarySave(t, filepath.Join(boundaryBase(t), "restore.json"), r, 0600)
}
func restoreTarget(t *testing.T, ctx context.Context, s boundaryState) *Store {
	t.Helper()
	target, e := OpenCredentialMaintenanceDatabase(ctx, boundaryDSN(s, CredentialMaintenanceRole, "vms_camera_test"), boundaryEndpoint(t, s), s.SourceIP, boundaryCertificate(t, false, "client"))
	if e != nil {
		t.Fatal("fresh maintenance target unavailable", e)
	}
	return target
}
func restorePG(t *testing.T, ctx context.Context, s boundaryState, program string, args ...string) bool {
	t.Helper()
	base := boundaryBase(t)
	cmd := exec.CommandContext(ctx, program, args...)
	env := []string{}
	for _, e := range os.Environ() {
		if !strings.HasPrefix(e, "PG") {
			env = append(env, e)
		}
	}
	cmd.Env = append(env, "PGHOST=boundary-db", "PGHOSTADDR="+s.Host, "PGPORT="+stringPort(s.Port), "PGUSER=camera_maintenance", "PGDATABASE=vms_camera_test", "PGPASSWORD="+s.MaintenancePassword, "PGSSLMODE=verify-full", "PGSSLROOTCERT="+filepath.Join(base, "tls/ca.crt"), "PGSSLCERT="+filepath.Join(base, "tls/client.crt"), "PGSSLKEY="+filepath.Join(base, "tls/client.key"), "PGCONNECT_TIMEOUT=5")
	// Do not emit libpq output or command strings containing private inputs.
	return cmd.Run() == nil
}
func stringPort(p uint16) string {
	var b [5]byte
	i := len(b)
	for {
		i--
		b[i] = byte(p%10) + '0'
		p /= 10
		if p == 0 {
			return string(b[i:])
		}
	}
}

func TestNativeCredentialBoundaryRestore(t *testing.T) {
	phase := os.Getenv("CAMERA_BOUNDARY_RESTORE_PHASE")
	if phase == "" {
		t.Skip("dedicated disposable boundary restore runner required")
	}
	if os.Geteuid() != 0 || os.Getenv("CAMERA_BOUNDARY_RESTORE_ONLY") != "1" || os.Getenv("CAMERA_TEST_ENGINE") == "pglite" {
		t.Fatal("explicit native synthetic restore fixture required")
	}
	base := boundaryBase(t)
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()
	if phase == "keys" {
		if os.Mkdir(filepath.Join(base, "keys"), 0700) != nil {
			t.Fatal("fresh private key fixture required")
		}
		key := func() string {
			var b [32]byte
			if _, e := rand.Read(b[:]); e != nil {
				t.Fatal("synthetic entropy failed")
			}
			return base64.StdEncoding.EncodeToString(b[:])
		}
		wire := map[string]any{"format_version": 1, "encryption": map[string]any{"active_key_id": credentialOldEnc, "keys": map[string]string{credentialOldEnc: key()}}, "idempotency": map[string]any{"active_key_id": credentialOldMac, "keys": map[string]string{credentialOldMac: key()}}}
		for _, name := range []string{"previous", "backup", "restored", "candidate"} {
			if os.Mkdir(filepath.Join(base, "keys", name), 0700) != nil {
				t.Fatal("private key directory failed")
			}
		}
		boundarySave(t, filepath.Join(base, "keys/previous/key-bundle.json"), wire, 0600)
		restoreProof(t, phase)
		return
	}
	s := boundaryRead(t, false)
	p := boundaryEndpoint(t, s)
	if phase == "history" {
		owner := restoreTarget(t, ctx, s)
		defer owner.Close()
		if owner.ProvisionCredentialRuntime(ctx) != nil || owner.ProvisionCredentialAdmissionReaders(ctx) != nil {
			t.Fatal("synthetic runtime grants failed")
		}
		createDeleteDevice(t, owner, ctx, "parent")
		writer := boundaryStore(t, ctx, s, "camera_credential_writer", "vms_camera_test")
		defer writer.Close()
		budget := boundaryStore(t, ctx, s, "camera_credential_budget", "vms_camera_test")
		defer budget.Close()
		c, e := newFixtureCredentialStore(writer, budget, restoreKeys(t, "previous"))
		if e != nil {
			t.Fatal(e)
		}
		c.admission = boundaryRestoreSeedGuard{}
		first, replay, e := c.WriteVersion(ctx, credentialIdentity("create"), credentialWrite(t, 0), authorizeCredentialForTest)
		if e != nil || replay {
			t.Fatal("synthetic history write failed", e)
		}
		saveRestore(t, boundaryRestoreReceipt{BackupMarker: admissionDatabaseFixture(t), History: rehearsalRows(t, owner, ctx, 1), First: first, BackupUses: credentialUses(t, owner, ctx, credentialOldEnc)})
		restoreProof(t, phase)
		return
	}
	r := restoreReceipt(t)
	if phase == "backup" {
		dump := filepath.Join(base, "camera.pgdump")
		if !restorePG(t, ctx, s, "pg_dump", "--format=custom", "--file="+dump) {
			t.Fatal("actual synthetic TLS dump failed")
		}
		if os.Chmod(dump, 0600) != nil {
			t.Fatal("dump protection failed")
		}
		raw, e := os.ReadFile(dump)
		if e != nil {
			t.Fatal("dump absent")
		}
		r.DumpHash = digestBytes(raw)
		key, e := os.ReadFile(filepath.Join(base, "keys/previous/key-bundle.json"))
		if e != nil {
			t.Fatal("key source absent")
		}
		r.KeyHash = digestBytes(key)
		if os.WriteFile(filepath.Join(base, "keys/backup/key-bundle.json"), key, 0600) != nil {
			t.Fatal("synthetic backup failed")
		}
		saveRestore(t, r)
		restoreProof(t, phase)
		return
	}
	if phase == "advance" {
		owner := restoreTarget(t, ctx, s)
		defer owner.Close()
		if _, e := owner.ReserveCredentialEncryptionUse(ctx, credentialOldEnc); e != nil {
			t.Fatal("post snapshot reservation failed")
		}
		if _, e := owner.ReserveCredentialEncryptionUse(ctx, credentialOldEnc); e != nil {
			t.Fatal("post snapshot reservation failed")
		}
		r.HighWater = credentialUses(t, owner, ctx, credentialOldEnc)
		if r.HighWater != r.BackupUses+2 {
			t.Fatal("advance proof failed")
		}
		saveRestore(t, r)
		restoreProof(t, phase)
		return
	}
	l := boundaryLease(t, ctx, s)
	defer l.Close()
	control := boundaryMaintenance(t, ctx, s)
	defer control.Close()
	if phase == "restore" {
		if s.Record.State != credentialadmission.Fenced || control.InspectCredentialMaintenanceHBA(ctx, l, s.Record, p, s.SourceIP) != nil {
			t.Fatal("restore requires pinned FENCED boundary")
		}
		dump := filepath.Join(base, "camera.pgdump")
		raw, e := os.ReadFile(dump)
		if e != nil || digestBytes(raw) != r.DumpHash {
			t.Fatal("approved dump mismatch")
		}
		key, e := os.ReadFile(filepath.Join(base, "keys/backup/key-bundle.json"))
		if e != nil || digestBytes(key) != r.KeyHash {
			t.Fatal("approved key backup mismatch")
		}
		// Native runner has already proved off-source rejection. Only maintenance
		// reconnects; HBA and cluster roles remain outside the restored DB snapshot.
		if _, e := control.pool.Exec(ctx, "ALTER DATABASE vms_camera_test ALLOW_CONNECTIONS true"); e != nil {
			t.Fatal("isolated maintenance reconnect failed")
		}
		target := restoreTarget(t, ctx, s)
		before := credentialUses(t, target, ctx, credentialOldEnc)
		if before != r.HighWater {
			t.Fatal("pre-restore high water mismatch")
		}
		corrupt := filepath.Join(base, "corrupt.pgdump")
		if os.WriteFile(corrupt, []byte("not a postgres archive"), 0600) != nil {
			t.Fatal("negative archive fixture failed")
		}
		if restorePG(t, ctx, s, "pg_restore", "--dbname=vms_camera_test", "--single-transaction", "--exit-on-error", corrupt) {
			t.Fatal("corrupt archive accepted")
		}
		_ = os.Remove(corrupt)
		if credentialUses(t, target, ctx, credentialOldEnc) != before || confirmMaintenanceFence(l, s.Record) != nil {
			t.Fatal("failed restore changed boundary or data")
		}
		target.Close()
		if !restorePG(t, ctx, s, "pg_restore", "--dbname=vms_camera_test", "--clean", "--if-exists", "--no-owner", "--single-transaction", "--exit-on-error", dump) {
			t.Fatal("actual approved TLS restore failed")
		}
		if os.WriteFile(filepath.Join(base, "keys/restored/key-bundle.json"), key, 0600) != nil {
			t.Fatal("exact synthetic key restore failed")
		}
		target = restoreTarget(t, ctx, s)
		defer target.Close()
		if target.DisableCredentialEncryption(ctx) != nil {
			t.Fatal("restored old encryption disable failed")
		}
		if _, e := target.ReserveCredentialEncryptionUse(ctx, credentialOldEnc); e == nil {
			t.Fatal("restored old key writable before PREPARED")
		}
		if credentialUses(t, target, ctx, credentialOldEnc) != r.BackupUses || rehearsalRows(t, target, ctx, 1) != r.History || storedCredentialSecret(t, target, ctx, restoreKeys(t, "restored"), 1) != credentialWrite(t, 0).Secret {
			t.Fatal("restored history/key/snapshot mismatch")
		}
		if control.InspectCredentialMaintenanceHBA(ctx, l, s.Record, p, s.SourceIP) != nil {
			t.Fatal("restore replaced external boundary")
		}
		restoreProof(t, phase)
		return
	}
	if phase == "prepare" {
		if s.Record.State != credentialadmission.Fenced {
			t.Fatal("candidate only from FENCED")
		}
		raw, e := os.ReadFile(filepath.Join(base, "keys/previous/key-bundle.json"))
		var wire map[string]json.RawMessage
		if e != nil || json.Unmarshal(raw, &wire) != nil {
			t.Fatal("protected previous keys absent")
		}
		var enc struct {
			Active string            `json:"active_key_id"`
			Keys   map[string]string `json:"keys"`
		}
		if json.Unmarshal(wire["encryption"], &enc) != nil {
			t.Fatal("synthetic key parse failed")
		}
		var material [32]byte
		var id [8]byte
		if _, e := rand.Read(material[:]); e != nil {
			t.Fatal("synthetic key entropy failed")
		}
		if _, e := rand.Read(id[:]); e != nil {
			t.Fatal("synthetic ID entropy failed")
		}
		enc.Active = "enc-" + hex.EncodeToString(id[:])
		enc.Keys[enc.Active] = base64.StdEncoding.EncodeToString(material[:])
		wire["encryption"], _ = json.Marshal(enc)
		boundarySave(t, filepath.Join(base, "keys/candidate/key-bundle.json"), wire, 0600)
		candidate := restoreKeys(t, "candidate")
		if candidate.CheckRestoreSuccessor(restoreKeys(t, "previous"), restoreKeys(t, "restored")) != nil {
			t.Fatal("unsafe material candidate")
		}
		binding := *s.Record.Binding
		binding.DatabaseID = "66666666-6666-4666-8666-666666666666"
		binding.ActiveEncryptionKeyID = candidate.ActiveEncryptionID()
		binding.KeyBundleSHA256, _, _ = candidate.ProtectedBundleReceipt()
		bad := binding
		bad.ActiveEncryptionKeyID = credentialOldEnc
		if _, e := credentialadmission.NextPrepare(s.Record, bad, "2026-10-07T02:00:00Z"); e == nil {
			t.Fatal("seen encryption ID reused")
		}
		prepared, e := credentialadmission.NextPrepare(s.Record, binding, "2026-10-07T02:00:00Z")
		if e != nil || l.Commit(s.Record, prepared) != nil {
			t.Fatal("durable PREPARED failed")
		}
		target := restoreTarget(t, ctx, s)
		defer target.Close()
		var count int
		if target.pool.QueryRow(ctx, "SELECT count(*) FROM camera.credential_encryption_budgets WHERE key_id=$1", binding.ActiveEncryptionKeyID).Scan(&count) != nil || count != 0 {
			t.Fatal("budget enrolled before PREPARED receipt")
		}
		r.Prepared = prepared
		s.Record = prepared
		saveRestore(t, r)
		boundarySave(t, filepath.Join(base, "state.json"), s, 0600)
		restoreProof(t, phase)
		return
	}
	if phase != "commit" && phase != "retry" {
		t.Fatal("unknown boundary restore phase")
	}
	if !reflect.DeepEqual(s.Record, r.Prepared) {
		t.Fatal("exact interrupted candidate unavailable")
	}
	target := restoreTarget(t, ctx, s)
	candidate := restoreKeys(t, "candidate")
	previous := restoreKeys(t, "previous")
	backup := restoreKeys(t, "restored")
	prepare := func(marker CredentialAdmissionDatabase) error {
		return control.PrepareRestoredCredentialDatabase(ctx, l, s.Record, p, s.SourceIP, target, candidate, previous, backup, marker)
	}
	wrong := r.BackupMarker
	wrong.DatabaseID = "77777777-7777-4777-8777-777777777777"
	if phase == "commit" {
		assertMaintenanceDenied(t, prepare(wrong))
		// Neither FENCED nor altered candidate receipts authorize any mutation.
		fenced, e := credentialadmission.NextFence(s.Record, "88888888-8888-4888-8888-888888888888", "2026-10-07T03:00:00Z")
		if e != nil {
			t.Fatal("negative authority fixture failed")
		}
		assertMaintenanceDenied(t, control.PrepareRestoredCredentialDatabase(ctx, l, fenced, p, s.SourceIP, target, candidate, previous, backup, r.BackupMarker))
		changed := s.Record
		changedBinding := *changed.Binding
		changed.Binding = &changedBinding
		changed.Binding.KeyBundleSHA256 = strings.Repeat("0", 64)
		assertMaintenanceDenied(t, control.PrepareRestoredCredentialDatabase(ctx, l, changed, p, s.SourceIP, target, candidate, previous, backup, r.BackupMarker))
		var enrolled int
		if target.pool.QueryRow(ctx, "SELECT count(*) FROM camera.credential_encryption_budgets WHERE key_id=$1", candidate.ActiveEncryptionID()).Scan(&enrolled) != nil || enrolled != 0 {
			t.Fatal("negative input mutated budget")
		}
	}
	if prepare(r.BackupMarker) != nil {
		t.Fatal("guarded candidate preparation failed")
	}
	var uses int64
	var enabled bool
	if target.pool.QueryRow(ctx, "SELECT uses,enabled FROM camera.credential_encryption_budgets WHERE key_id=$1", candidate.ActiveEncryptionID()).Scan(&uses, &enabled) != nil || uses != 0 || !enabled {
		t.Fatal("candidate budget not fresh")
	}
	if credentialUses(t, target, ctx, credentialOldEnc) != r.BackupUses {
		t.Fatal("old budget reset by preparation")
	}
	if _, e := target.ReserveCredentialEncryptionUse(ctx, credentialOldEnc); e == nil {
		t.Fatal("restored old key still writable")
	}
	if rehearsalRows(t, target, ctx, 1) != r.History || storedCredentialSecret(t, target, ctx, candidate, 1) != credentialWrite(t, 0).Secret {
		t.Fatal("historical ciphertext/HMAC changed")
	}
	if got, e := l.Snapshot(); e != nil || !reflect.DeepEqual(got, r.Prepared) {
		t.Fatal("candidate preparation opened authority")
	}
	if phase == "retry" {
		// Simulate an untrusted/partial candidate use. A retry must refuse rather
		// than silently reset the counter. This consumes a disposable test use only.
		if _, e := target.ReserveCredentialEncryptionUse(ctx, candidate.ActiveEncryptionID()); e != nil {
			t.Fatal("retry negative fixture failed")
		}
		assertMaintenanceDenied(t, prepare(r.BackupMarker))
		// OPEN inspection also refuses this consumed candidate. Its pure
		// verification path cannot enroll, repair or reset anything.
		opened, e := credentialadmission.NextOpen(r.Prepared, "2026-10-07T04:00:00Z")
		if e != nil {
			t.Fatal("negative OPEN fixture failed")
		}
		assertMaintenanceDenied(t, control.AuthorizeRestoredCredentialOpen(ctx, l, r.Prepared, opened, p, s.SourceIP, target, candidate, previous, backup, r.BackupMarker))
		if got, e := l.Snapshot(); e != nil || !reflect.DeepEqual(got, r.Prepared) {
			t.Fatal("used candidate OPEN changed authority")
		}
		if credentialUses(t, target, ctx, candidate.ActiveEncryptionID()) != 1 {
			t.Fatal("retry reset candidate budget")
		}
		var active bool
		if target.pool.QueryRow(ctx, "SELECT enabled FROM camera.credential_encryption_budgets WHERE key_id=$1", credentialOldEnc).Scan(&active) != nil || active {
			t.Fatal("old budget reactivated")
		}
		target.Close()
		if _, e := control.pool.Exec(ctx, "ALTER DATABASE vms_camera_test ALLOW_CONNECTIONS false"); e != nil {
			t.Fatal("final target closure failed")
		}
		if _, e := control.pool.Exec(ctx, "SELECT pg_stat_clear_snapshot()"); e != nil {
			t.Fatal("fresh final activity unavailable")
		}
		var closed bool
		if control.pool.QueryRow(ctx, `SELECT NOT d.datallowconn
 AND (SELECT count(*)=2 AND bool_and(NOT rolcanlogin) FROM pg_roles WHERE rolname IN ('camera_credential_writer','camera_credential_budget'))
 AND NOT EXISTS(SELECT 1 FROM pg_stat_activity WHERE datname='vms_camera_test' OR usename IN ('camera_credential_writer','camera_credential_budget'))
 FROM pg_database d WHERE d.datname='vms_camera_test'`).Scan(&closed) != nil || !closed || confirmMaintenanceFence(l, r.Prepared) != nil {
			t.Fatal("final candidate boundary not closed")
		}
	} else {
		target.Close()
	}
	restoreProof(t, phase)
}
