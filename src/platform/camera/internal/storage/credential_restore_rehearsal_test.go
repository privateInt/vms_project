//go:build linux

package storage

// This is an isolated multi-process rehearsal, not production restore admission.
import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net/url"
	"os"
	"path/filepath"
	"reflect"
	"syscall"
	"testing"
	"time"

	"vms.local/platform/camera/internal/credentialcrypto"
)

const rehearsalState = "/exchange/restore-state.json"

type credentialRestoreState struct {
	First        CredentialMetadata `json:"first"`
	Second       CredentialMetadata `json:"second"`
	OriginalRows string             `json:"original_rows_sha256"`
	NewRows      string             `json:"new_rows_sha256"`
	HighWater    int64              `json:"pre_restore_high_water"`
}

func rehearsalHash(body []byte) string { h := sha256.Sum256(body); return hex.EncodeToString(h[:]) }
func rehearsalRows(t *testing.T, s *Store, ctx context.Context, version int64) string {
	t.Helper()
	var rows string
	if err := s.pool.QueryRow(ctx, `SELECT row_to_json(v)::text||row_to_json(r)::text
 FROM camera.credential_versions v JOIN camera.credential_requests r USING(credential_id,version)
 WHERE v.credential_id='credential-1' AND v.version=$1`, version).Scan(&rows); err != nil {
		t.Fatal("history unavailable")
	}
	return rehearsalHash([]byte(rows))
}
func rehearsalRead(t *testing.T) credentialRestoreState {
	t.Helper()
	b, err := os.ReadFile(rehearsalState)
	if err != nil {
		t.Fatal("rehearsal receipt unavailable")
	}
	var state credentialRestoreState
	if json.Unmarshal(b, &state) != nil || state.First.Version != 1 || len(state.OriginalRows) != 64 {
		t.Fatal("invalid rehearsal receipt")
	}
	return state
}
func rehearsalSave(t *testing.T, state credentialRestoreState) {
	t.Helper()
	b, err := json.Marshal(state)
	if err != nil {
		t.Fatal("receipt encoding failed")
	}
	if os.WriteFile(rehearsalState, b, 0600) != nil {
		t.Fatal("receipt write failed")
	}
}
func rehearsalKeys(t *testing.T, name string) *credentialcrypto.Keyring {
	t.Helper()
	directory := filepath.Join("/keys", name)
	if os.Geteuid() != 10001 {
		t.Fatal("isolated credential process UID required")
	}
	var fs syscall.Statfs_t
	if syscall.Statfs(directory, &fs) != nil || fs.Flags&syscall.MS_RDONLY == 0 {
		t.Fatal("key mount is not read-only")
	}
	path := filepath.Join(directory, "key-bundle.json")
	// The owner can chmod a mode-0400 file on a writable mount. EROFS proves
	// mount protection independently of ordinary Unix write permissions.
	if !errors.Is(os.Chmod(path, 0600), syscall.EROFS) {
		t.Fatal("key mount protection missing")
	}
	k, err := credentialcrypto.LoadKeyBundleFile(path)
	if err != nil {
		t.Fatal("protected synthetic key load failed")
	}
	return k
}
func rehearsalOpen(t *testing.T, ctx context.Context, role string) *Store {
	t.Helper()
	u, err := url.Parse(os.Getenv("CAMERA_TEST_DATABASE_URL"))
	if err != nil {
		t.Fatal("isolated DSN required")
	}
	if role != "" {
		u.User = url.UserPassword(role, os.Getenv("CAMERA_TEST_ROLE_PASSWORD"))
	}
	s, err := Open(ctx, u.String())
	if err != nil {
		t.Fatal("isolated role connection failed")
	}
	t.Cleanup(s.Close)
	return s
}
func rehearsalStore(t *testing.T, ctx context.Context, k *credentialcrypto.Keyring) *CredentialStore {
	t.Helper()
	writer := rehearsalOpen(t, ctx, "camera_credential_writer")
	budget := rehearsalOpen(t, ctx, "camera_credential_budget")
	c, err := newFixtureCredentialStore(writer, budget, k)
	if err != nil {
		t.Fatal("separate role store failed")
	}
	var writerName, budgetName, database string
	if writer.pool.QueryRow(ctx, "SELECT current_user,current_database()").Scan(&writerName, &database) != nil || budget.pool.QueryRow(ctx, "SELECT current_user").Scan(&budgetName) != nil || writerName != "camera_credential_writer" || budgetName != "camera_credential_budget" {
		t.Fatal("role identity mismatch")
	}
	u, _ := url.Parse(os.Getenv("CAMERA_TEST_DATABASE_URL"))
	if database != u.Path[1:] {
		t.Fatal("database identity mismatch")
	}
	return c
}
func rehearsalFenced(t *testing.T, owner *Store, ctx context.Context) {
	t.Helper()
	for _, role := range []string{"camera_credential_writer", "camera_credential_budget"} {
		var allowed bool
		if owner.pool.QueryRow(ctx, "SELECT rolcanlogin FROM pg_roles WHERE rolname=$1", role).Scan(&allowed) != nil || allowed {
			t.Fatal("restore login fence absent")
		}
		u, _ := url.Parse(os.Getenv("CAMERA_TEST_DATABASE_URL"))
		u.User = url.UserPassword(role, os.Getenv("CAMERA_TEST_ROLE_PASSWORD"))
		s, err := Open(ctx, u.String())
		if err == nil {
			s.Close()
			t.Fatal("fenced account authenticated")
		}
	}
	var writers int
	if owner.pool.QueryRow(ctx, "SELECT count(*) FROM pg_stat_activity WHERE usename IN ('camera_credential_writer','camera_credential_budget')").Scan(&writers) != nil || writers != 0 {
		t.Fatal("restore writers not drained")
	}
	var enabled bool
	if owner.pool.QueryRow(ctx, "SELECT enabled FROM camera.credential_encryption_budgets WHERE key_id=$1", credentialOldEnc).Scan(&enabled) != nil || enabled {
		t.Fatal("restored old encryption key enabled")
	}
}
func rehearsalPreserved(t *testing.T, owner *Store, ctx context.Context, state credentialRestoreState, k *credentialcrypto.Keyring) {
	t.Helper()
	if rehearsalRows(t, owner, ctx, 1) != state.OriginalRows {
		t.Fatal("original ciphertext/HMAC receipt changed")
	}
	if storedCredentialSecret(t, owner, ctx, k, 1) != credentialWrite(t, 0).Secret {
		t.Fatal("historical ciphertext unreadable")
	}
	if credentialUses(t, owner, ctx, credentialOldEnc) != 1 || state.HighWater != 3 {
		t.Fatal("snapshot rewind not reproduced")
	}
}

func TestNativeCredentialKeySupplyRestoreRehearsal(t *testing.T) {
	phase := os.Getenv("CAMERA_CREDENTIAL_REHEARSAL_PHASE")
	if phase == "" {
		t.Skip("requires the dedicated isolated DB/key restore runner")
	}
	if os.Getenv("CAMERA_TEST_ENGINE") == "pglite" || os.Getenv("CAMERA_CREDENTIAL_REHEARSAL_ONLY") != "1" {
		t.Fatal("native isolated rehearsal required")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 45*time.Second)
	defer cancel()
	owner := rehearsalOpen(t, ctx, "")
	switch phase {
	case "seed":
		keys := rehearsalKeys(t, "old")
		if _, err := owner.Migrate(ctx); err != nil {
			t.Fatal(err)
		}
		createDeleteDevice(t, owner, ctx, "parent")
		password := os.Getenv("CAMERA_TEST_ROLE_PASSWORD")
		if len(password) != 48 {
			t.Fatal("ephemeral role password required")
		}
		for _, r := range password {
			if !(r >= '0' && r <= '9' || r >= 'a' && r <= 'f') {
				t.Fatal("invalid ephemeral password")
			}
		}
		for _, role := range []string{"camera_credential_writer", "camera_credential_budget"} {
			if _, err := owner.pool.Exec(ctx, "CREATE ROLE "+role+" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD '"+password+"'"); err != nil {
				t.Fatal("fresh role creation failed")
			}
		}
		if owner.ProvisionCredentialRuntime(ctx) != nil || owner.EnrollCredentialEncryptionKey(ctx, keys.ActiveEncryptionID()) != nil {
			t.Fatal("fixture provisioning failed")
		}
		c := rehearsalStore(t, ctx, keys)
		if c.CheckReady(ctx) != nil {
			t.Fatal("seed not ready")
		}
		first, replay, err := c.WriteVersion(ctx, credentialIdentity("create"), credentialWrite(t, 0), authorizeCredentialForTest)
		if err != nil || replay || first.Version != 1 || credentialUses(t, owner, ctx, credentialOldEnc) != 1 {
			t.Fatal("seed write failed")
		}
		rehearsalSave(t, credentialRestoreState{First: first, OriginalRows: rehearsalRows(t, owner, ctx, 1)})
	case "advance":
		state := rehearsalRead(t)
		c := rehearsalStore(t, ctx, rehearsalKeys(t, "old"))
		if _, _, err := c.WriteVersion(ctx, credentialIdentity("lost-after-backup"), credentialWrite(t, 1), authorizeCredentialForTest); err != nil {
			t.Fatal("post-backup write failed")
		}
		if _, err := c.budget.ReserveCredentialEncryptionUse(ctx, credentialOldEnc); err != nil {
			t.Fatal("post-backup reservation failed")
		}
		state.HighWater = credentialUses(t, owner, ctx, credentialOldEnc)
		if state.HighWater != 3 || credentialCounts(t, owner, ctx) != "1:2:2" {
			t.Fatal("post-backup state missing")
		}
		rehearsalSave(t, state)
	case "blocked", "enrolled":
		state := rehearsalRead(t)
		old := rehearsalKeys(t, "restored")
		rehearsalFenced(t, owner, ctx)
		source, err := os.ReadFile("/keys/restored/key-bundle.json")
		if err != nil {
			t.Fatal("restored key missing")
		}
		backup, err := os.ReadFile("/backup-keys/old/key-bundle.json")
		if err != nil || rehearsalHash(source) != rehearsalHash(backup) {
			t.Fatal("key backup mismatch")
		}
		clear(source)
		clear(backup)
		rehearsalPreserved(t, owner, ctx, state, old)
		if credentialCounts(t, owner, ctx) != "1:1:1" {
			t.Fatal("restored snapshot changed")
		}
		c, err := newFixtureCredentialStore(owner, rehearsalOpen(t, ctx, ""), old)
		if err != nil {
			t.Fatal(err)
		}
		credentialError(t, c.CheckReady(ctx), "CREDENTIAL_ENCRYPTION_KEY_UNAVAILABLE")
		_, _, err = c.WriteVersion(ctx, credentialIdentity("old-must-stay-blocked"), credentialWrite(t, 1), authorizeCredentialForTest)
		credentialError(t, err, "CREDENTIAL_ENCRYPTION_KEY_UNAVAILABLE")
		if _, err := credentialcrypto.LoadKeyBundleFile("/keys/absent/key-bundle.json"); !errors.Is(err, credentialcrypto.ErrKeyFile) {
			t.Fatal("missing keys accepted")
		}
		fresh := rehearsalKeys(t, "fresh")
		if fresh.ActiveEncryptionID() != credentialNewEnc || fresh.ActiveIdempotencyID() != credentialNewMac {
			t.Fatal("fresh active keys required")
		}
		freshStore, err := newFixtureCredentialStore(owner, rehearsalOpen(t, ctx, ""), fresh)
		if err != nil {
			t.Fatal(err)
		}
		if phase == "blocked" {
			credentialError(t, freshStore.CheckReady(ctx), "CREDENTIAL_ENCRYPTION_KEY_UNAVAILABLE")
		}
		rehearsalPreserved(t, owner, ctx, state, fresh)
		got, replay, err := freshStore.WriteVersion(ctx, credentialIdentity("create"), credentialWrite(t, 0), authorizeCredentialForTest)
		if err != nil || !replay || !reflect.DeepEqual(got, state.First) {
			t.Fatal("fresh key history incomplete before admission")
		}
		if phase == "enrolled" {
			err = owner.EnrollCredentialEncryptionKey(ctx, fresh.ActiveEncryptionID())
			if err != nil {
				credentialError(t, err, "CREDENTIAL_ENCRYPTION_KEY_ALREADY_ENROLLED")
			}
			if credentialUses(t, owner, ctx, credentialNewEnc) != 0 {
				t.Fatal("interrupted enrollment consumed budget")
			}
			// A new process repeats this phase before LOGIN is enabled. It must not
			// reset the existing budget, even though readiness for the new key exists.
			credentialError(t, owner.EnrollCredentialEncryptionKey(ctx, fresh.ActiveEncryptionID()), "CREDENTIAL_ENCRYPTION_KEY_ALREADY_ENROLLED")
			rehearsalFenced(t, owner, ctx)
		}
	case "resumed", "recreated":
		state := rehearsalRead(t)
		keys := rehearsalKeys(t, "fresh")
		c := rehearsalStore(t, ctx, keys)
		if c.CheckReady(ctx) != nil {
			t.Fatal("fresh resumed store not ready")
		}
		for _, role := range []string{"camera_credential_writer", "camera_credential_budget"} {
			u, _ := url.Parse(os.Getenv("CAMERA_TEST_DATABASE_URL"))
			u.Path = "/vms_camera_test"
			u.User = url.UserPassword(role, os.Getenv("CAMERA_TEST_ROLE_PASSWORD"))
			previous, err := Open(ctx, u.String())
			if err == nil {
				previous.Close()
				t.Fatal("old database still admits credential accounts")
			}
		}
		rehearsalPreserved(t, owner, ctx, state, keys)
		old, err := newFixtureCredentialStore(c.data, c.budget, rehearsalKeys(t, "restored"))
		if err != nil {
			t.Fatal(err)
		}
		credentialError(t, old.CheckReady(ctx), "CREDENTIAL_ENCRYPTION_KEY_UNAVAILABLE")
		expected := int64(1)
		if phase == "recreated" {
			expected = 2
		}
		_, _, err = old.WriteVersion(ctx, credentialIdentity("disabled-old"), credentialWrite(t, expected), authorizeCredentialForTest)
		credentialError(t, err, "CREDENTIAL_ENCRYPTION_KEY_UNAVAILABLE")
		noHistory, err := newFixtureCredentialStore(c.data, c.budget, rehearsalKeys(t, "missing"))
		if err != nil {
			t.Fatal(err)
		}
		before := credentialUses(t, owner, ctx, credentialNewEnc)
		_, _, err = noHistory.WriteVersion(ctx, credentialIdentity("create"), credentialWrite(t, 0), authorizeCredentialForTest)
		credentialError(t, err, "CREDENTIAL_KEY_UNAVAILABLE")
		var envelope credentialcrypto.Envelope
		var use int64
		var policy string
		if owner.pool.QueryRow(ctx, `SELECT encryption_format,encryption_algorithm,encryption_key_id,encryption_use,ciphertext,target_policy_sha256 FROM camera.credential_versions WHERE version=1`).Scan(&envelope.FormatVersion, &envelope.Algorithm, &envelope.KeyID, &use, &envelope.Ciphertext, &policy) != nil {
			t.Fatal("old envelope missing")
		}
		envelope.EncryptionUse = uint64(use)
		if _, err := noHistory.keys.Open(credentialcrypto.Context{ScopeID: "scope-1", DeviceID: "parent", CredentialID: "credential-1", CredentialVersion: 1, TargetPolicySHA256: policy}, envelope); !errors.Is(err, credentialcrypto.ErrKeyUnavailable) {
			t.Fatal("missing historical encryption key accepted")
		}
		replayed, replay, err := c.WriteVersion(ctx, credentialIdentity("create"), credentialWrite(t, 0), authorizeCredentialForTest)
		if err != nil || !replay || !reflect.DeepEqual(replayed, state.First) || credentialUses(t, owner, ctx, credentialNewEnc) != before {
			t.Fatal("historical HMAC replay failed")
		}
		next, replay, err := c.WriteVersion(ctx, credentialIdentity("fresh-after-restore"), credentialWrite(t, 1), authorizeCredentialForTest)
		if err != nil || next.Version != 2 || replay != (phase == "recreated") {
			t.Fatal("fresh write/replay failed")
		}
		if phase == "resumed" {
			state.Second = next
			state.NewRows = rehearsalRows(t, owner, ctx, 2)
			rehearsalSave(t, state)
		} else if !reflect.DeepEqual(next, state.Second) || rehearsalRows(t, owner, ctx, 2) != state.NewRows {
			t.Fatal("new durable receipt changed")
		}
		again, replay, err := c.WriteVersion(ctx, credentialIdentity("fresh-after-restore"), credentialWrite(t, 1), authorizeCredentialForTest)
		if err != nil || !replay || !reflect.DeepEqual(next, again) || credentialUses(t, owner, ctx, credentialNewEnc) != 1 || credentialUses(t, owner, ctx, credentialOldEnc) != 1 || credentialCounts(t, owner, ctx) != "1:2:2" {
			t.Fatal("resumed budget/replay mismatch")
		}
		var key string
		var counter int64
		if owner.pool.QueryRow(ctx, "SELECT encryption_key_id,encryption_use FROM camera.credential_versions WHERE version=2").Scan(&key, &counter) != nil || key != credentialNewEnc || counter != 1 {
			t.Fatal("restored write reused old key")
		}
		if storedCredentialSecret(t, owner, ctx, keys, 2) != credentialWrite(t, 1).Secret {
			t.Fatal("new ciphertext unreadable")
		}
	default:
		t.Fatal("unknown rehearsal phase")
	}
	t.Log("CREDENTIAL_REHEARSAL_PHASE_OK:" + phase)
}
