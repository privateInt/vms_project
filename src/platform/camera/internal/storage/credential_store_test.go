package storage

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"reflect"
	"strings"
	"testing"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"vms.local/platform/camera/internal/credentialcrypto"
)

const credentialOldEnc = "enc-1111111111111161"
const credentialNewEnc = "enc-3333333333333363"
const credentialOldMac = "idem-2222222222222262"
const credentialNewMac = "idem-4444444444444464"

func credentialTestKeys(t *testing.T, rotated, retain bool) *credentialcrypto.Keyring {
	t.Helper()
	enc := map[string]string{}
	mac := map[string]string{}
	activeEnc, activeMac := credentialOldEnc, credentialOldMac
	if !rotated || retain {
		enc[credentialOldEnc] = base64.StdEncoding.EncodeToString(bytes.Repeat([]byte{61}, 32))
		mac[credentialOldMac] = base64.StdEncoding.EncodeToString(bytes.Repeat([]byte{62}, 32))
	}
	if rotated {
		enc[credentialNewEnc] = base64.StdEncoding.EncodeToString(bytes.Repeat([]byte{63}, 32))
		mac[credentialNewMac] = base64.StdEncoding.EncodeToString(bytes.Repeat([]byte{64}, 32))
		activeEnc, activeMac = credentialNewEnc, credentialNewMac
	}
	wire, _ := json.Marshal(map[string]any{"format_version": 1, "encryption": map[string]any{"active_key_id": activeEnc, "keys": enc}, "idempotency": map[string]any{"active_key_id": activeMac, "keys": mac}})
	k, err := credentialcrypto.ParseKeyBundle(wire)
	clear(wire)
	if err != nil {
		t.Fatal(err)
	}
	return k
}
func credentialFixture(t *testing.T) (*Store, *CredentialStore, context.Context) {
	t.Helper()
	s, ctx := testStore(t)
	if _, err := s.Migrate(ctx); err != nil {
		t.Fatal(err)
	}
	createDeleteDevice(t, s, ctx, "parent")
	budget, err := Open(ctx, os.Getenv("CAMERA_TEST_DATABASE_URL"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(budget.Close)
	keys := credentialTestKeys(t, false, false)
	if err = s.EnrollCredentialEncryptionKey(ctx, credentialOldEnc); err != nil {
		t.Fatal(err)
	}
	c, err := newFixtureCredentialStore(s, budget, keys)
	if err != nil {
		t.Fatal(err)
	}
	return s, c, ctx
}
func credentialIdentity(key string) CredentialIdentity {
	return CredentialIdentity{"scope-1", "admin-1", key}
}
func credentialWrite(t *testing.T, version int64) CredentialWrite {
	t.Helper()
	secret, err := credentialcrypto.NewSecret("synthetic-private-user", "synthetic-private-password")
	if err != nil {
		t.Fatal(err)
	}
	return CredentialWrite{"credential-1", "parent", version, CredentialTarget{"RTSP", "camera.example.invalid", 554}, secret}
}
func authorizeCredentialForTest(_ context.Context, _ pgx.Tx, a CredentialAccess) (bool, error) {
	return a.ScopeID == "scope-1" && a.PrincipalID == "admin-1" && a.DeviceID == "parent" && (a.Operation == "MANAGE" || a.Operation == "REFERENCE"), nil
}
func unusedCredentialForTest(context.Context, pgx.Tx, CredentialReference) (CredentialUsage, error) {
	return CredentialUsageUnused, nil
}
func credentialError(t *testing.T, err error, code string) {
	t.Helper()
	var safe *Error
	if !errors.As(err, &safe) || safe.Code != code {
		t.Fatalf("wanted %s got %v", code, err)
	}
	for _, format := range []string{"%v", "%+v", "%#v"} {
		text := fmt.Sprintf(format, err)
		if strings.Contains(text, "synthetic-private-") {
			t.Fatal("private error exposed")
		}
	}
}
func credentialUses(t *testing.T, s *Store, ctx context.Context, id string) int64 {
	t.Helper()
	var uses int64
	if err := s.pool.QueryRow(ctx, "SELECT uses FROM camera.credential_encryption_budgets WHERE key_id=$1", id).Scan(&uses); err != nil {
		t.Fatal(err)
	}
	return uses
}
func credentialCounts(t *testing.T, s *Store, ctx context.Context) string {
	t.Helper()
	var value string
	if err := s.pool.QueryRow(ctx, `SELECT (SELECT count(*) FROM camera.credentials)::text||':'||(SELECT count(*) FROM camera.credential_versions)::text||':'||(SELECT count(*) FROM camera.credential_requests)::text`).Scan(&value); err != nil {
		t.Fatal(err)
	}
	return value
}
func storedCredentialSecret(t *testing.T, s *Store, ctx context.Context, k *credentialcrypto.Keyring, version int64) credentialcrypto.Secret {
	t.Helper()
	var e credentialcrypto.Envelope
	var use int64
	var policy string
	if err := s.pool.QueryRow(ctx, `SELECT encryption_format,encryption_algorithm,encryption_key_id,encryption_use,ciphertext,target_policy_sha256
FROM camera.credential_versions WHERE credential_id='credential-1' AND version=$1`, version).Scan(&e.FormatVersion, &e.Algorithm, &e.KeyID, &use, &e.Ciphertext, &policy); err != nil {
		t.Fatal(err)
	}
	e.EncryptionUse = uint64(use)
	secret, err := k.Open(credentialcrypto.Context{ScopeID: "scope-1", DeviceID: "parent", CredentialID: "credential-1", CredentialVersion: version, TargetPolicySHA256: policy}, e)
	if err != nil {
		t.Fatal(err)
	}
	return secret
}

func TestCredentialTargetAndPrivateStoreConfiguration(t *testing.T) {
	for _, host := range []string{"192.168.0.10", "2001:db8::10", "::ffff:192.0.2.10", "camera.example.invalid", "CAMERA.example.invalid"} {
		if !(CredentialTarget{"RTSP", host, 554}).valid() {
			t.Fatal("valid target rejected", host)
		}
	}
	for _, host := range []string{"", "localhost", "127.1", "0177.0.0.1", "0x7f.0.0.1", "2130706433", "256.1.1.1", "camera.invalid.", "camera..invalid", "camera@example.invalid", "rtsp://camera.invalid", "camera.invalid:554", "[2001:db8::10]", "fe80::1%eth0", "cam_1.example.invalid", "카메라.invalid", "camera.invalid\n", "camera.invalid/path"} {
		if (CredentialTarget{"RTSP", host, 554}).valid() {
			t.Fatal("invalid target accepted")
		}
	}
	for _, target := range []CredentialTarget{{"HTTP", "camera.invalid", 554}, {"RTSP", "camera.invalid", 0}, {"RTSP", "camera.invalid", 65536}} {
		if target.valid() {
			t.Fatal("invalid target accepted")
		}
	}
	if _, err := newFixtureCredentialStore(nil, nil, nil); err == nil {
		t.Fatal("missing stores accepted")
	}
	if _, err := newFixtureCredentialStore(&Store{}, &Store{}, credentialTestKeys(t, false, false)); err == nil {
		t.Fatal("empty pools accepted")
	}
	// Lazy pools verify configuration without contacting any database.
	pool, err := pgxpool.New(context.Background(), "postgres://writer@db.invalid:5432/test?sslmode=disable")
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	if _, err := newFixtureCredentialStore(&Store{pool: pool}, &Store{pool: pool}, credentialTestKeys(t, false, false)); err == nil {
		t.Fatal("shared pool accepted through distinct wrappers")
	}
	for _, value := range []any{CredentialStore{}, &CredentialStore{}} {
		if !strings.Contains(fmt.Sprintf("%#v", value), "redacted") {
			t.Fatal("store formatting not private")
		}
		if _, err := json.Marshal(value); !errors.Is(err, credentialcrypto.ErrDisclosure) {
			t.Fatal("store serialized")
		}
	}
}

func TestCredentialVersionPersistenceAndSafeReplay(t *testing.T) {
	s, c, ctx := credentialFixture(t)
	w := credentialWrite(t, 0)
	first, replay, err := c.WriteVersion(ctx, credentialIdentity("create"), w, authorizeCredentialForTest)
	if err != nil || replay || first.Version != 1 || first.RevokedAt != nil {
		t.Fatalf("write: %v", err)
	}
	if secret := storedCredentialSecret(t, s, ctx, c.keys, 1); secret.Username() != w.Secret.Username() || secret.Password() != w.Secret.Password() {
		t.Fatal("secret mismatch")
	}
	uses := credentialUses(t, s, ctx, credentialOldEnc)
	again, replay, err := c.WriteVersion(ctx, credentialIdentity("create"), w, authorizeCredentialForTest)
	if err != nil || !replay || !reflect.DeepEqual(first, again) || credentialUses(t, s, ctx, credentialOldEnc) != uses {
		t.Fatal("stable replay failed", err)
	}
	changed := w
	changed.Secret, _ = credentialcrypto.NewSecret(w.Secret.Username(), "synthetic-private-different")
	_, _, err = c.WriteVersion(ctx, credentialIdentity("create"), changed, authorizeCredentialForTest)
	credentialError(t, err, "IDEMPOTENCY_CONFLICT")
	changed = w
	changed.Target.Port = 8554
	_, _, err = c.WriteVersion(ctx, credentialIdentity("create"), changed, authorizeCredentialForTest)
	credentialError(t, err, "IDEMPOTENCY_CONFLICT")
	var rows string
	if err = s.pool.QueryRow(ctx, `SELECT (SELECT row_to_json(c)::text FROM camera.credentials c)||
(SELECT row_to_json(v)::text FROM camera.credential_versions v)||
(SELECT row_to_json(r)::text FROM camera.credential_requests r)`).Scan(&rows); err != nil {
		t.Fatal(err)
	}
	for _, private := range []string{w.Secret.Username(), w.Secret.Password(), "\"username\"", "\"password\"", "request_body", "response_body"} {
		if strings.Contains(rows, private) {
			t.Fatal("plaintext/private request archived")
		}
	}
	public, _ := json.Marshal(first)
	if bytes.Contains(public, []byte(w.Target.Host)) {
		t.Fatal("target returned")
	}
	if credentialCounts(t, s, ctx) != "1:1:1" {
		t.Fatal("replay changed rows")
	}
	if _, err = newFixtureCredentialStore(s, s, c.keys); err == nil {
		t.Fatal("shared budget pool accepted")
	}
}

func TestCredentialImmutableVersionsAndExactTarget(t *testing.T) {
	s, c, ctx := credentialFixture(t)
	w := credentialWrite(t, 0)
	if _, _, err := c.WriteVersion(ctx, credentialIdentity("create"), w, authorizeCredentialForTest); err != nil {
		t.Fatal(err)
	}
	next := credentialWrite(t, 1)
	next.Secret, _ = credentialcrypto.NewSecret("synthetic-private-new-user", "synthetic-private-new-password")
	next.Target.Port = 8554
	m, _, err := c.WriteVersion(ctx, credentialIdentity("rotate"), next, authorizeCredentialForTest)
	if err != nil || m.Version != 2 {
		t.Fatal("append failed", err)
	}
	if storedCredentialSecret(t, s, ctx, c.keys, 1) != w.Secret || storedCredentialSecret(t, s, ctx, c.keys, 2) != next.Secret {
		t.Fatal("old version changed")
	}
	for _, scenario := range []struct {
		version int64
		target  CredentialTarget
		want    string
	}{{1, w.Target, ""}, {2, next.Target, ""}, {1, next.Target, "CREDENTIAL_UNAVAILABLE"}, {2, w.Target, "CREDENTIAL_UNAVAILABLE"}, {3, next.Target, "CREDENTIAL_UNAVAILABLE"}} {
		_, err := c.CheckReference(ctx, credentialIdentity(""), CredentialReference{"credential-1", "parent", scenario.version}, scenario.target, authorizeCredentialForTest)
		if scenario.want == "" {
			if err != nil {
				t.Fatal(err)
			}
		} else {
			credentialError(t, err, scenario.want)
		}
	}
	_, _, err = c.WriteVersion(ctx, credentialIdentity("stale"), credentialWrite(t, 1), authorizeCredentialForTest)
	credentialError(t, err, "CREDENTIAL_VERSION_CONFLICT")
	_, _, err = c.WriteVersion(ctx, credentialIdentity("duplicate"), w, authorizeCredentialForTest)
	credentialError(t, err, "CREDENTIAL_EXISTS")
	for _, query := range []string{"UPDATE camera.credential_versions SET host='other.invalid'", "UPDATE camera.credential_versions SET ciphertext='\\x00'", "UPDATE camera.credentials SET head_version=1", "UPDATE camera.credentials SET scope_id='scope-2'"} {
		if _, err = s.pool.Exec(ctx, query); stateCode(err) != "23514" {
			t.Fatal("immutable update accepted", err)
		}
	}
}

func TestCredentialAuthorizationAppliesToReplayAndReference(t *testing.T) {
	s, c, ctx := credentialFixture(t)
	w := credentialWrite(t, 0)
	if _, _, err := c.WriteVersion(ctx, credentialIdentity("create"), w, authorizeCredentialForTest); err != nil {
		t.Fatal(err)
	}
	before := credentialCounts(t, s, ctx)
	uses := credentialUses(t, s, ctx, credentialOldEnc)
	for _, guard := range []CredentialAuthorizer{nil, func(context.Context, pgx.Tx, CredentialAccess) (bool, error) { return false, nil }, func(context.Context, pgx.Tx, CredentialAccess) (bool, error) {
		return true, errors.New("synthetic-private-password")
	}} {
		_, _, err := c.WriteVersion(ctx, credentialIdentity("create"), w, guard)
		if guard == nil {
			credentialError(t, err, "CREDENTIAL_AUTHORIZATION_UNAVAILABLE")
		} else if err == nil {
			t.Fatal("denied replay accepted")
		}
		if _, err = c.CheckReference(ctx, credentialIdentity(""), CredentialReference{"credential-1", "parent", 1}, w.Target, guard); err == nil {
			t.Fatal("denied reference accepted")
		}
	}
	for _, identity := range []CredentialIdentity{{"scope-2", "admin-1", "other"}, {"scope-1", "other-admin", "other"}} {
		_, _, err := c.WriteVersion(ctx, identity, w, authorizeCredentialForTest)
		credentialError(t, err, "CREDENTIAL_UNAVAILABLE")
	}
	if credentialCounts(t, s, ctx) != before || credentialUses(t, s, ctx, credentialOldEnc) != uses {
		t.Fatal("denied request mutated data/budget")
	}
}

func TestCredentialRevokeGuardAndParentProtection(t *testing.T) {
	s, c, ctx := credentialFixture(t)
	w := credentialWrite(t, 0)
	created, _, err := c.WriteVersion(ctx, credentialIdentity("create"), w, authorizeCredentialForTest)
	if err != nil {
		t.Fatal(err)
	}
	r := CredentialReference{"credential-1", "parent", 1}
	_, _, err = s.DeleteDevice(ctx, "p", "delete-parent", "parent", deviceDeleteInput(1), unusedDeviceForTest)
	credentialError(t, err, "DEVICE_IN_USE")
	if _, err = s.pool.Exec(ctx, "UPDATE camera.devices SET deleted_at=clock_timestamp(),updated_at=clock_timestamp(),version=version+1 WHERE device_id='parent'"); stateCode(err) != "23514" {
		t.Fatal("direct parent deletion accepted", err)
	}
	for _, guard := range []CredentialRevokeGuard{nil, func(context.Context, pgx.Tx, CredentialReference) (CredentialUsage, error) {
		return CredentialUsageUnknown, nil
	}, func(context.Context, pgx.Tx, CredentialReference) (CredentialUsage, error) {
		return CredentialUsageInUse, nil
	}, func(context.Context, pgx.Tx, CredentialReference) (CredentialUsage, error) {
		return CredentialUsageUnused, errors.New("synthetic-private-password")
	}} {
		_, _, err = c.RevokeVersion(ctx, credentialIdentity("revoke"), r, authorizeCredentialForTest, guard)
		if err == nil {
			t.Fatal("uncertain/in-use revoke accepted")
		}
	}
	if credentialCounts(t, s, ctx) != "1:1:1" {
		t.Fatal("failed revoke persisted")
	}
	revoked, replay, err := c.RevokeVersion(ctx, credentialIdentity("revoke"), r, authorizeCredentialForTest, unusedCredentialForTest)
	if err != nil || replay || revoked.RevokedAt == nil || revoked.RevokedAt.Before(revoked.CreatedAt) {
		t.Fatal("revoke failed", err)
	}
	if _, err = c.CheckReference(ctx, credentialIdentity(""), r, w.Target, authorizeCredentialForTest); err == nil {
		t.Fatal("revoked reference accepted")
	}
	if _, err = s.pool.Exec(ctx, "UPDATE camera.credential_versions SET revoked_at=NULL"); stateCode(err) != "23514" {
		t.Fatal("unrevoke accepted")
	}
	if got, replay, err := c.RevokeVersion(ctx, credentialIdentity("revoke"), r, authorizeCredentialForTest, nil); err != nil || !replay || !reflect.DeepEqual(got, revoked) {
		t.Fatal("revoke replay failed", err)
	}
	if _, _, err = s.DeleteDevice(ctx, "p", "delete-parent", "parent", deviceDeleteInput(1), unusedDeviceForTest); err != nil {
		t.Fatal("parent after release", err)
	}
	if got, replay, err := c.WriteVersion(ctx, credentialIdentity("create"), w, authorizeCredentialForTest); err != nil || !replay || !reflect.DeepEqual(got, created) {
		t.Fatal("historical write replay reactivated data", err)
	}
	_, _, err = c.WriteVersion(ctx, credentialIdentity("append"), credentialWrite(t, 1), authorizeCredentialForTest)
	credentialError(t, err, "DEVICE_UNAVAILABLE")
	if storedCredentialSecret(t, s, ctx, c.keys, 1) != w.Secret {
		t.Fatal("revoke destroyed history")
	}
}

func TestCredentialMutationFailureKeepsCommittedBudget(t *testing.T) {
	s, c, ctx := credentialFixture(t)
	w := credentialWrite(t, 0)
	for _, table := range []string{"credential_versions", "credential_requests"} {
		t.Run(table, func(t *testing.T) {
			if _, err := s.pool.Exec(ctx, `CREATE FUNCTION camera.fail_private_insert() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic-private-password'; END $$;
CREATE TRIGGER fail_private_insert BEFORE INSERT ON camera.`+table+` FOR EACH ROW EXECUTE FUNCTION camera.fail_private_insert()`); err != nil {
				t.Fatal(err)
			}
			before := credentialUses(t, s, ctx, credentialOldEnc)
			_, _, err := c.WriteVersion(ctx, credentialIdentity("retry-"+table), w, authorizeCredentialForTest)
			credentialError(t, err, "CREDENTIAL_STORE_UNAVAILABLE")
			if credentialUses(t, s, ctx, credentialOldEnc) != before+1 || credentialCounts(t, s, ctx) != "0:0:0" {
				t.Fatal("rollback reset budget or left data")
			}
			if _, err = s.pool.Exec(ctx, "DROP TRIGGER fail_private_insert ON camera."+table+"; DROP FUNCTION camera.fail_private_insert()"); err != nil {
				t.Fatal(err)
			}
		})
	}
	got, replay, err := c.WriteVersion(ctx, credentialIdentity("retry-credential_requests"), w, authorizeCredentialForTest)
	if err != nil || replay || got.Version != 1 {
		t.Fatal("failure-key retry failed", err)
	}
	if credentialUses(t, s, ctx, credentialOldEnc) != 3 {
		t.Fatal("committed uses not preserved")
	}
}

func TestCredentialBudgetBoundsAndDisabledKey(t *testing.T) {
	s, c, ctx := credentialFixture(t)
	if err := c.CheckReady(ctx); err != nil {
		t.Fatal(err)
	}
	if credentialUses(t, s, ctx, credentialOldEnc) != 0 {
		t.Fatal("readiness consumed budget")
	}
	if err := s.EnrollCredentialEncryptionKey(ctx, credentialOldEnc); err == nil {
		t.Fatal("key enrollment reset accepted")
	}
	if _, err := s.pool.Exec(ctx, "UPDATE camera.credential_encryption_budgets SET uses=4294967294"); err != nil {
		t.Fatal(err)
	}
	reservation, err := c.budget.ReserveCredentialEncryptionUse(ctx, credentialOldEnc)
	if err != nil || reservation.Use != credentialcrypto.MaxEncryptionUse {
		t.Fatal("boundary reserve failed", err)
	}
	_, err = c.budget.ReserveCredentialEncryptionUse(ctx, credentialOldEnc)
	credentialError(t, err, "CREDENTIAL_ENCRYPTION_BUDGET_EXHAUSTED")
	if _, err = s.pool.Exec(ctx, "UPDATE camera.credential_encryption_budgets SET uses=0"); stateCode(err) != "23514" {
		t.Fatal("budget reset accepted")
	}
	if err = s.DisableCredentialEncryption(ctx); err != nil {
		t.Fatal(err)
	}
	if c.CheckReady(ctx) == nil {
		t.Fatal("disabled key storage marked ready")
	}
	_, _, err = c.WriteVersion(ctx, credentialIdentity("disabled"), credentialWrite(t, 0), authorizeCredentialForTest)
	credentialError(t, err, "CREDENTIAL_ENCRYPTION_KEY_UNAVAILABLE")
	if credentialCounts(t, s, ctx) != "0:0:0" {
		t.Fatal("disabled key created data")
	}
	if _, err = s.pool.Exec(ctx, "UPDATE camera.credential_encryption_budgets SET enabled=true"); stateCode(err) != "23514" {
		t.Fatal("disabled key reactivated")
	}
}

func TestCredentialRestartAndHistoricalFingerprintKeys(t *testing.T) {
	s, c, ctx := credentialFixture(t)
	w := credentialWrite(t, 0)
	first, _, err := c.WriteVersion(ctx, credentialIdentity("create"), w, authorizeCredentialForTest)
	if err != nil {
		t.Fatal(err)
	}
	before := credentialUses(t, s, ctx, credentialOldEnc)
	data, err := Open(ctx, os.Getenv("CAMERA_TEST_DATABASE_URL"))
	if err != nil {
		t.Fatal(err)
	}
	defer data.Close()
	budget, err := Open(ctx, os.Getenv("CAMERA_TEST_DATABASE_URL"))
	if err != nil {
		t.Fatal(err)
	}
	defer budget.Close()
	reopened, err := newFixtureCredentialStore(data, budget, credentialTestKeys(t, true, true))
	if err != nil {
		t.Fatal(err)
	}
	if again, replay, err := reopened.WriteVersion(ctx, credentialIdentity("create"), w, authorizeCredentialForTest); err != nil || !replay || !reflect.DeepEqual(again, first) {
		t.Fatal("historical fingerprint replay failed", err)
	}
	if storedCredentialSecret(t, s, ctx, reopened.keys, 1) != w.Secret || credentialUses(t, s, ctx, credentialOldEnc) != before {
		t.Fatal("reopening changed data/budget")
	}
	if err = s.EnrollCredentialEncryptionKey(ctx, credentialNewEnc); err != nil {
		t.Fatal(err)
	}
	if next, _, err := reopened.WriteVersion(ctx, credentialIdentity("rotate-key"), credentialWrite(t, 1), authorizeCredentialForTest); err != nil || next.Version != 2 {
		t.Fatal("new key write failed", err)
	}
	missing, err := newFixtureCredentialStore(data, budget, credentialTestKeys(t, true, false))
	if err != nil {
		t.Fatal(err)
	}
	_, _, err = missing.WriteVersion(ctx, credentialIdentity("create"), w, authorizeCredentialForTest)
	credentialError(t, err, "CREDENTIAL_KEY_UNAVAILABLE")
	if credentialUses(t, s, ctx, credentialNewEnc) != 1 {
		t.Fatal("failed historical replay reserved encryption")
	}
}

func TestCredentialPermissionRecheckedAfterReservation(t *testing.T) {
	s, c, ctx := credentialFixture(t)
	calls := 0
	guard := func(context.Context, pgx.Tx, CredentialAccess) (bool, error) { calls++; return calls == 1, nil }
	_, _, err := c.WriteVersion(ctx, credentialIdentity("retry"), credentialWrite(t, 0), guard)
	credentialError(t, err, "CREDENTIAL_UNAVAILABLE")
	if calls != 2 || credentialCounts(t, s, ctx) != "0:0:0" || credentialUses(t, s, ctx, credentialOldEnc) != 1 {
		t.Fatal("changed permission admitted write or reset budget")
	}
	if _, replay, err := c.WriteVersion(ctx, credentialIdentity("retry"), credentialWrite(t, 0), authorizeCredentialForTest); err != nil || replay {
		t.Fatal("permission recovery retry failed", err)
	}
}
