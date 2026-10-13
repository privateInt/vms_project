package storage

import (
	"context"
	"encoding/json"
	"errors"
	"reflect"
	"strings"
	"testing"

	"github.com/jackc/pgx/v5"
)

func TestCredentialMetadataRequiresLeaseWithoutIO(t *testing.T) {
	for _, store := range []*CredentialStore{nil, {}, {keys: credentialTestKeys(t, false, false)}} {
		_, err := store.GetVersionMetadata(context.Background(), credentialIdentity(""), "credential-1", 1, authorizeCredentialForTest)
		assertAdmissionDenied(t, err)
	}
	for _, version := range []int64{0, -1} {
		_, err := (&CredentialStore{}).GetVersionMetadata(context.Background(), credentialIdentity(""), "credential-1", version, authorizeCredentialForTest)
		credentialError(t, err, "CONTRACT_INVALID")
	}
}

func TestCredentialMetadataInspectionAndRevocation(t *testing.T) {
	owner, store, ctx := credentialFixture(t)
	first, _, err := store.WriteVersion(ctx, credentialIdentity("create"), credentialWrite(t, 0), authorizeCredentialForTest)
	if err != nil {
		t.Fatal(err)
	}
	second, _, err := store.WriteVersion(ctx, credentialIdentity("append"), credentialWrite(t, 1), authorizeCredentialForTest)
	if err != nil {
		t.Fatal(err)
	}
	counts := credentialCounts(t, owner, ctx)
	uses := credentialUses(t, owner, ctx, credentialOldEnc)
	for _, expected := range []CredentialMetadata{first, second} {
		got, err := store.GetVersionMetadata(ctx, credentialIdentity(""), "credential-1", expected.Version, authorizeCredentialForTest)
		if err != nil || !reflect.DeepEqual(got, expected) {
			t.Fatal("exact version inspection failed", err)
		}
		body, _ := json.Marshal(got)
		for _, private := range []string{"camera.example.invalid", "synthetic-private-", "ciphertext", "encryption_key", "target_policy", "fingerprint"} {
			if strings.Contains(string(body), private) {
				t.Fatal("private metadata disclosed")
			}
		}
	}
	if credentialCounts(t, owner, ctx) != counts || credentialUses(t, owner, ctx, credentialOldEnc) != uses {
		t.Fatal("inspection reserved budget or wrote history")
	}
	for _, version := range []int64{1, 2} {
		revoked, _, err := store.RevokeVersion(ctx, credentialIdentity("revoke-"+string(rune('0'+version))), CredentialReference{"credential-1", "parent", version}, authorizeCredentialForTest, unusedCredentialForTest)
		if err != nil {
			t.Fatal(err)
		}
		got, err := store.GetVersionMetadata(ctx, credentialIdentity(""), "credential-1", version, authorizeCredentialForTest)
		if err != nil || !reflect.DeepEqual(got, revoked) || got.RevokedAt == nil {
			t.Fatal("revoked history unavailable", err)
		}
	}
	if _, _, err = owner.DeleteDevice(ctx, "p", "delete-parent", "parent", deviceDeleteInput(1), unusedDeviceForTest); err != nil {
		t.Fatal(err)
	}
	got, err := store.GetVersionMetadata(ctx, credentialIdentity(""), "credential-1", 1, authorizeCredentialForTest)
	if err != nil || got.RevokedAt == nil {
		t.Fatal("historical metadata lost after parent deletion", err)
	}
	if credentialUses(t, owner, ctx, credentialOldEnc) != uses {
		t.Fatal("metadata/revoke changed encryption budget")
	}
}

func TestCredentialMetadataAuthorizationAndUnwind(t *testing.T) {
	owner, store, ctx := credentialFixture(t)
	if _, _, err := store.WriteVersion(ctx, credentialIdentity("create"), credentialWrite(t, 0), authorizeCredentialForTest); err != nil {
		t.Fatal(err)
	}
	counts := credentialCounts(t, owner, ctx)
	uses := credentialUses(t, owner, ctx, credentialOldEnc)
	closed := 0
	store.admission = fixtureCredentialGuard{&closed}
	guard := func(ctx context.Context, tx pgx.Tx, access CredentialAccess) (bool, error) {
		if access.DeviceID != "parent" || access.CredentialID != "credential-1" || access.Version != 1 || access.Operation != "MANAGE" {
			t.Fatal("incorrect actual-resource authorization")
		}
		return authorizeCredentialForTest(ctx, tx, access)
	}
	if _, err := store.GetVersionMetadata(ctx, credentialIdentity(""), "credential-1", 1, guard); err != nil {
		t.Fatal(err)
	}
	for _, test := range []struct {
		authorizer CredentialAuthorizer
		code       string
	}{
		{nil, "CREDENTIAL_AUTHORIZATION_UNAVAILABLE"},
		{func(context.Context, pgx.Tx, CredentialAccess) (bool, error) { return false, nil }, "CREDENTIAL_UNAVAILABLE"},
		{func(context.Context, pgx.Tx, CredentialAccess) (bool, error) {
			return true, errors.New("synthetic-private-password")
		}, "CREDENTIAL_AUTHORIZATION_UNAVAILABLE"},
		{func(_ context.Context, _ pgx.Tx, a CredentialAccess) (bool, error) {
			return a.Operation == "REFERENCE", nil
		}, "CREDENTIAL_UNAVAILABLE"},
	} {
		_, err := store.GetVersionMetadata(ctx, credentialIdentity(""), "credential-1", 1, test.authorizer)
		credentialError(t, err, test.code)
	}
	for _, test := range []struct {
		identity CredentialIdentity
		id       string
		version  int64
	}{
		{CredentialIdentity{"scope-2", "admin-1", ""}, "credential-1", 1},
		{CredentialIdentity{"scope-1", "other-admin", ""}, "credential-1", 1},
		{credentialIdentity(""), "missing", 1}, {credentialIdentity(""), "credential-1", 42},
	} {
		_, err := store.GetVersionMetadata(ctx, test.identity, test.id, test.version, authorizeCredentialForTest)
		credentialError(t, err, "CREDENTIAL_UNAVAILABLE")
	}
	before := closed
	func() {
		defer func() {
			if recover() == nil {
				t.Fatal("panic hidden")
			}
		}()
		_, _ = store.GetVersionMetadata(ctx, credentialIdentity(""), "credential-1", 1, func(context.Context, pgx.Tx, CredentialAccess) (bool, error) { panic("synthetic callback panic") })
	}()
	if closed != before+1 || store.data.pool.Stat().AcquiredConns() != 0 {
		t.Fatal("panic leaked lease or transaction")
	}
	canceled, cancel := context.WithCancel(ctx)
	cancel()
	before = closed
	_, err := store.GetVersionMetadata(canceled, credentialIdentity(""), "credential-1", 1, authorizeCredentialForTest)
	assertAdmissionDenied(t, err)
	if closed != before || credentialCounts(t, owner, ctx) != counts || credentialUses(t, owner, ctx, credentialOldEnc) != uses {
		t.Fatal("inspection failure changed data or budget")
	}
}

func TestNativeCredentialMetadataRoleAndGrantLoss(t *testing.T) {
	nativeCredentialRequired(t)
	owner, original, ctx := credentialFixture(t)
	writer := credentialRoleStore(t, owner, ctx, "camera_credential_writer")
	budget := credentialRoleStore(t, owner, ctx, "camera_credential_budget")
	if err := owner.ProvisionCredentialRuntime(ctx); err != nil {
		t.Fatal(err)
	}
	store, err := newFixtureCredentialStore(writer, budget, original.keys)
	if err != nil {
		t.Fatal(err)
	}
	expected, _, err := store.WriteVersion(ctx, credentialIdentity("create"), credentialWrite(t, 0), authorizeCredentialForTest)
	if err != nil {
		t.Fatal(err)
	}
	counts := credentialCounts(t, owner, ctx)
	uses := credentialUses(t, owner, ctx, credentialOldEnc)
	check := func() {
		t.Helper()
		got, err := store.GetVersionMetadata(ctx, credentialIdentity(""), "credential-1", 1, authorizeCredentialForTest)
		if err != nil || !reflect.DeepEqual(expected, got) {
			t.Fatal("writer metadata failed", err)
		}
	}
	check()
	for _, table := range []string{"credentials", "credential_versions"} {
		t.Run(table, func(t *testing.T) {
			if _, err := owner.pool.Exec(ctx, "REVOKE SELECT ON camera."+table+" FROM camera_credential_writer"); err != nil {
				t.Fatal(err)
			}
			_, err := store.GetVersionMetadata(ctx, credentialIdentity(""), "credential-1", 1, authorizeCredentialForTest)
			credentialError(t, err, "CREDENTIAL_STORE_UNAVAILABLE")
			if _, err := owner.pool.Exec(ctx, "GRANT SELECT ON camera."+table+" TO camera_credential_writer"); err != nil {
				t.Fatal(err)
			}
			check()
		})
	}
	wrongRole, err := newFixtureCredentialStore(budget, writer, original.keys)
	if err != nil {
		t.Fatal(err)
	}
	_, err = wrongRole.GetVersionMetadata(ctx, credentialIdentity(""), "credential-1", 1, authorizeCredentialForTest)
	assertAdmissionDenied(t, err)
	if credentialCounts(t, owner, ctx) != counts || credentialUses(t, owner, ctx, credentialOldEnc) != uses {
		t.Fatal("grant loss reserved budget or changed history")
	}
}
