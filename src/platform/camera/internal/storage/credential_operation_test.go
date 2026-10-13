package storage

import (
	"context"
	"errors"
	"strings"
	"testing"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"vms.local/platform/camera/internal/credentialadmission"
	"vms.local/platform/camera/internal/credentialcrypto"
)

// This guard exists only in _test.go for the accepted legacy schema-8 regression
// suite. It is NOT an admission/restore proof and is not available to callers.
type fixtureCredentialGuard struct{ closed *int }
type fixtureCredentialLease struct{ closed *int }

func (g fixtureCredentialGuard) acquire(ctx context.Context, c *CredentialStore) (credentialOperationLease, error) {
	if err := c.data.checkMigrationReady(ctx); err != nil {
		return nil, err
	}
	return fixtureCredentialLease{g.closed}, nil
}
func (fixtureCredentialLease) Check(ctx context.Context) error { return ctx.Err() }
func (l fixtureCredentialLease) CheckTx(ctx context.Context, _ pgx.Tx, _ string) error {
	return l.Check(ctx)
}
func (l fixtureCredentialLease) Close() error {
	if l.closed != nil {
		*l.closed++
	}
	return nil
}
func newFixtureCredentialStore(data, budget *Store, keys *credentialcrypto.Keyring) (*CredentialStore, error) {
	c, err := NewCredentialStore(data, budget, keys)
	if err == nil {
		c.admission = fixtureCredentialGuard{}
	}
	return c, err
}

func assertAdmissionDenied(t *testing.T, err error) {
	t.Helper()
	var safe *Error
	if !errors.As(err, &safe) || safe.Code != "CREDENTIAL_ADMISSION_UNAVAILABLE" || errors.Unwrap(err) != nil {
		t.Fatal("fixed, cause-free admission denial required", err)
	}
}

// Nil pools would panic if any business DB path were reached. All valid inputs
// and callback-free replays must be blocked even on a manually empty store.
func TestCredentialOperationRequiresLeaseWithoutIO(t *testing.T) {
	for _, c := range []*CredentialStore{nil, {}, {keys: credentialTestKeys(t, false, false)}} {
		_, _, err := c.WriteVersion(context.Background(), credentialIdentity("denied-write"), credentialWrite(t, 0), authorizeCredentialForTest)
		assertAdmissionDenied(t, err)
		_, err = c.CheckReference(context.Background(), credentialIdentity(""), CredentialReference{"credential-1", "parent", 1}, credentialWrite(t, 0).Target, authorizeCredentialForTest)
		assertAdmissionDenied(t, err)
		_, _, err = c.RevokeVersion(context.Background(), credentialIdentity("denied-revoke"), CredentialReference{"credential-1", "parent", 1}, authorizeCredentialForTest, unusedCredentialForTest)
		assertAdmissionDenied(t, err)
		assertAdmissionDenied(t, c.CheckReady(context.Background()))
	}
}

func TestCredentialOperationPinsOwnedPolicy(t *testing.T) {
	pools := []*pgxpool.Pool{}
	for _, role := range []string{"camera_credential_writer", "camera_credential_budget"} {
		p, err := pgxpool.New(context.Background(), "postgres://"+role+":synthetic@127.0.0.1:5432/vms_camera_test?sslmode=disable")
		if err != nil {
			t.Fatal(err)
		}
		defer p.Close()
		pools = append(pools, p)
	}
	p, _ := NewCredentialEndpoint("127.0.0.1", 5432, "vms_camera_test", "disable", "", nil)
	hash, _ := CredentialAdmissionMigrationsSHA256()
	r, _ := credentialadmission.NewFenced("11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222", "2026-10-07T00:00:00Z")
	r, _ = credentialadmission.NextPrepare(r, credentialadmission.Binding{DatabaseID: "33333333-3333-4333-8333-333333333333", DatabaseName: "vms_camera_test", SchemaVersion: 9, MigrationSetSHA256: hash, EndpointProfileSHA256: p.SHA256(), KeyBundleSHA256: strings.Repeat("a", 64), ActiveEncryptionKeyID: credentialOldEnc, ActiveIdempotencyKeyID: credentialOldMac, WriterRole: "camera_credential_writer", BudgetRole: "camera_credential_budget"}, r.WrittenAt)
	r, _ = credentialadmission.NextOpen(r, r.WrittenAt)
	policy := credentialadmission.Policy{Directory: "/missing-reviewed-authority", OwnerUID: 0, RuntimeGID: 10001, LockIdentity: credentialadmission.LockIdentity{Device: 1, Inode: 2}}
	c, err := NewAdmittedCredentialStore(&Store{pool: pools[0]}, &Store{pool: pools[1]}, credentialTestKeys(t, false, false), policy, r, p)
	if err != nil {
		t.Fatal(err)
	}
	g := c.admission.(*credentialFileGuard)
	unadmitted, err := NewCredentialStore(c.data, c.budget, c.keys)
	if err != nil {
		t.Fatal(err)
	}
	assertAdmissionDenied(t, unadmitted.CheckReady(context.Background()))
	r.Binding.KeyBundleSHA256 = strings.Repeat("b", 64)
	r.SeenEncryptionKeyIDs[0] = "enc-ffffffffffffffff"
	policy.Directory = "/changed"
	if g.expected.Binding.KeyBundleSHA256 != strings.Repeat("a", 64) || g.expected.SeenEncryptionKeyIDs[0] != credentialOldEnc || g.policy.Directory != "/missing-reviewed-authority" {
		t.Fatal("caller repinned operation guard")
	}
	assertAdmissionDenied(t, c.CheckReady(context.Background())) // mandatory lease deadline, no DB IO
	for _, state := range []credentialadmission.State{credentialadmission.Fenced, credentialadmission.Prepared} {
		bad := g.expected
		bad.State = state
		if _, err := NewAdmittedCredentialStore(c.data, c.budget, c.keys, g.policy, bad, p); err == nil {
			t.Fatal("non-OPEN constructor accepted")
		}
	}
}

func TestCredentialOperationLeaseReleasedOnErrorAndPanic(t *testing.T) {
	owner, c, ctx := credentialFixture(t)
	closed := 0
	c.admission = fixtureCredentialGuard{&closed}
	before := credentialCounts(t, owner, ctx)
	_, _, err := c.WriteVersion(ctx, credentialIdentity("auth-error"), credentialWrite(t, 0), nil)
	credentialError(t, err, "CREDENTIAL_AUTHORIZATION_UNAVAILABLE")
	if closed != 1 {
		t.Fatal("error leaked operation lease")
	}
	func() {
		defer func() {
			if recover() == nil {
				t.Fatal("panic hidden")
			}
		}()
		_, _, _ = c.WriteVersion(ctx, credentialIdentity("auth-panic"), credentialWrite(t, 0), func(context.Context, pgx.Tx, CredentialAccess) (bool, error) { panic("synthetic callback panic") })
	}()
	if closed != 2 || credentialCounts(t, owner, ctx) != before || c.data.pool.Stat().AcquiredConns() != 0 {
		t.Fatal("panic leaked transaction or lease")
	}
	canceled, cancel := context.WithCancel(ctx)
	cancel()
	_, _, err = c.WriteVersion(canceled, credentialIdentity("canceled"), credentialWrite(t, 0), authorizeCredentialForTest)
	assertAdmissionDenied(t, err)
	if closed != 2 || credentialUses(t, owner, ctx, credentialOldEnc) != 0 {
		t.Fatal("canceled request acquired lease or budget")
	}
}

// PostgreSQL comma-separated privilege lists mean ANY, not ALL. Exercise each
// required privilege independently against the actual non-owner writer role.
func TestNativeCredentialOperationRequiredGrants(t *testing.T) {
	owner, writer, budget, ctx, _ := admissionStores(t)
	if err := owner.ProvisionCredentialRuntime(ctx); err != nil {
		t.Fatal(err)
	}
	check := func(s *Store, role string) error {
		tx, err := s.pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadOnly})
		if err != nil {
			return err
		}
		defer tx.Rollback(context.Background())
		return checkCredentialRuntimePermissionsTx(ctx, tx, role)
	}
	if check(writer, "camera_credential_writer") != nil || check(budget, "camera_credential_budget") != nil {
		t.Fatal("native granted roles denied")
	}
	for _, privilege := range []string{"INSERT ON camera.credentials", "INSERT ON camera.credential_versions", "INSERT ON camera.credential_requests", "UPDATE (head_version) ON camera.credentials", "UPDATE (revoked_at) ON camera.credential_versions"} {
		if _, err := owner.pool.Exec(ctx, "REVOKE "+privilege+" FROM camera_credential_writer"); err != nil {
			t.Fatal(err)
		}
		assertAdmissionDenied(t, check(writer, "camera_credential_writer"))
		if _, err := owner.pool.Exec(ctx, "GRANT "+privilege+" TO camera_credential_writer"); err != nil {
			t.Fatal(err)
		}
		if check(writer, "camera_credential_writer") != nil {
			t.Fatal("restored native grant not rechecked")
		}
	}
	if _, err := owner.pool.Exec(ctx, "REVOKE EXECUTE ON FUNCTION camera.reserve_credential_encryption_use(text) FROM camera_credential_budget"); err != nil {
		t.Fatal(err)
	}
	assertAdmissionDenied(t, check(budget, "camera_credential_budget"))
}
