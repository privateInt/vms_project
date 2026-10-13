//go:build linux

package app

import (
	"bufio"
	"bytes"
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync/atomic"
	"syscall"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
	"vms.local/platform/camera/internal/contracts"
	"vms.local/platform/camera/internal/credentialadmission"
	"vms.local/platform/camera/internal/credentialcrypto"
	"vms.local/platform/camera/internal/storage"
)

// All credentials, certificates, authority and databases in this fixture are
// synthetic. Runtime children never inherit the database owner DSN/password.
type managementNativeConfig struct {
	Writer, Budget, IP string
	Port               uint16
	Record             credentialadmission.Record
	Pin                credentialadmission.LockIdentity
}
type managementNativeChild struct {
	cmd    *exec.Cmd
	input  io.WriteCloser
	events chan string
	done   chan error
}

func managementNativeStart(t *testing.T, phase, file string) *managementNativeChild {
	t.Helper()
	cmd := exec.Command(os.Args[0], "-test.run=^TestNativeCredentialManagementRuntime$", "-test.v", "-test.timeout=100s")
	for _, v := range os.Environ() {
		if !strings.HasPrefix(v, "CAMERA_") && !strings.HasPrefix(v, "PG") && !strings.HasPrefix(v, "VMS_") && !strings.HasPrefix(v, "COMPOSE_") {
			cmd.Env = append(cmd.Env, v)
		}
	}
	cmd.Env = append(cmd.Env, "CAMERA_MANAGEMENT_TEST_PHASE="+phase, "CAMERA_MANAGEMENT_TEST_CONFIG="+file)
	cmd.SysProcAttr = &syscall.SysProcAttr{Credential: &syscall.Credential{Uid: 10001, Gid: 10001, Groups: []uint32{10001}}}
	input, err := cmd.StdinPipe()
	if err != nil {
		t.Fatal("child input unavailable")
	}
	output, err := cmd.StdoutPipe()
	if err != nil {
		t.Fatal("child output unavailable")
	}
	cmd.Stderr = io.Discard
	c := &managementNativeChild{cmd, input, make(chan string, 16), make(chan error, 1)}
	if cmd.Start() != nil {
		t.Fatal("separate UID child start failed")
	}
	go func() {
		s := bufio.NewScanner(output)
		for s.Scan() {
			if strings.HasPrefix(s.Text(), "CREDENTIAL_MANAGEMENT_EVENT:") {
				c.events <- strings.TrimPrefix(s.Text(), "CREDENTIAL_MANAGEMENT_EVENT:")
			}
		}
		close(c.events)
		c.done <- cmd.Wait()
	}()
	t.Cleanup(func() { _ = input.Close(); _ = cmd.Process.Kill() })
	return c
}
func (c *managementNativeChild) next(t *testing.T, want string) {
	t.Helper()
	select {
	case value, ok := <-c.events:
		if !ok || value != want {
			t.Fatal("native HTTP child failed before", want)
		}
	case <-time.After(25 * time.Second):
		t.Fatal("native HTTP child timed out before", want)
	}
}
func (c *managementNativeChild) send(t *testing.T, value string) {
	t.Helper()
	if _, err := fmt.Fprintln(c.input, value); err != nil {
		t.Fatal("child command failed")
	}
}
func (c *managementNativeChild) finish(t *testing.T) {
	t.Helper()
	select {
	case err := <-c.done:
		if err != nil {
			t.Fatal("native HTTP child did not pass")
		}
	case <-time.After(10 * time.Second):
		t.Fatal("native HTTP child did not exit")
	}
}
func managementNativeCommand(t *testing.T, in *bufio.Scanner, want string) {
	t.Helper()
	if !in.Scan() || in.Text() != want {
		t.Fatal("native HTTP owner command unavailable")
	}
}
func managementNativeEmit(value string)  { fmt.Println("CREDENTIAL_MANAGEMENT_EVENT:" + value) }
func managementNativePhase(value string) { fmt.Println("CREDENTIAL_MANAGEMENT_PHASE_OK:" + value) }

func managementNativeSQL(t *testing.T, s *storage.Store, ctx context.Context, sql string, args ...any) {
	t.Helper()
	if s.WithTx(ctx, func(tx pgx.Tx) error { _, err := tx.Exec(ctx, sql, args...); return err }) != nil {
		t.Fatal("isolated fixture SQL failed")
	}
}

type managementNativeCounts struct{ versions, requests, revoked, uses int64 }

func managementNativeCount(t *testing.T, s *storage.Store, ctx context.Context) managementNativeCounts {
	t.Helper()
	var c managementNativeCounts
	err := s.WithTx(ctx, func(tx pgx.Tx) error {
		return tx.QueryRow(ctx, `SELECT (SELECT count(*) FROM camera.credential_versions),
(SELECT count(*) FROM camera.credential_requests),(SELECT count(*) FROM camera.credential_versions WHERE revoked_at IS NOT NULL),
(SELECT uses FROM camera.credential_encryption_budgets WHERE key_id='enc-1111111111111111')`).Scan(&c.versions, &c.requests, &c.revoked, &c.uses)
	})
	if err != nil {
		t.Fatal("isolated counters unavailable")
	}
	return c
}

func TestNativeCredentialManagementHTTP(t *testing.T) {
	if os.Getenv("CAMERA_MANAGEMENT_TEST_PHASE") != "owner" {
		t.Skip("native UID/RO/TLS HTTP integration not enabled")
	}
	if os.Geteuid() != 0 || os.Getenv("CAMERA_TEST_ALLOW_SCHEMA_RESET") != "1" {
		t.Fatal("explicit disposable owner required")
	}
	u, err := url.Parse(os.Getenv("CAMERA_TEST_DATABASE_URL"))
	if err != nil || u.Path != "/vms_camera_test" || u.User == nil || u.User.Username() != "vms_camera_test" {
		t.Fatal("disposable test database required")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 170*time.Second)
	defer cancel()
	owner, err := storage.Open(ctx, u.String())
	if err != nil {
		t.Fatal("isolated owner connection unavailable")
	}
	defer owner.Close()
	managementNativeSQL(t, owner, ctx, "DROP SCHEMA IF EXISTS camera CASCADE")
	if _, err = owner.MigrateCredentialAdmission(ctx); err != nil {
		t.Fatal("schema9 migration failed")
	}
	addresses, err := net.LookupHost(u.Hostname())
	if err != nil || len(addresses) != 1 {
		t.Fatal("single disposable endpoint required")
	}
	ip := net.ParseIP(addresses[0]).String()
	port := uint16(5432)
	if u.Port() != "" {
		var p uint64
		if _, err = fmt.Sscanf(u.Port(), "%d", &p); err != nil || p < 1 || p > 65535 {
			t.Fatal("invalid fixture port")
		}
		port = uint16(p)
	}
	ca, err := os.ReadFile("/exchange/fixture/tls/ca.crt")
	if err != nil {
		t.Fatal("synthetic CA absent")
	}
	endpoint, err := storage.NewCredentialEndpoint(ip, port, "vms_camera_test", "verify-full", "admission-db", ca)
	if err != nil {
		t.Fatal("fixture endpoint invalid")
	}
	config := managementNativeConfig{IP: ip, Port: port}
	for _, role := range []string{"camera_credential_writer", "camera_credential_budget"} {
		var random [24]byte
		if _, err = rand.Read(random[:]); err != nil {
			t.Fatal("fixture password unavailable")
		}
		password := hex.EncodeToString(random[:])
		managementNativeSQL(t, owner, ctx, "CREATE ROLE "+role+" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD '"+password+"'")
		roleURL := url.URL{Scheme: "postgres", User: url.UserPassword(role, password), Host: net.JoinHostPort(ip, fmt.Sprint(port)), Path: "/vms_camera_test", RawQuery: "sslmode=verify-full"}
		if role == "camera_credential_writer" {
			config.Writer = roleURL.String()
		} else {
			config.Budget = roleURL.String()
		}
	}
	if owner.ProvisionCredentialRuntime(ctx) != nil || owner.ProvisionCredentialAdmissionReaders(ctx) != nil || owner.EnrollCredentialEncryptionKey(ctx, "enc-1111111111111111") != nil {
		t.Fatal("credential runtime grants unavailable")
	}
	for _, id := range []string{"camera-1", "camera-2"} {
		if _, _, err = owner.CreateDevice(ctx, "fixture-owner", "create-"+id, contracts.DeviceCreate{SchemaVersion: "v1", DeviceID: id, DisplayName: id, DeviceKind: "TEST"}); err != nil {
			t.Fatal("fixture device unavailable")
		}
	}
	history, err := storage.CredentialAdmissionMigrationsSHA256()
	if err != nil {
		t.Fatal("migration digest unavailable")
	}
	keyBytes, err := os.ReadFile("/exchange/fixture/keys/key-bundle.json")
	if err != nil {
		t.Fatal("synthetic key fixture unavailable")
	}
	keyHash := sha256.Sum256(keyBytes)
	clear(keyBytes)
	initial, err := credentialadmission.NewFenced("11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222", "2026-10-08T00:00:00Z")
	if err != nil {
		t.Fatal("fixture authority invalid")
	}
	binding := credentialadmission.Binding{DatabaseID: "33333333-3333-4333-8333-333333333333", DatabaseName: "vms_camera_test", SchemaVersion: 9, MigrationSetSHA256: history, EndpointProfileSHA256: endpoint.SHA256(), KeyBundleSHA256: hex.EncodeToString(keyHash[:]), ActiveEncryptionKeyID: "enc-1111111111111111", ActiveIdempotencyKeyID: "idem-2222222222222222", WriterRole: "camera_credential_writer", BudgetRole: "camera_credential_budget"}
	prepared, err := credentialadmission.NextPrepare(initial, binding, "2026-10-08T00:00:00Z")
	if err != nil {
		t.Fatal("fixture prepare failed")
	}
	config.Record, err = credentialadmission.NextOpen(prepared, "2026-10-08T00:00:00Z")
	if err != nil {
		t.Fatal("fixture open failed")
	}
	managementNativeSQL(t, owner, ctx, `INSERT INTO camera.credential_admission_database(singleton,deployment_id,generation,operation_id,database_id,database_name,schema_version,migration_set_sha256) VALUES(1,$1,$2,$3,$4,$5,9,$6)`, initial.DeploymentID, initial.Generation, initial.OperationID, binding.DatabaseID, binding.DatabaseName, history)
	directory := "/control-rw/authority"
	if os.Mkdir(directory, 0750) != nil || os.Chown(directory, 0, 10001) != nil || os.Chmod(directory, 0750) != nil {
		t.Fatal("fresh fixture control directory required")
	}
	policy := credentialadmission.Policy{Directory: directory, OwnerUID: 0, RuntimeGID: 10001}
	config.Pin, err = credentialadmission.Bootstrap(ctx, policy, initial)
	if err != nil {
		t.Fatal("fixture bootstrap failed")
	}
	policy.LockIdentity = config.Pin
	lease, err := credentialadmission.AcquireMaintenance(ctx, policy)
	if err != nil {
		t.Fatal("fixture maintenance unavailable")
	}
	if lease.Commit(initial, prepared) != nil || lease.Commit(prepared, config.Record) != nil || lease.Close() != nil {
		t.Fatal("fixture authority commits failed")
	}
	temporary, err := os.MkdirTemp("/tmp", "credential-http-")
	if err != nil {
		t.Fatal("private child fixture unavailable")
	}
	defer os.RemoveAll(temporary)
	if os.Chown(temporary, 0, 10001) != nil || os.Chmod(temporary, 0750) != nil {
		t.Fatal("private child directory permissions failed")
	}
	file := filepath.Join(temporary, "runtime.json")
	raw, _ := json.Marshal(config)
	if os.WriteFile(file, raw, 0640) != nil || os.Chown(file, 0, 10001) != nil || os.Chmod(file, 0640) != nil {
		t.Fatal("private runtime configuration failed")
	}
	clear(raw)
	managementNativePhase("schema9-role-key-authority")
	child := managementNativeStart(t, "runtime", file)
	child.next(t, "ready")
	managementNativePhase("actual-runtime-bindings")
	child.send(t, "exercise")
	child.next(t, "lease-held")
	waitCtx, waitCancel := context.WithTimeout(ctx, 120*time.Millisecond)
	waitLease, waitErr := credentialadmission.AcquireMaintenance(waitCtx, policy)
	waitCancel()
	if waitLease != nil {
		_ = waitLease.Close()
	}
	if !errors.Is(waitErr, credentialadmission.ErrDeadline) {
		t.Fatal("HTTP operation did not hold authority lease")
	}
	child.send(t, "release")
	child.next(t, "exercise-done")
	lease, err = credentialadmission.AcquireMaintenance(ctx, policy)
	if err != nil {
		t.Fatal("HTTP lease did not drain")
	}
	_ = lease.Close()
	if managementNativeCount(t, owner, ctx) != (managementNativeCounts{2, 3, 1, 2}) {
		t.Fatal("HTTP mutations/replay changed unexpected counters")
	}
	managementNativePhase("http-write-metadata-revoke-replay")
	managementNativePhase("policy-and-usage-denials")
	managementNativePhase("whole-http-lease-and-drain")
	child.send(t, "exit")
	child.finish(t)
	child = managementNativeStart(t, "recreated", file)
	child.next(t, "ready")
	child.send(t, "replay")
	child.next(t, "replayed")
	if managementNativeCount(t, owner, ctx) != (managementNativeCounts{2, 3, 1, 2}) {
		t.Fatal("process recreation consumed budget")
	}
	managementNativePhase("recreated-http-replay")
	before := managementNativeCount(t, owner, ctx)
	for _, pair := range [][2]string{
		{"REVOKE SELECT ON camera.credential_admission_database FROM camera_credential_writer", "GRANT SELECT ON camera.credential_admission_database TO camera_credential_writer"},
		{"REVOKE EXECUTE ON FUNCTION camera.reserve_credential_encryption_use(text) FROM camera_credential_budget", "GRANT EXECUTE ON FUNCTION camera.reserve_credential_encryption_use(text) TO camera_credential_budget"},
		{"UPDATE camera.credential_admission_database SET generation=2", "UPDATE camera.credential_admission_database SET generation=1"},
	} {
		managementNativeSQL(t, owner, ctx, pair[0])
		child.send(t, "blocked")
		child.next(t, "blocked")
		if managementNativeCount(t, owner, ctx) != before {
			t.Fatal("grant/marker failure changed data or budget")
		}
		managementNativeSQL(t, owner, ctx, pair[1])
		child.send(t, "replay")
		child.next(t, "replayed")
	}
	managementNativePhase("actual-grant-and-marker-loss")
	lease, err = credentialadmission.AcquireMaintenance(ctx, policy)
	if err != nil {
		t.Fatal("fixture fence unavailable")
	}
	fenced, err := credentialadmission.NextFence(config.Record, "44444444-4444-4444-8444-444444444444", "2026-10-08T00:00:01Z")
	if err != nil || lease.Commit(config.Record, fenced) != nil || lease.Close() != nil {
		t.Fatal("fixture fence failed")
	}
	child.send(t, "blocked")
	child.next(t, "blocked")
	child.send(t, "exit")
	child.finish(t)
	child = managementNativeStart(t, "fenced", file)
	child.next(t, "ready")
	child.send(t, "blocked")
	child.next(t, "blocked")
	child.send(t, "exit")
	child.finish(t)
	if managementNativeCount(t, owner, ctx) != before {
		t.Fatal("fenced HTTP changed data or budget")
	}
	managementNativePhase("fenced-and-recreated-denial")
}

func TestNativeCredentialManagementRuntime(t *testing.T) {
	phase := os.Getenv("CAMERA_MANAGEMENT_TEST_PHASE")
	if phase != "runtime" && phase != "recreated" && phase != "fenced" {
		t.Skip("native HTTP runtime child not enabled")
	}
	t.Cleanup(func() {
		if t.Failed() {
			managementNativeEmit("failed")
		}
	})
	if os.Geteuid() != 10001 || os.Getegid() != 10001 || os.Getenv("CAMERA_TEST_DATABASE_URL") != "" {
		t.Fatal("unprivileged role-only child required")
	}
	status, err := os.ReadFile("/proc/self/status")
	if err != nil || !strings.Contains(string(status), "CapEff:\t0000000000000000") {
		t.Fatal("capability-free runtime required")
	}
	raw, err := os.ReadFile(os.Getenv("CAMERA_MANAGEMENT_TEST_CONFIG"))
	if err != nil {
		t.Fatal("protected runtime fixture absent")
	}
	var config managementNativeConfig
	if json.Unmarshal(raw, &config) != nil {
		t.Fatal("runtime fixture invalid")
	}
	clear(raw)
	ctx, cancel := context.WithTimeout(context.Background(), 90*time.Second)
	defer cancel()
	ring, err := credentialcrypto.LoadKeyBundleFile("/exchange/fixture/keys/key-bundle.json")
	if err != nil {
		t.Fatal("protected key receipt unavailable")
	}
	_, ro, err := ring.ProtectedBundleReceipt()
	if err != nil || !ro {
		t.Fatal("actual read-only key mount required")
	}
	ca, err := os.ReadFile("/exchange/fixture/tls/ca.crt")
	if err != nil {
		t.Fatal("fixture CA absent")
	}
	endpoint, err := storage.NewCredentialEndpoint(config.IP, config.Port, "vms_camera_test", "verify-full", "admission-db", ca)
	if err != nil {
		t.Fatal("reviewed endpoint invalid")
	}
	writer, err := storage.OpenCredentialAdmissionDatabase(ctx, config.Writer, endpoint, "camera_credential_writer")
	if err != nil {
		t.Fatal("actual writer TLS binding failed")
	}
	defer writer.Close()
	budget, err := storage.OpenCredentialAdmissionDatabase(ctx, config.Budget, endpoint, "camera_credential_budget")
	if err != nil {
		t.Fatal("actual budget TLS binding failed")
	}
	defer budget.Close()
	authority := credentialadmission.Policy{Directory: "/control-ro/authority", OwnerUID: 0, RuntimeGID: 10001, LockIdentity: config.Pin}
	store, err := storage.NewAdmittedCredentialStore(writer, budget, ring, authority, config.Record, endpoint)
	if err != nil {
		t.Fatal("admitted store constructor failed")
	}
	certs := managementCerts(t)
	grant := managementGrantFixture(certs.client)
	policy, err := NewCredentialManagementPolicy([]CredentialManagementGrant{grant})
	if err != nil {
		t.Fatal("fixture management policy invalid")
	}
	var logs bytes.Buffer
	a, err := New(credentialToken, slog.New(slog.NewJSONHandler(&logs, nil)))
	if err != nil {
		t.Fatal("fixture HTTP API unavailable")
	}
	var usage atomic.Uint32
	usage.Store(uint32(storage.CredentialUsageUnknown))
	var pause atomic.Bool
	paused, release := make(chan struct{}, 1), make(chan struct{})
	// This is an explicit fixture-only usage source, not production reference tracking.
	guard := func(ctx context.Context, tx pgx.Tx, r storage.CredentialReference) (storage.CredentialUsage, error) {
		if tx == nil || r.DeviceID != "camera-1" || r.CredentialID != "credential-1" {
			return storage.CredentialUsageUnknown, nil
		}
		if pause.Swap(false) {
			paused <- struct{}{}
			select {
			case <-release:
			case <-ctx.Done():
				return storage.CredentialUsageUnknown, ctx.Err()
			}
		}
		return storage.CredentialUsage(usage.Load()), nil
	}
	handler, err := RegisterCredentialManagement(a, store, policy, guard)
	if err != nil {
		t.Fatal("explicit concrete HTTP registration failed")
	}
	server, client := managementServer(t, handler, certs)
	t.Cleanup(func() {
		for _, private := range []string{"native-user-private", "native-password-private", "native-target.invalid", config.Writer, config.Budget} {
			if strings.Contains(logs.String(), private) {
				t.Fatal("private log value disclosed")
			}
		}
	})
	request := func(method, path, key, body string, want int, replay string) []byte {
		t.Helper()
		req, err := http.NewRequest(method, server.URL+path, strings.NewReader(body))
		if err != nil {
			t.Fatal("HTTP fixture request failed")
		}
		req.Header.Set("Authorization", "Bearer "+credentialToken)
		if key != "" {
			req.Header.Set("Idempotency-Key", key)
		}
		if body != "" {
			req.Header.Set("Content-Type", "application/json")
		}
		resp, err := client.Do(req)
		if err != nil {
			t.Fatal("actual HTTP TLS request failed")
		}
		defer resp.Body.Close()
		value, err := io.ReadAll(io.LimitReader(resp.Body, 65537))
		if err != nil || len(value) > 65536 || resp.StatusCode != want || (replay != "" && resp.Header.Get("Idempotency-Replayed") != replay) {
			t.Fatal("native HTTP receipt/status mismatch", method, want)
		}
		for _, secret := range []string{"native-user-private", "native-password-private", "native-target.invalid", config.Writer, config.Budget} {
			if bytes.Contains(value, []byte(secret)) {
				t.Fatal("private response value disclosed")
			}
		}
		return value
	}
	write := func(expected int) string {
		return fmt.Sprintf(`{"schema_version":"v1","device_id":"camera-1","expected_version":%d,"target":{"protocol":"RTSP","host":"native-target.invalid","port":554},"secret":{"username":"native-user-private","password":"native-password-private"}}`, expected)
	}
	path := "/api/v1/credentials/credential-1/versions"
	revoke := `{"schema_version":"v1","device_id":"camera-1"}`
	replayCheck := func() {
		request("POST", path, "native-append", write(1), 201, "true")
		request("GET", path+"/1", "", "", 200, "")
		request("DELETE", path+"/1", "native-revoke", revoke, 200, "true")
	}
	blocked := func() {
		for _, r := range [][4]string{{"POST", path, "native-create", write(0)}, {"POST", path, "native-denied", write(2)}, {"GET", path + "/1", "", ""}, {"DELETE", path + "/1", "native-revoke", revoke}, {"DELETE", path + "/2", "native-revoke-two", revoke}} {
			value := request(r[0], r[1], r[2], r[3], 503, "")
			if !bytes.Contains(value, []byte("CREDENTIAL_ADMISSION_UNAVAILABLE")) {
				t.Fatal("admission error receipt missing")
			}
		}
	}
	in := bufio.NewScanner(os.Stdin)
	managementNativeEmit("ready")
	if phase == "runtime" {
		managementNativeCommand(t, in, "exercise")
		first := request("POST", path, "native-create", write(0), 201, "false")
		repeated := request("POST", path, "native-create", write(0), 201, "true")
		var x, y struct {
			Credential storage.CredentialMetadata `json:"credential"`
		}
		if json.Unmarshal(first, &x) != nil || json.Unmarshal(repeated, &y) != nil || x.Credential != y.Credential || x.Credential.Version != 1 {
			t.Fatal("create replay metadata mismatch")
		}
		request("POST", path, "native-append", write(1), 201, "false")
		request("GET", path+"/2", "", "", 200, "")
		if policy.Replace(nil) != nil {
			t.Fatal("policy replacement failed")
		}
		request("POST", path, "native-create", write(0), 403, "")
		request("GET", path+"/1", "", "", 403, "")
		request("DELETE", path+"/1", "native-revoke", revoke, 403, "")
		denied := grant
		denied.DeviceIDs = []string{"camera-2"}
		if policy.Replace([]CredentialManagementGrant{denied}) != nil {
			t.Fatal("device policy replacement failed")
		}
		request("POST", path, "native-create", write(0), 409, "")
		request("GET", path+"/1", "", "", 404, "")
		request("DELETE", path+"/1", "native-revoke", revoke, 409, "")
		if policy.Replace([]CredentialManagementGrant{grant}) != nil {
			t.Fatal("policy restoration failed")
		}
		usage.Store(uint32(storage.CredentialUsageInUse))
		request("DELETE", path+"/1", "native-revoke", revoke, 409, "")
		usage.Store(uint32(storage.CredentialUsageUnknown))
		request("DELETE", path+"/1", "native-revoke", revoke, 503, "")
		usage.Store(uint32(storage.CredentialUsageUnused))
		pause.Store(true)
		done := make(chan struct{})
		go func() { defer close(done); request("DELETE", path+"/1", "native-revoke", revoke, 200, "false") }()
		select {
		case <-paused:
		case <-time.After(5 * time.Second):
			t.Fatal("HTTP revoke guard not reached")
		}
		managementNativeEmit("lease-held")
		managementNativeCommand(t, in, "release")
		close(release)
		<-done
		replayCheck()
		managementNativeEmit("exercise-done")
		managementNativeCommand(t, in, "exit")
	} else {
		for in.Scan() {
			switch in.Text() {
			case "replay":
				replayCheck()
				managementNativeEmit("replayed")
			case "blocked":
				blocked()
				managementNativeEmit("blocked")
			case "exit":
				managementNativeEmit("finished")
				return
			default:
				t.Fatal("unknown native owner command")
			}
		}
		t.Fatal("native runtime command stream ended")
	}

}
