//go:build linux

package credentialadmission

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"sync"
	"syscall"
	"testing"
	"time"
)

func deadline(t *testing.T, duration time.Duration) context.Context {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), duration)
	t.Cleanup(cancel)
	return ctx
}

func newPolicy(t *testing.T) Policy {
	t.Helper()
	dir := filepath.Join(t.TempDir(), "authority")
	if err := os.Mkdir(dir, 0750); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(dir, 0750); err != nil {
		t.Fatal(err)
	}
	return Policy{Directory: dir, OwnerUID: os.Geteuid(), RuntimeGID: os.Getegid()}
}

func seeded(t *testing.T, open bool) (Policy, Record) {
	t.Helper()
	p := newPolicy(t)
	r := initial(t)
	identity, err := Bootstrap(deadline(t, time.Second), p, r)
	if err != nil {
		t.Fatal(err)
	}
	p.LockIdentity = identity
	if open {
		l, err := AcquireMaintenance(deadline(t, time.Second), p)
		if err != nil {
			t.Fatal(err)
		}
		defer l.Close()
		prepared, _ := NextPrepare(r, candidate(), timestamp)
		if err = l.Commit(r, prepared); err != nil {
			t.Fatal(err)
		}
		next, _ := NextOpen(prepared, timestamp)
		if err = l.Commit(prepared, next); err != nil {
			t.Fatal(err)
		}
		r = next
	}
	return p, r
}

func TestBootstrapCreateOnlyAndDurableModes(t *testing.T) {
	p, r := seeded(t, false)
	for name, mode := range map[string]os.FileMode{stateName: 0640, lockName: 0640} {
		info, err := os.Stat(filepath.Join(p.Directory, name))
		if err != nil || info.Mode().Perm() != mode {
			t.Fatal("mode", err)
		}
	}
	before, _ := os.ReadFile(filepath.Join(p.Directory, stateName))
	p.LockIdentity = LockIdentity{}
	if _, err := Bootstrap(deadline(t, time.Second), p, r); err != ErrConflict {
		t.Fatal("overwrote authority", err)
	}
	after, _ := os.ReadFile(filepath.Join(p.Directory, stateName))
	if !bytes.Equal(before, after) {
		t.Fatal("changed existing")
	}
	if err := os.Remove(filepath.Join(p.Directory, stateName)); err != nil {
		t.Fatal(err)
	}
	if _, err := Bootstrap(deadline(t, time.Second), p, r); err != ErrConflict {
		t.Fatal("missing state repaired", err)
	}
	if _, err := AcquireMaintenance(deadline(t, time.Second), p); err == nil {
		t.Fatal("unbound lock accepted")
	}
}

func TestBootstrapRejectsHistoryAndExistingArtifacts(t *testing.T) {
	for name, r := range map[string]Record{"OPEN": openRecord(t), "generation": func() Record { r := initial(t); r.Generation = 2; return r }(), "history": func() Record { r := initial(t); r.SeenEncryptionKeyIDs = []string{"enc-1111111111111111"}; return r }()} {
		t.Run(name, func(t *testing.T) {
			p := newPolicy(t)
			if _, err := Bootstrap(deadline(t, time.Second), p, r); err != ErrConflict {
				t.Fatal(err)
			}
			entries, _ := os.ReadDir(p.Directory)
			if len(entries) != 0 {
				t.Fatal("created on rejection")
			}
		})
	}
	for _, name := range []string{stateName, lockName} {
		t.Run(name, func(t *testing.T) {
			p := newPolicy(t)
			if err := os.Symlink("missing", filepath.Join(p.Directory, name)); err != nil {
				t.Fatal(err)
			}
			if _, err := Bootstrap(deadline(t, time.Second), p, initial(t)); err != ErrConflict {
				t.Fatal(err)
			}
		})
	}
}

func TestMaintenanceCASAndIdempotency(t *testing.T) {
	p, r := seeded(t, false)
	l, err := AcquireMaintenance(deadline(t, time.Second), p)
	if err != nil {
		t.Fatal(err)
	}
	defer l.Close()
	prepared, _ := NextPrepare(r, candidate(), timestamp)
	wrong := clone(r)
	wrong.OperationID = nextOperation
	if err = l.Commit(wrong, prepared); err != ErrConflict {
		t.Fatal("stale expected", err)
	}
	if err = l.Commit(r, prepared); err != nil {
		t.Fatal(err)
	}
	infoBefore, _ := os.Stat(filepath.Join(p.Directory, stateName))
	if err = l.Commit(prepared, prepared); err != nil {
		t.Fatal(err)
	}
	infoAfter, _ := os.Stat(filepath.Join(p.Directory, stateName))
	if !os.SameFile(infoBefore, infoAfter) {
		t.Fatal("retry rewrote state")
	}
	if err = l.Commit(r, prepared); err != ErrConflict {
		t.Fatal("stale operation")
	}
	if err = l.Close(); err != nil {
		t.Fatal(err)
	}
	if _, err = l.Snapshot(); err != ErrUnavailable {
		t.Fatal("closed snapshot")
	}
	if err = l.Commit(prepared, prepared); err != ErrUnavailable {
		t.Fatal("closed commit")
	}
}

func TestIndependentSharedDescriptorsAndDeadlines(t *testing.T) {
	p, r := seeded(t, true)
	one, err := acquireRead(deadline(t, time.Second), p, r, false)
	if err != nil {
		t.Fatal(err)
	}
	defer one.Close()
	two, err := acquireRead(deadline(t, time.Second), p, r, false)
	if err != nil {
		t.Fatal(err)
	}
	defer two.Close()
	one.Close()
	if err = two.Check(); err != nil {
		t.Fatal(err)
	}
	if _, err = AcquireMaintenance(deadline(t, 30*time.Millisecond), p); err != ErrDeadline {
		t.Fatal("one reader unlocked other", err)
	}
	two.Close()
	if err = two.Check(); err != ErrUnavailable {
		t.Fatal("closed reader")
	}
	l, err := AcquireMaintenance(deadline(t, time.Second), p)
	if err != nil {
		t.Fatal(err)
	}
	defer l.Close()
	if _, err = acquireRead(deadline(t, 30*time.Millisecond), p, r, false); err != ErrDeadline {
		t.Fatal("writer not exclusive", err)
	}
	if _, err = AcquireMaintenance(context.Background(), p); err != ErrDeadline {
		t.Fatal("unbounded acquisition")
	}
	cancelled, cancel := context.WithTimeout(context.Background(), time.Second)
	cancel()
	if _, err = AcquireMaintenance(cancelled, p); err != ErrDeadline {
		t.Fatal("cancel")
	}
}

func TestReadIntentRejectsFencedPreparedAndStaleExpected(t *testing.T) {
	p, r := seeded(t, false)
	if _, err := acquireRead(deadline(t, time.Second), p, r, false); err != ErrConflict {
		t.Fatal("fence admission")
	}
	l, err := AcquireMaintenance(deadline(t, time.Second), p)
	if err != nil {
		t.Fatal(err)
	}
	prepared, _ := NextPrepare(r, candidate(), timestamp)
	l.Commit(r, prepared)
	l.Close()
	if _, err := acquireRead(deadline(t, time.Second), p, prepared, false); err != ErrConflict {
		t.Fatal("prepared admission")
	}
	op, _ := NextOpen(prepared, timestamp)
	l, err = AcquireMaintenance(deadline(t, time.Second), p)
	if err != nil {
		t.Fatal(err)
	}
	l.Commit(prepared, op)
	l.Close()
	for name, change := range map[string]func(*Record){"generation": func(r *Record) { r.Generation++ }, "operation": func(r *Record) { r.OperationID = nextOperation }, "keys": func(r *Record) { r.Binding.KeyBundleSHA256 = candidate().EndpointProfileSHA256 }} {
		t.Run(name, func(t *testing.T) {
			expected := clone(op)
			change(&expected)
			if _, err := acquireRead(deadline(t, time.Second), p, expected, false); err != ErrConflict {
				t.Fatal("stale expected", err)
			}
		})
	}
	// Public API always enforces real RO mount and a separate runtime UID. The
	// private no-mount-check helper above tests lease mechanics only.
	if _, err := AcquireReadOnly(deadline(t, time.Second), p, op); err != ErrUnavailable {
		t.Fatal("writable owner mount admitted", err)
	}
}

func TestPermissionsTypesLinksOwnersAndBounds(t *testing.T) {
	for _, kind := range []string{"dir mode", "state mode", "lock mode", "state symlink", "lock symlink", "hardlink", "FIFO", "owner", "group", "empty", "oversize", "corrupt", "lock content", "untrusted parent"} {
		t.Run(kind, func(t *testing.T) {
			p, _ := seeded(t, true)
			path := filepath.Join(p.Directory, stateName)
			switch kind {
			case "dir mode":
				os.Chmod(p.Directory, 0770)
			case "state mode":
				os.Chmod(path, 0600)
			case "lock mode":
				os.Chmod(filepath.Join(p.Directory, lockName), 0660)
			case "state symlink", "lock symlink":
				if kind == "lock symlink" {
					path = filepath.Join(p.Directory, lockName)
				}
				os.Rename(path, path+".original")
				os.Symlink(path+".original", path)
			case "hardlink":
				if err := os.Link(path, path+".link"); err != nil {
					t.Fatal(err)
				}
			case "FIFO":
				os.Remove(path)
				if err := syscall.Mkfifo(path, 0640); err != nil {
					t.Fatal(err)
				}
			case "owner":
				p.OwnerUID++
			case "group":
				p.RuntimeGID++
			case "empty":
				os.WriteFile(path, nil, 0640)
			case "oversize":
				os.WriteFile(path, bytes.Repeat([]byte(" "), MaxBytes+1), 0640)
			case "corrupt":
				os.WriteFile(path, []byte("PRIVATE_INVALID_INPUT"), 0640)
			case "lock content":
				os.WriteFile(filepath.Join(p.Directory, lockName), []byte("x"), 0640)
			case "untrusted parent":
				os.Chmod(filepath.Dir(p.Directory), 0770)
			}
			if l, err := AcquireMaintenance(deadline(t, 100*time.Millisecond), p); err != ErrUnavailable {
				if l != nil {
					l.Close()
				}
				t.Fatal("unsafe accepted", err)
			}
		})
	}
	for _, kind := range []int64{0x6969, 0x65735546, 0x1234} {
		if localFilesystem(kind) {
			t.Fatal("remote filesystem")
		}
	}
}

func TestStableLockReceiptRejectsReplacementBeforeOrDuringLease(t *testing.T) {
	for _, during := range []bool{false, true} {
		t.Run(fmt.Sprint(during), func(t *testing.T) {
			p, r := seeded(t, true)
			var reader *ReadLease
			var err error
			if during {
				reader, err = acquireRead(deadline(t, time.Second), p, r, false)
				if err != nil {
					t.Fatal(err)
				}
				defer reader.Close()
			}
			path := filepath.Join(p.Directory, lockName)
			if err = os.Rename(path, path+".old"); err != nil {
				t.Fatal(err)
			}
			if err = os.WriteFile(path, nil, 0640); err != nil {
				t.Fatal(err)
			}
			os.Chmod(path, 0640)
			if reader != nil && reader.Check() != ErrUnavailable {
				t.Fatal("old lease accepted new lock")
			}
			if l, err := AcquireMaintenance(deadline(t, time.Second), p); err != ErrUnavailable {
				if l != nil {
					l.Close()
				}
				t.Fatal("replacement accepted", err)
			}
		})
	}
}

func TestDirectoryAndComponentReplacement(t *testing.T) {
	p, r := seeded(t, true)
	l, err := acquireRead(deadline(t, time.Second), p, r, false)
	if err != nil {
		t.Fatal(err)
	}
	defer l.Close()
	os.Rename(p.Directory, p.Directory+".old")
	os.Mkdir(p.Directory, 0750)
	os.Chmod(p.Directory, 0750)
	if l.Check() != ErrUnavailable {
		t.Fatal("directory replacement")
	}
	link := filepath.Join(filepath.Dir(p.Directory), "alias")
	os.Symlink(p.Directory+".old", link)
	p.Directory = link
	if _, err = AcquireMaintenance(deadline(t, time.Second), p); err != ErrUnavailable {
		t.Fatal("component symlink")
	}
	p.Directory = filepath.Dir(link) + "/../authority"
	if _, err = AcquireMaintenance(deadline(t, time.Second), p); err != ErrUnavailable {
		t.Fatal("unclean path")
	}
}

func TestAtomicCommitFailureAndReacquisition(t *testing.T) {
	for _, stage := range []string{"retry_file_sync", "retry_directory_sync"} {
		t.Run(stage, func(t *testing.T) {
			p, r := seeded(t, true)
			l, err := AcquireMaintenance(deadline(t, time.Second), p)
			if err != nil {
				t.Fatal(err)
			}
			defer l.Close()
			if err = l.commit(r, r, func(s string) error {
				if s == stage {
					return errors.New("IO")
				}
				return nil
			}); err != ErrUncertain {
				t.Fatal("retry durability failure", err)
			}
			if _, err = l.Snapshot(); err != ErrUnavailable {
				t.Fatal("retry did not poison lease")
			}
		})
	}
	for _, stage := range []string{"write", "file_sync", "before_rename", "directory_sync", "after_sync"} {
		t.Run(stage, func(t *testing.T) {
			p, r := seeded(t, true)
			l, err := AcquireMaintenance(deadline(t, time.Second), p)
			if err != nil {
				t.Fatal(err)
			}
			next, _ := NextFence(r, nextOperation, timestamp)
			fault := func(s string) error {
				if s == stage {
					return errors.New("PRIVATE_FAULT")
				}
				return nil
			}
			if err = l.commit(r, next, fault); err != ErrUncertain {
				t.Fatal(err)
			}
			if _, err = l.Snapshot(); err != ErrUnavailable {
				t.Fatal("poisoned lease")
			}
			if err = l.Commit(r, next); err != ErrUnavailable {
				t.Fatal("uncertain retry")
			}
			l.Close()
			fresh, err := AcquireMaintenance(deadline(t, time.Second), p)
			if err != nil {
				t.Fatal(err)
			}
			defer fresh.Close()
			current, err := fresh.Snapshot()
			if err != nil {
				t.Fatal(err)
			}
			want := r
			if stage == "directory_sync" || stage == "after_sync" {
				want = next
			}
			if !reflect.DeepEqual(current, want) {
				t.Fatal("partial record")
			}
			if err = fresh.Commit(current, next); err != nil {
				t.Fatal("explicit reinspection retry", err)
			}
			entries, _ := os.ReadDir(p.Directory)
			if len(entries) != 2 {
				t.Fatal("temp leak")
			}
		})
	}
}

func TestConcurrentCASHasOneWinner(t *testing.T) {
	p, r := seeded(t, true)
	var wg sync.WaitGroup
	results := make(chan error, 2)
	for _, op := range []string{nextOperation, "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"} {
		wg.Add(1)
		go func(op string) {
			defer wg.Done()
			l, err := AcquireMaintenance(deadline(t, time.Second), p)
			if err != nil {
				results <- err
				return
			}
			defer l.Close()
			next, _ := NextFence(r, op, timestamp)
			results <- l.Commit(r, next)
		}(op)
	}
	wg.Wait()
	close(results)
	success, conflict := 0, 0
	for err := range results {
		if err == nil {
			success++
		} else if err == ErrConflict {
			conflict++
		} else {
			t.Fatal(err)
		}
	}
	if success != 1 || conflict != 1 {
		t.Fatal(success, conflict)
	}
}

// Child helpers run the actual compiled test binary in separate processes.
func TestLeaseProcessHelper(t *testing.T) {
	mode := os.Getenv("VMS_ADMISSION_TEST_CHILD")
	if mode == "" {
		return
	}
	var p Policy
	if json.Unmarshal([]byte(os.Getenv("VMS_ADMISSION_TEST_POLICY")), &p) != nil {
		t.Fatal("policy")
	}
	if mode == "read" {
		l, err := acquireRead(deadline(t, 3*time.Second), p, openRecord(t), false)
		if err != nil {
			t.Fatal(err)
		}
		defer l.Close()
		fmt.Println("LEASE_READY")
		io.Copy(io.Discard, os.Stdin)
	} else {
		l, err := AcquireMaintenance(deadline(t, 3*time.Second), p)
		if err != nil {
			t.Fatal(err)
		}
		defer l.Close()
		if mode == "fence" {
			r, err := l.Snapshot()
			if err != nil {
				t.Fatal(err)
			}
			next, _ := NextFence(r, nextOperation, timestamp)
			if err = l.Commit(r, next); err != nil {
				t.Fatal(err)
			}
		}
		fmt.Println("LEASE_READY")
		io.Copy(io.Discard, os.Stdin)
	}
}

func childLease(t *testing.T, p Policy, mode string) (*exec.Cmd, io.WriteCloser) {
	t.Helper()
	binary, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	t.Cleanup(cancel)
	cmd := exec.CommandContext(ctx, binary, "-test.run", "^TestLeaseProcessHelper$", "-test.count=1")
	body, _ := json.Marshal(p)
	cmd.Env = append(os.Environ(), "VMS_ADMISSION_TEST_CHILD="+mode, "VMS_ADMISSION_TEST_POLICY="+string(body))
	input, err := cmd.StdinPipe()
	if err != nil {
		t.Fatal(err)
	}
	output, err := cmd.StdoutPipe()
	if err != nil {
		t.Fatal(err)
	}
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	if err = cmd.Start(); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { input.Close(); cmd.Process.Kill() })
	ready := make(chan string, 1)
	go func() { line, _ := bufio.NewReader(output).ReadString('\n'); ready <- line }()
	select {
	case line := <-ready:
		if line != "LEASE_READY\n" {
			cmd.Wait()
			t.Fatal("child failed", line, stderr.String())
		}
	case <-ctx.Done():
		t.Fatal("child deadline")
	}
	return cmd, input
}

func TestMultipleProcessesDrainAndKilledWriterKeepsFence(t *testing.T) {
	p, r := seeded(t, true)
	one, inOne := childLease(t, p, "read")
	two, inTwo := childLease(t, p, "read")
	if _, err := AcquireMaintenance(deadline(t, 30*time.Millisecond), p); err != ErrDeadline {
		t.Fatal("child readers did not drain")
	}
	inOne.Close()
	if err := one.Wait(); err != nil {
		t.Fatal(err)
	}
	if _, err := AcquireMaintenance(deadline(t, 30*time.Millisecond), p); err != ErrDeadline {
		t.Fatal("first child released second")
	}
	inTwo.Close()
	if err := two.Wait(); err != nil {
		t.Fatal(err)
	}
	writer, input := childLease(t, p, "fence")
	defer input.Close()
	if _, err := acquireRead(deadline(t, 30*time.Millisecond), p, r, false); err != ErrDeadline {
		t.Fatal("child exclusive lease")
	}
	writer.Process.Kill()
	writer.Wait()
	l, err := AcquireMaintenance(deadline(t, time.Second), p)
	if err != nil {
		t.Fatal(err)
	}
	defer l.Close()
	after, err := l.Snapshot()
	if err != nil || after.State != Fenced || after.Generation != 2 {
		t.Fatal("killed writer lost fence", err)
	}
	if _, err := acquireRead(deadline(t, 30*time.Millisecond), p, r, false); err != ErrDeadline {
		t.Fatal("held exclusive")
	}
	l.Close()
	if _, err := acquireRead(deadline(t, time.Second), p, r, false); err != ErrConflict {
		t.Fatal("stale OPEN revived", err)
	}
}
