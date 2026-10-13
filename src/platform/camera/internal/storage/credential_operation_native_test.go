//go:build linux

package storage

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
	"vms.local/platform/camera/internal/credentialadmission"
	"vms.local/platform/camera/internal/credentialcrypto"
)

type operationEvent struct {
	Kind             string                      `json:"kind"`
	Record           *credentialadmission.Record `json:"record,omitempty"`
	FailureComponent string                      `json:"failure_component,omitempty"`
}
type operationRestart struct {
	Writer, Budget string
	Record         credentialadmission.Record
}
type operationChild struct {
	cmd    *exec.Cmd
	input  io.WriteCloser
	events chan operationEvent
	done   chan error
}

func startOperationChild(t *testing.T, phase, temporary string, pin credentialadmission.LockIdentity) *operationChild {
	t.Helper()
	cmd := exec.Command(os.Args[0], "-test.run=^TestNativeCredentialOperationRuntime$", "-test.v", "-test.timeout=110s")
	for _, value := range os.Environ() {
		if !strings.HasPrefix(value, "CAMERA_OPERATION_TEST_") {
			cmd.Env = append(cmd.Env, value)
		}
	}
	cmd.Env = append(cmd.Env, "CAMERA_OPERATION_TEST_PHASE="+phase, "CAMERA_OPERATION_TEST_TEMP="+temporary, fmt.Sprintf("CAMERA_OPERATION_TEST_PIN=%d:%d", pin.Device, pin.Inode))
	cmd.SysProcAttr = &syscall.SysProcAttr{Credential: &syscall.Credential{Uid: 10001, Gid: 10001, Groups: []uint32{10001}}}
	input, err := cmd.StdinPipe()
	if err != nil {
		t.Fatal(err)
	}
	output, err := cmd.StdoutPipe()
	if err != nil {
		t.Fatal(err)
	}
	// Child output is a protocol, never printed or archived with private DSNs.
	cmd.Stderr = io.Discard
	c := &operationChild{cmd: cmd, input: input, events: make(chan operationEvent, 32), done: make(chan error, 1)}
	if cmd.Start() != nil {
		operationFailure("child_start")
		t.Fatal("native separate-UID child start failed")
	}
	go func() {
		s := bufio.NewScanner(output)
		for s.Scan() {
			if strings.HasPrefix(s.Text(), "CREDENTIAL_OP_EVENT ") {
				var e operationEvent
				if json.Unmarshal([]byte(strings.TrimPrefix(s.Text(), "CREDENTIAL_OP_EVENT ")), &e) == nil {
					c.events <- e
				}
			}
		}
		close(c.events)
		c.done <- cmd.Wait()
	}()
	t.Cleanup(func() { _ = input.Close(); _ = cmd.Process.Kill() })
	return c
}
func (c *operationChild) next(t *testing.T, kind string) operationEvent {
	t.Helper()
	select {
	case e, ok := <-c.events:
		if ok && e.Kind == "failure" {
			operationFailure(e.FailureComponent)
			t.Fatal("native child failed in", operationSafeComponent(e.FailureComponent))
		}
		if !ok || e.Kind != kind {
			operationFailure("child_protocol")
			t.Fatal("native child event missing or out of order", kind, e.Kind)
		}
		return e
	case <-time.After(25 * time.Second):
		operationFailure("child_wait")
		t.Fatal("native child event timeout", kind)
	}
	return operationEvent{}
}
func (c *operationChild) send(t *testing.T, command string) {
	t.Helper()
	if _, err := fmt.Fprintln(c.input, command); err != nil {
		t.Fatal("native child command failed")
	}
}
func operationEmit(kind string, r *credentialadmission.Record) {
	raw, _ := json.Marshal(operationEvent{Kind: kind, Record: r})
	fmt.Println("CREDENTIAL_OP_EVENT " + string(raw))
}

// Failure receipts contain only a reviewed component name. Child stderr and
// ordinary test output remain private and cannot expose synthetic role DSNs.
func operationSafeComponent(value string) string {
	switch value {
	case "owner_signal", "child_start", "child_protocol", "child_wait", "child_identity", "child_keys", "child_authority_pin", "child_database_setup", "child_endpoint", "child_restart_fixture", "child_approved_pools", "child_constructor", "child_ready", "child_failure_unwind", "child_required_grants", "child_create", "child_write_replay", "child_reference", "child_revoke", "child_revoke_replay", "child_append", "child_interrupted_write", "child_recreated":
		return value
	default:
		return "child_unknown"
	}
}
func operationFailure(component string) {
	fmt.Println("CREDENTIAL_OPERATION_FAILURE_COMPONENT:" + operationSafeComponent(component))
}
func operationOwnerCanSignal(status []byte) bool {
	for _, line := range strings.Split(string(status), "\n") {
		if strings.HasPrefix(line, "CapEff:") {
			fields := strings.Fields(line)
			if len(fields) != 2 || len(fields[1]) != 16 {
				return false
			}
			caps, err := strconv.ParseUint(fields[1], 16, 64)
			return err == nil && caps&(1<<5) != 0 // Linux CAP_KILL
		}
	}
	return false
}
func operationCommand(t *testing.T, in *bufio.Scanner, want string) {
	t.Helper()
	if !in.Scan() || in.Text() != want {
		t.Fatal("native parent command missing", want)
	}
}

// Runtime helper is invoked only by the parent fixture, never a normal selector.
func TestNativeCredentialOperationRuntime(t *testing.T) {
	phase := os.Getenv("CAMERA_OPERATION_TEST_PHASE")
	if phase != "runtime" && phase != "recreated" {
		t.Skip("native operation child not enabled")
	}
	component := "child_identity"
	t.Cleanup(func() {
		if t.Failed() {
			raw, _ := json.Marshal(operationEvent{Kind: "failure", FailureComponent: operationSafeComponent(component)})
			fmt.Println("CREDENTIAL_OP_EVENT " + string(raw))
		}
	})
	if os.Geteuid() != 10001 || os.Getegid() != 10001 {
		t.Fatal("actual runtime UID/GID required")
	}
	status, err := os.ReadFile("/proc/self/status")
	if err != nil || !strings.Contains(string(status), "CapEff:\t0000000000000000") {
		t.Fatal("unprivileged runtime required")
	}
	component = "child_keys"
	ring, err := credentialcrypto.LoadKeyBundleFile("/exchange/fixture/keys/key-bundle.json")
	if err != nil {
		t.Fatal(err)
	}
	_, ro, err := ring.ProtectedBundleReceipt()
	if err != nil || !ro {
		t.Fatal("actual RO key receipt required")
	}
	component = "child_authority_pin"
	var pin credentialadmission.LockIdentity
	if _, err = fmt.Sscanf(os.Getenv("CAMERA_OPERATION_TEST_PIN"), "%d:%d", &pin.Device, &pin.Inode); err != nil {
		t.Fatal("reviewed pin missing")
	}
	policy := credentialadmission.Policy{Directory: "/control-ro/authority", OwnerUID: 0, RuntimeGID: 10001, LockIdentity: pin}
	ctx, cancel := context.WithTimeout(context.Background(), 100*time.Second)
	defer cancel()
	var owner, writer, budget *Store
	var approved credentialadmission.Record
	if phase == "runtime" {
		component = "child_database_setup"
		owner, writer, budget, _, _ = admissionStores(t)
		putAdmissionMarker(t, owner, ctx, admissionDatabaseFixture(t))
		if err = owner.ProvisionCredentialRuntime(ctx); err != nil {
			t.Fatal(err)
		}
		if err = owner.EnrollCredentialEncryptionKey(ctx, ring.ActiveEncryptionID()); err != nil {
			t.Fatal(err)
		}
		createDeleteDevice(t, owner, ctx, "parent")
	}
	// Discovery belongs only to this synthetic fixture. The application receives
	// the resulting reviewed canonical IP, not a DNS/failover policy.
	component = "child_endpoint"
	admin, err := Open(ctx, os.Getenv("CAMERA_TEST_DATABASE_URL"))
	if err != nil {
		t.Fatal(err)
	}
	defer admin.Close()
	cfg := admin.pool.Config().ConnConfig
	ips, err := net.LookupHost(cfg.Host)
	if err != nil || len(ips) != 1 {
		t.Fatal("single fixture endpoint required")
	}
	ip := net.ParseIP(ips[0]).String()
	ca, err := os.ReadFile("/exchange/fixture/tls/ca.crt")
	if err != nil {
		t.Fatal(err)
	}
	p, err := NewCredentialEndpoint(ip, cfg.Port, cfg.Database, "verify-full", "admission-db", ca)
	if err != nil {
		t.Fatal(err)
	}
	component = "child_restart_fixture"
	file := filepath.Join(os.Getenv("CAMERA_OPERATION_TEST_TEMP"), "recreation.json")
	var saved operationRestart
	if phase == "runtime" {
		approved = bindingRecord(t, p, ring)
		saved = operationRestart{bindingRoleDSN(t, writer, ip, "verify-full"), bindingRoleDSN(t, budget, ip, "verify-full"), approved}
		raw, _ := json.Marshal(saved)
		if os.WriteFile(file, raw, 0600) != nil {
			t.Fatal("private synthetic restart fixture failed")
		}
		clear(raw)
	} else {
		raw, err := os.ReadFile(file)
		if err != nil {
			t.Fatal("synthetic restart fixture absent")
		}
		if json.Unmarshal(raw, &saved) != nil {
			t.Fatal("invalid synthetic restart fixture")
		}
		clear(raw)
		approved = saved.Record
	}
	component = "child_approved_pools"
	a, err := OpenCredentialAdmissionDatabase(ctx, saved.Writer, p, "camera_credential_writer")
	if err != nil {
		t.Fatal(err)
	}
	defer a.Close()
	b, err := OpenCredentialAdmissionDatabase(ctx, saved.Budget, p, "camera_credential_budget")
	if err != nil {
		t.Fatal(err)
	}
	defer b.Close()
	component = "child_constructor"
	c, err := NewAdmittedCredentialStore(a, b, ring, policy, approved, p)
	if err != nil {
		t.Fatal(err)
	}
	if phase == "recreated" {
		component = "child_recreated"
		before := credentialCounts(t, admin, ctx)
		uses := credentialUses(t, admin, ctx, ring.ActiveEncryptionID())
		calls := 0
		auth := func(context.Context, pgx.Tx, CredentialAccess) (bool, error) { calls++; return true, nil }
		_, _, err = c.WriteVersion(ctx, credentialIdentity("create"), credentialWrite(t, 0), auth)
		assertAdmissionDenied(t, err)
		_, err = c.CheckReference(ctx, credentialIdentity(""), CredentialReference{"credential-1", "parent", 2}, credentialWrite(t, 0).Target, auth)
		assertAdmissionDenied(t, err)
		_, _, err = c.RevokeVersion(ctx, credentialIdentity("revoke"), CredentialReference{"credential-1", "parent", 1}, auth, unusedCredentialForTest)
		assertAdmissionDenied(t, err)
		assertAdmissionDenied(t, c.CheckReady(ctx))
		if calls != 0 || before != credentialCounts(t, admin, ctx) || uses != credentialUses(t, admin, ctx, ring.ActiveEncryptionID()) {
			t.Fatal("FENCED recreation reached business IO")
		}
		operationEmit("recreated-denied", nil)
		return
	}
	in := bufio.NewScanner(os.Stdin)
	operationEmit("proposal", &approved)
	operationCommand(t, in, "open")
	component = "child_ready"
	if err = c.CheckReady(ctx); err != nil {
		t.Fatal(err)
	}
	assertAdmissionDenied(t, c.CheckReady(context.Background()))
	component = "child_failure_unwind"
	// Test real guarded error, panic and canceled-callback unwinding before any
	// budget reservation. The parent verifies exclusive acquisition afterwards.
	_, _, err = c.WriteVersion(ctx, credentialIdentity("auth-error"), credentialWrite(t, 0), nil)
	credentialError(t, err, "CREDENTIAL_AUTHORIZATION_UNAVAILABLE")
	func() {
		defer func() {
			if recover() == nil {
				t.Fatal("guarded panic hidden")
			}
		}()
		_, _, _ = c.WriteVersion(ctx, credentialIdentity("panic"), credentialWrite(t, 0), func(context.Context, pgx.Tx, CredentialAccess) (bool, error) { panic("synthetic panic") })
	}()
	canceled, stop := context.WithCancel(ctx)
	_, _, err = c.WriteVersion(canceled, credentialIdentity("canceled-callback"), credentialWrite(t, 0), func(context.Context, pgx.Tx, CredentialAccess) (bool, error) { stop(); return true, nil })
	if err == nil || a.pool.Stat().AcquiredConns() != 0 || credentialUses(t, admin, ctx, ring.ActiveEncryptionID()) != 0 {
		t.Fatal("guarded unwind leaked lease, connection or budget")
	}
	badPolicy := policy
	badPolicy.Directory = "/control-rw/authority"
	rw, err := NewAdmittedCredentialStore(a, b, ring, badPolicy, approved, p)
	if err != nil {
		t.Fatal(err)
	}
	assertAdmissionDenied(t, rw.CheckReady(ctx))
	if _, err = admin.pool.Exec(ctx, "UPDATE camera.credential_admission_database SET generation=generation+1"); err != nil {
		t.Fatal(err)
	}
	_, _, err = c.WriteVersion(ctx, credentialIdentity("marker-mismatch"), credentialWrite(t, 0), authorizeCredentialForTest)
	assertAdmissionDenied(t, err)
	if _, err = admin.pool.Exec(ctx, "UPDATE camera.credential_admission_database SET generation=generation-1"); err != nil {
		t.Fatal(err)
	}
	operationEmit("unwound", nil)
	operationCommand(t, in, "next")
	component = "child_required_grants"
	// Lost required business grants deny even successful replay/reference paths.
	if _, err = admin.pool.Exec(ctx, "REVOKE INSERT ON camera.credential_requests FROM camera_credential_writer"); err != nil {
		t.Fatal(err)
	}
	_, _, err = c.WriteVersion(ctx, credentialIdentity("grant"), credentialWrite(t, 0), authorizeCredentialForTest)
	assertAdmissionDenied(t, err)
	if credentialUses(t, admin, ctx, ring.ActiveEncryptionID()) != 0 {
		t.Fatal("grant denial burned budget")
	}
	if _, err = admin.pool.Exec(ctx, "GRANT INSERT ON camera.credential_requests TO camera_credential_writer"); err != nil {
		t.Fatal(err)
	}
	for _, flow := range []string{"create", "write-replay", "reference", "revoke", "revoke-replay", "append"} {
		component = "child_" + strings.ReplaceAll(flow, "-", "_")
		count := 0
		pause := 1
		if flow == "append" {
			pause = 2
		}
		auth := func(ctx context.Context, tx pgx.Tx, access CredentialAccess) (bool, error) {
			count++
			if count == pause {
				operationEmit("blocked-"+flow, nil)
				operationCommand(t, in, "resume")
			}
			return authorizeCredentialForTest(ctx, tx, access)
		}
		switch flow {
		case "create", "write-replay", "append":
			version := int64(0)
			key := "create"
			if flow == "append" {
				version = 1
				key = "append"
			}
			m, replay, err := c.WriteVersion(ctx, credentialIdentity(key), credentialWrite(t, version), auth)
			if err != nil || m.Version != version+1 || replay != (flow == "write-replay") {
				t.Fatal("guarded write/replay failed", flow, err)
			}
		case "reference":
			m, err := c.CheckReference(ctx, credentialIdentity(""), CredentialReference{"credential-1", "parent", 1}, credentialWrite(t, 0).Target, auth)
			if err != nil || m.Version != 1 {
				t.Fatal("guarded reference failed", err)
			}
		case "revoke", "revoke-replay":
			m, replay, err := c.RevokeVersion(ctx, credentialIdentity("revoke"), CredentialReference{"credential-1", "parent", 1}, auth, unusedCredentialForTest)
			if err != nil || m.RevokedAt == nil || replay != (flow == "revoke-replay") {
				t.Fatal("guarded revoke/replay failed", err)
			}
		}
		operationEmit("returned-"+flow, nil)
		operationCommand(t, in, "next")
	}
	// Hold a real second data transaction after a separately committed use.
	component = "child_interrupted_write"
	count := 0
	_, _, _ = c.WriteVersion(ctx, credentialIdentity("interrupted"), credentialWrite(t, 2), func(ctx context.Context, tx pgx.Tx, a CredentialAccess) (bool, error) {
		count++
		if count == 2 {
			operationEmit("kill-after-budget", nil)
			operationCommand(t, in, "never")
		}
		return authorizeCredentialForTest(ctx, tx, a)
	})
	t.Fatal("interrupted operation unexpectedly returned")
}

func TestNativeCredentialOperationLeases(t *testing.T) {
	if os.Getenv("CAMERA_OPERATION_TEST_PHASE") != "owner" {
		t.Skip("native operation owner not enabled")
	}
	if os.Geteuid() != 0 {
		t.Fatal("synthetic maintenance UID required")
	}
	status, err := os.ReadFile("/proc/self/status")
	if err != nil || !operationOwnerCanSignal(status) {
		operationFailure("owner_signal")
		t.Fatal("isolated maintenance CAP_KILL required for different-UID child termination")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 140*time.Second)
	defer cancel()
	directory := "/control-rw/authority"
	if os.Mkdir(directory, 0750) != nil || os.Chown(directory, 0, 10001) != nil || os.Chmod(directory, 0750) != nil {
		t.Fatal("fresh isolated authority required")
	}
	db := admissionDatabaseFixture(t)
	initial, err := credentialadmission.NewFenced(db.DeploymentID, db.OperationID, "2026-10-07T00:00:00Z")
	if err != nil {
		t.Fatal(err)
	}
	policy := credentialadmission.Policy{Directory: directory, OwnerUID: 0, RuntimeGID: 10001}
	pin, err := credentialadmission.Bootstrap(ctx, policy, initial)
	if err != nil {
		t.Fatal(err)
	}
	policy.LockIdentity = pin
	temporary, err := os.MkdirTemp("/tmp", "operations-")
	if err != nil {
		t.Fatal(err)
	}
	defer os.RemoveAll(temporary)
	if os.Chown(temporary, 0, 10001) != nil || os.Chmod(temporary, 0770) != nil {
		t.Fatal("synthetic coordination permissions failed")
	}
	child := startOperationChild(t, "runtime", temporary, pin)
	proposal := child.next(t, "proposal").Record
	if proposal == nil || credentialadmission.Validate(*proposal) != nil {
		t.Fatal("valid synthetic proposal required")
	}
	lease, err := credentialadmission.AcquireMaintenance(ctx, policy)
	if err != nil {
		t.Fatal(err)
	}
	prepared, err := credentialadmission.NextPrepare(initial, *proposal.Binding, proposal.WrittenAt)
	if err != nil {
		t.Fatal(err)
	}
	if lease.Commit(initial, prepared) != nil || lease.Commit(prepared, *proposal) != nil {
		t.Fatal("synthetic OPEN commit failed")
	}
	_ = lease.Close()
	child.send(t, "open")
	child.next(t, "unwound")
	lease, err = credentialadmission.AcquireMaintenance(ctx, policy)
	if err != nil {
		t.Fatal("error/panic/cancellation did not drain")
	}
	_ = lease.Close()
	fmt.Println("CREDENTIAL_OPERATION_PHASE_OK:failure-unwind")
	child.send(t, "next")
	for _, flow := range []string{"create", "write-replay", "reference", "revoke", "revoke-replay", "append"} {
		child.next(t, "blocked-"+flow)
		deadline, stop := context.WithTimeout(ctx, 75*time.Millisecond)
		blocked, err := credentialadmission.AcquireMaintenance(deadline, policy)
		stop()
		if blocked != nil || err != credentialadmission.ErrDeadline {
			if blocked != nil {
				_ = blocked.Close()
			}
			t.Fatal("maintenance entered active operation", flow)
		}
		child.send(t, "resume")
		child.next(t, "returned-"+flow)
		lease, err := credentialadmission.AcquireMaintenance(ctx, policy)
		if err != nil {
			t.Fatal("normal operation did not drain", err)
		}
		if r, err := lease.Snapshot(); err != nil || r.State != credentialadmission.Open {
			t.Fatal("normal drain changed authority")
		}
		_ = lease.Close()
		fmt.Println("CREDENTIAL_OPERATION_PHASE_OK:" + flow)
		child.send(t, "next")
	}
	child.next(t, "kill-after-budget")
	owner, err := Open(ctx, os.Getenv("CAMERA_TEST_DATABASE_URL"))
	if err != nil {
		t.Fatal(err)
	}
	defer owner.Close()
	var name string
	if owner.pool.QueryRow(ctx, "SELECT current_database()").Scan(&name) != nil || name != "vms_camera_test" {
		t.Fatal("disposable database required")
	}
	before := credentialCounts(t, owner, ctx)
	if uses := credentialUses(t, owner, ctx, "enc-1111111111111111"); uses != 3 {
		t.Fatal("interruption did not follow durable budget commit", uses)
	}
	deadline, stop := context.WithTimeout(ctx, 75*time.Millisecond)
	blocked, err := credentialadmission.AcquireMaintenance(deadline, policy)
	stop()
	if blocked != nil || err != credentialadmission.ErrDeadline {
		if blocked != nil {
			_ = blocked.Close()
		}
		t.Fatal("maintenance crossed budget/data gap")
	}
	if child.cmd.Process.Kill() != nil {
		operationFailure("owner_signal")
		t.Fatal("synthetic child kill failed")
	}
	select {
	case err := <-child.done:
		if err == nil {
			t.Fatal("killed child exited successfully")
		}
	case <-time.After(10 * time.Second):
		t.Fatal("killed child was not reaped")
	}
	lease, err = credentialadmission.AcquireMaintenance(ctx, policy)
	if err != nil {
		t.Fatal("process death did not drain lease", err)
	}
	current, err := lease.Snapshot()
	if err != nil {
		t.Fatal(err)
	}
	fenced, err := credentialadmission.NextFence(current, "44444444-4444-4444-8444-444444444444", current.WrittenAt)
	if err != nil || lease.Commit(current, fenced) != nil {
		t.Fatal("post-drain fence failed")
	}
	_ = lease.Close()
	if credentialCounts(t, owner, ctx) != before || credentialUses(t, owner, ctx, "enc-1111111111111111") != 3 {
		t.Fatal("process death lost durable use or committed interrupted rows")
	}
	fmt.Println("CREDENTIAL_OPERATION_PHASE_OK:death-drain-budget")
	recreated := startOperationChild(t, "recreated", temporary, pin)
	recreated.next(t, "recreated-denied")
	select {
	case err := <-recreated.done:
		if err != nil {
			t.Fatal("recreated runtime failed")
		}
	case <-time.After(10 * time.Second):
		t.Fatal("recreated runtime did not exit")
	}
	if credentialCounts(t, owner, ctx) != before || credentialUses(t, owner, ctx, "enc-1111111111111111") != 3 {
		t.Fatal("stale recreation mutated state")
	}
	fmt.Println("CREDENTIAL_OPERATION_PHASE_OK:stale-recreation")
	// The killed fixture cannot run Go cleanup. Explicitly clean only this
	// disposable cluster after every child has been waited for.
	for _, role := range []string{"camera_credential_writer", "camera_credential_budget"} {
		if _, err = owner.pool.Exec(ctx, "DROP OWNED BY "+role+"; DROP ROLE "+role); err != nil {
			t.Fatal("isolated killed-role cleanup failed")
		}
	}
}
