package storage

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"net/url"
	"os"
	"reflect"
	"sync"
	"sync/atomic"
	"testing"

	"github.com/jackc/pgx/v5"
)

func nativeCredentialRequired(t *testing.T) {
	t.Helper()
	if os.Getenv("CAMERA_TEST_ENGINE") == "pglite" {
		t.Skip("requires native PostgreSQL account authentication/concurrent sessions")
	}
}
func credentialRoleStore(t *testing.T, owner *Store, ctx context.Context, role string) *Store {
	t.Helper()
	var random [24]byte
	if _, err := rand.Read(random[:]); err != nil {
		t.Fatal(err)
	}
	password := hex.EncodeToString(random[:])
	// The fixed role names are local to this disposable cluster. Refuse existing roles.
	if _, err := owner.pool.Exec(ctx, "CREATE ROLE "+role+" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD '"+password+"'"); err != nil {
		t.Fatal("fresh isolated credential role required")
	}
	t.Cleanup(func() {
		_, _ = owner.pool.Exec(context.Background(), "DROP OWNED BY "+role)
		_, _ = owner.pool.Exec(context.Background(), "DROP ROLE "+role)
	})
	u, err := url.Parse(os.Getenv("CAMERA_TEST_DATABASE_URL"))
	if err != nil {
		t.Fatal("invalid test connection")
	}
	u.User = url.UserPassword(role, password)
	s, err := Open(ctx, u.String())
	if err != nil {
		t.Fatal("isolated role authentication failed")
	}
	t.Cleanup(s.Close)
	return s
}

func TestNativeCredentialLeastPrivilegeAndGrantLoss(t *testing.T) {
	nativeCredentialRequired(t)
	owner, old, ctx := credentialFixture(t)
	registry := credentialRoleStore(t, owner, ctx, "camera_runtime")
	writer := credentialRoleStore(t, owner, ctx, "camera_credential_writer")
	budget := credentialRoleStore(t, owner, ctx, "camera_credential_budget")
	if err := owner.ProvisionRegistryRuntime(ctx); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 2; i++ {
		if err := owner.ProvisionCredentialRuntime(ctx); err != nil {
			t.Fatal(err)
		}
	}
	c, err := newFixtureCredentialStore(writer, budget, old.keys)
	if err != nil {
		t.Fatal(err)
	}
	if err = c.CheckReady(ctx); err != nil {
		t.Fatal(err)
	}
	if err = registry.CheckReady(ctx); err != nil {
		t.Fatal(err)
	}
	for _, role := range []*Store{registry, budget} {
		for _, table := range []string{"credentials", "credential_versions", "credential_requests", "credential_encryption_budgets"} {
			if _, err := role.pool.Exec(ctx, "SELECT * FROM camera."+table); stateCode(err) != "42501" {
				t.Fatal("private table exposed to unrelated role", err)
			}
		}
	}
	for _, query := range []string{"SELECT camera.reserve_credential_encryption_use('" + credentialOldEnc + "')", "UPDATE camera.credential_encryption_budgets SET uses=0", "DELETE FROM camera.credential_versions", "TRUNCATE camera.credential_requests", "UPDATE camera.credential_versions SET ciphertext='\\x00'", "UPDATE camera.credential_versions SET host='other.invalid'", "UPDATE camera.credentials SET scope_id='other'", "UPDATE camera.credential_requests SET fingerprint_digest=repeat('0',64)", "CREATE TABLE camera.forbidden(id int)", "ALTER TABLE camera.credentials ADD COLUMN forbidden int"} {
		if _, err = writer.pool.Exec(ctx, query); stateCode(err) != "42501" {
			t.Fatal("writer exceeded privilege", err)
		}
	}
	for _, query := range []string{"UPDATE camera.credential_encryption_budgets SET uses=0", "INSERT INTO camera.credential_encryption_budgets(key_id) VALUES ('" + credentialNewEnc + "')", "SELECT camera.device_has_active_credentials('parent')", "CREATE TABLE camera.forbidden(id int)"} {
		if _, err = budget.pool.Exec(ctx, query); stateCode(err) != "42501" {
			t.Fatal("budget role exceeded privilege", err)
		}
	}
	w := credentialWrite(t, 0)
	first, _, err := c.WriteVersion(ctx, credentialIdentity("create"), w, authorizeCredentialForTest)
	if err != nil {
		t.Fatal(err)
	}
	_, _, err = registry.DeleteDevice(ctx, "p", "delete-parent", "parent", deviceDeleteInput(1), unusedDeviceForTest)
	credentialError(t, err, "DEVICE_IN_USE")
	for _, grant := range []struct{ role, privilege string }{{"camera_credential_writer", "INSERT ON camera.credential_requests"}, {"camera_credential_writer", "UPDATE (head_version) ON camera.credentials"}, {"camera_credential_budget", "EXECUTE ON FUNCTION camera.reserve_credential_encryption_use(text)"}} {
		t.Run(grant.privilege, func(t *testing.T) {
			if _, err := owner.pool.Exec(ctx, "REVOKE "+grant.privilege+" FROM "+grant.role); err != nil {
				t.Fatal(err)
			}
			if c.CheckReady(ctx) == nil {
				t.Fatal("missing required grant ready")
			}
			before := credentialCounts(t, owner, ctx)
			_, _, err := c.WriteVersion(ctx, credentialIdentity("grant-retry"), credentialWrite(t, 1), authorizeCredentialForTest)
			if err == nil {
				t.Fatal("lost grant write accepted")
			}
			if credentialCounts(t, owner, ctx) != before {
				t.Fatal("lost grant changed rows")
			}
			if _, err = owner.pool.Exec(ctx, "GRANT "+grant.privilege+" TO "+grant.role); err != nil {
				t.Fatal(err)
			}
		})
	}
	if next, replay, err := c.WriteVersion(ctx, credentialIdentity("grant-retry"), credentialWrite(t, 1), authorizeCredentialForTest); err != nil || replay || next.Version != 2 {
		t.Fatal("grant repair retry failed", err)
	}
	if got, replay, err := c.WriteVersion(ctx, credentialIdentity("create"), w, authorizeCredentialForTest); err != nil || !replay || !reflect.DeepEqual(first, got) {
		t.Fatal("least privilege replay failed", err)
	}
	if _, _, err := c.RevokeVersion(ctx, credentialIdentity("revoke-one"), CredentialReference{"credential-1", "parent", 1}, authorizeCredentialForTest, unusedCredentialForTest); err != nil {
		t.Fatal(err)
	}
	if _, _, err := c.RevokeVersion(ctx, credentialIdentity("revoke-two"), CredentialReference{"credential-1", "parent", 2}, authorizeCredentialForTest, unusedCredentialForTest); err != nil {
		t.Fatal(err)
	}
	if _, _, err := registry.DeleteDevice(ctx, "p", "delete-parent", "parent", deviceDeleteInput(1), unusedDeviceForTest); err != nil {
		t.Fatal(err)
	}
	if err = c.CheckReady(ctx); err != nil {
		t.Fatal(err)
	}
	t.Log("native isolated roles, private table/DDL denial, grant-loss rollback and parent release passed")
}

func TestNativeCredentialConcurrentBudgetAndReceipts(t *testing.T) {
	nativeCredentialRequired(t)
	s, c, ctx := credentialFixture(t)
	start := make(chan struct{})
	uses := make(chan uint64, 32)
	errs := make(chan error, 32)
	var wg sync.WaitGroup
	for i := 0; i < 32; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			<-start
			r, err := c.budget.ReserveCredentialEncryptionUse(ctx, credentialOldEnc)
			uses <- r.Use
			errs <- err
		}()
	}
	close(start)
	wg.Wait()
	close(uses)
	close(errs)
	for err := range errs {
		if err != nil {
			t.Fatal(err)
		}
	}
	seen := map[uint64]bool{}
	for use := range uses {
		if use == 0 || seen[use] {
			t.Fatal("reservation reused")
		}
		seen[use] = true
	}
	if credentialUses(t, s, ctx, credentialOldEnc) != 32 {
		t.Fatal("parallel reservation not durable")
	}
	w := credentialWrite(t, 0)
	type outcome struct {
		m      CredentialMetadata
		replay bool
		err    error
	}
	results := make(chan outcome, 8)
	start = make(chan struct{})
	for i := 0; i < 8; i++ {
		go func() {
			<-start
			m, replay, err := c.WriteVersion(ctx, credentialIdentity("same"), w, authorizeCredentialForTest)
			results <- outcome{m, replay, err}
		}()
	}
	close(start)
	first := 0
	for i := 0; i < 8; i++ {
		r := <-results
		if r.err != nil || r.m.Version != 1 {
			t.Fatal("concurrent same-key write", r.err)
		}
		if !r.replay {
			first++
		}
	}
	if first != 1 || credentialCounts(t, s, ctx) != "1:1:1" {
		t.Fatal("same key applied twice")
	}
	start = make(chan struct{})
	for i := 0; i < 8; i++ {
		go func(key string) {
			<-start
			m, replay, err := c.WriteVersion(ctx, credentialIdentity(key), credentialWrite(t, 1), authorizeCredentialForTest)
			results <- outcome{m, replay, err}
		}(fmt.Sprintf("version-%d", i))
	}
	close(start)
	first = 0
	for i := 0; i < 8; i++ {
		r := <-results
		if r.err == nil {
			if r.replay || r.m.Version != 2 {
				t.Fatal("wrong version result")
			}
			first++
		} else {
			credentialError(t, r.err, "CREDENTIAL_VERSION_CONFLICT")
		}
	}
	if first != 1 || credentialCounts(t, s, ctx) != "1:2:2" {
		t.Fatal("concurrent version admission failed")
	}
}

func TestNativeCredentialParentDeletionWinsBeforeMutation(t *testing.T) {
	nativeCredentialRequired(t)
	s, c, ctx := credentialFixture(t)
	arrived, release := make(chan struct{}), make(chan struct{})
	var calls atomic.Int32
	guard := func(ctx context.Context, tx pgx.Tx, a CredentialAccess) (bool, error) {
		if calls.Add(1) == 2 {
			close(arrived)
			select {
			case <-release:
			case <-ctx.Done():
				return false, ctx.Err()
			}
		}
		return authorizeCredentialForTest(ctx, tx, a)
	}
	finished := make(chan error, 1)
	go func() {
		_, _, err := c.WriteVersion(ctx, credentialIdentity("write"), credentialWrite(t, 0), guard)
		finished <- err
	}()
	select {
	case <-arrived:
	case <-ctx.Done():
		t.Fatal("mutation admission not reached")
	}
	_, _, deleted := s.DeleteDevice(ctx, "p", "delete", "parent", deviceDeleteInput(1), unusedDeviceForTest)
	close(release)
	err := <-finished
	if deleted != nil {
		t.Fatal(deleted)
	}
	credentialError(t, err, "DEVICE_UNAVAILABLE")
	if credentialCounts(t, s, ctx) != "0:0:0" || credentialUses(t, s, ctx, credentialOldEnc) != 1 {
		t.Fatal("lost admission changed data/reset reservation")
	}
}

func TestNativeCredentialMutationBlocksParentDeletion(t *testing.T) {
	nativeCredentialRequired(t)
	for _, rollback := range []bool{false, true} {
		t.Run(fmt.Sprint(rollback), func(t *testing.T) {
			s, c, ctx := credentialFixture(t)
			failureSQL := ""
			if rollback {
				failureSQL = "RAISE EXCEPTION 'synthetic credential rollback';"
			}
			if _, err := s.pool.Exec(ctx, `CREATE FUNCTION camera.pause_credential_write() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM pg_advisory_xact_lock(1447908169,1); `+failureSQL+` RETURN NEW; END $$;
CREATE TRIGGER pause_credential_write BEFORE INSERT ON camera.credential_versions FOR EACH ROW EXECUTE FUNCTION camera.pause_credential_write()`); err != nil {
				t.Fatal(err)
			}
			gate, err := s.pool.Begin(ctx)
			if err != nil {
				t.Fatal(err)
			}
			defer gate.Rollback(context.Background())
			var gatePID int32
			if err = gate.QueryRow(ctx, "SELECT pg_backend_pid()").Scan(&gatePID); err != nil {
				t.Fatal(err)
			}
			if _, err = gate.Exec(ctx, "SELECT pg_advisory_xact_lock(1447908169,1)"); err != nil {
				t.Fatal(err)
			}
			written := make(chan error, 1)
			go func() {
				_, _, err := c.WriteVersion(ctx, credentialIdentity("create"), credentialWrite(t, 0), authorizeCredentialForTest)
				written <- err
			}()
			writerPID := waitDeviceBlockedPID(t, s, ctx, gatePID)
			deleted := make(chan error, 1)
			go func() {
				_, _, err := s.DeleteDevice(ctx, "p", "delete", "parent", deviceDeleteInput(1), unusedDeviceForTest)
				deleted <- err
			}()
			waitDeviceBlockedPID(t, s, ctx, writerPID)
			if err = gate.Commit(ctx); err != nil {
				t.Fatal(err)
			}
			writeErr, deleteErr := <-written, <-deleted
			if rollback {
				credentialError(t, writeErr, "CREDENTIAL_STORE_UNAVAILABLE")
				if deleteErr != nil {
					t.Fatal("rollback still blocked deletion", deleteErr)
				}
			} else {
				if writeErr != nil {
					t.Fatal(writeErr)
				}
				credentialError(t, deleteErr, "DEVICE_IN_USE")
			}
			if credentialUses(t, s, ctx, credentialOldEnc) != 1 {
				t.Fatal("reservation lost after competing deletion")
			}
		})
	}
}
