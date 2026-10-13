//go:build linux

package credentialadmission

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"io"
	"math"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"sync"
	"syscall"
	"time"
)

const stateName = "admission.json"
const lockName = "admission.lock"

type authority struct {
	p         Policy
	dir, lock *os.File
	readOnly  bool
}

type MaintenanceLease struct {
	mu       sync.Mutex
	a        *authority
	poisoned bool
}
type ReadLease struct {
	mu       sync.Mutex
	a        *authority
	expected Record
}

func validPolicy(p Policy) bool {
	return p.OwnerUID >= 0 && uint64(p.OwnerUID) < math.MaxUint32 && p.RuntimeGID >= 0 && uint64(p.RuntimeGID) < math.MaxUint32 && filepath.IsAbs(p.Directory) && filepath.Clean(p.Directory) == p.Directory && p.Directory != "/" && !strings.ContainsRune(p.Directory, '\x00')
}

func statFile(f *os.File) (syscall.Stat_t, error) {
	var s syscall.Stat_t
	err := syscall.Fstat(int(f.Fd()), &s)
	return s, err
}

func sameNode(a, b syscall.Stat_t) bool { return a.Dev == b.Dev && a.Ino == b.Ino }
func sameMeta(a, b syscall.Stat_t) bool {
	return sameNode(a, b) && a.Mode == b.Mode && a.Uid == b.Uid && a.Gid == b.Gid && a.Nlink == b.Nlink && a.Size == b.Size && a.Mtim == b.Mtim && a.Ctim == b.Ctim
}

func controlled(s syscall.Stat_t, p Policy, directory bool) bool {
	mode, kind := uint32(0640), uint32(syscall.S_IFREG)
	if directory {
		mode, kind = 0750, syscall.S_IFDIR
	}
	return s.Uid == uint32(p.OwnerUID) && s.Gid == uint32(p.RuntimeGID) && s.Mode&syscall.S_IFMT == kind && s.Mode&07777 == mode && (directory || s.Nlink == 1)
}

func child(dir *os.File, name string, flags int, mode uint32) (*os.File, error) {
	fd, err := syscall.Openat(int(dir.Fd()), name, flags|syscall.O_NOFOLLOW|syscall.O_CLOEXEC|syscall.O_NONBLOCK, mode)
	if err != nil {
		return nil, ErrUnavailable
	}
	return os.NewFile(uintptr(fd), name), nil
}

// Each path component is opened relative to an existing descriptor without
// following links. The direct parent must protect directory replacement.
func openDirectory(p Policy) (*os.File, error) {
	if !validPolicy(p) {
		return nil, ErrUnavailable
	}
	fd, err := syscall.Open("/", syscall.O_RDONLY|syscall.O_DIRECTORY|syscall.O_CLOEXEC, 0)
	if err != nil {
		return nil, ErrUnavailable
	}
	f := os.NewFile(uintptr(fd), "/")
	parts := strings.Split(strings.TrimPrefix(p.Directory, "/"), "/")
	for i, name := range parts {
		if i == len(parts)-1 {
			s, err := statFile(f)
			if err != nil || (s.Uid != 0 && s.Uid != uint32(p.OwnerUID)) || s.Mode&0022 != 0 {
				f.Close()
				return nil, ErrUnavailable
			}
		}
		next, err := child(f, name, syscall.O_RDONLY|syscall.O_DIRECTORY, 0)
		f.Close()
		if err != nil {
			return nil, err
		}
		f = next
	}
	s, err := statFile(f)
	if err != nil || !controlled(s, p, true) {
		f.Close()
		return nil, ErrUnavailable
	}
	var fs syscall.Statfs_t
	if syscall.Fstatfs(int(f.Fd()), &fs) != nil || !localFilesystem(fs.Type) {
		f.Close()
		return nil, ErrUnavailable
	}
	return f, nil
}

func localFilesystem(kind int64) bool {
	// ext4, XFS, Btrfs, tmpfs, overlay. No NFS/FUSE/distributed admission.
	switch uint64(kind) {
	case 0xef53, 0x58465342, 0x9123683e, 0x01021994, 0x794c7630:
		return true
	}
	return false
}

func openAuthority(p Policy, readOnly bool) (*authority, error) {
	d, err := openDirectory(p)
	if err != nil {
		return nil, err
	}
	f, err := child(d, lockName, syscall.O_RDONLY, 0)
	if err != nil {
		d.Close()
		return nil, err
	}
	a := &authority{p, d, f, readOnly}
	if err = a.check(); err != nil {
		a.close()
		return nil, err
	}
	return a, nil
}

func (a *authority) check() error {
	s, err := statFile(a.dir)
	if err != nil || !controlled(s, a.p, true) {
		return ErrUnavailable
	}
	reopened, err := openDirectory(a.p)
	if err != nil {
		return err
	}
	defer reopened.Close()
	rs, err := statFile(reopened)
	if err != nil || !sameNode(s, rs) {
		return ErrUnavailable
	}
	ls, err := statFile(a.lock)
	if err != nil || !controlled(ls, a.p, false) || ls.Size != 0 || a.p.LockIdentity.Inode == 0 || uint64(ls.Dev) != a.p.LockIdentity.Device || ls.Ino != a.p.LockIdentity.Inode {
		return ErrUnavailable
	}
	l, err := child(a.dir, lockName, syscall.O_RDONLY, 0)
	if err != nil {
		return err
	}
	defer l.Close()
	ns, err := statFile(l)
	if err != nil || !controlled(ns, a.p, false) || !sameMeta(ls, ns) {
		return ErrUnavailable
	}
	if a.readOnly {
		var fs syscall.Statfs_t
		if os.Geteuid() == a.p.OwnerUID || syscall.Fstatfs(int(a.dir.Fd()), &fs) != nil || fs.Flags&syscall.MS_RDONLY == 0 {
			return ErrUnavailable
		}
	}
	return nil
}

func (a *authority) close() { a.lock.Close(); a.dir.Close() }

func lock(ctx context.Context, f *os.File, exclusive bool) error {
	if ctx == nil {
		return ErrDeadline
	}
	if _, ok := ctx.Deadline(); !ok {
		return ErrDeadline
	}
	mode := syscall.LOCK_SH
	if exclusive {
		mode = syscall.LOCK_EX
	}
	for {
		if ctx.Err() != nil {
			return ErrDeadline
		}
		err := syscall.Flock(int(f.Fd()), mode|syscall.LOCK_NB)
		if err == nil {
			if ctx.Err() == nil {
				return nil
			}
			syscall.Flock(int(f.Fd()), syscall.LOCK_UN)
			return ErrDeadline
		}
		if err != syscall.EWOULDBLOCK && err != syscall.EAGAIN && err != syscall.EINTR {
			return ErrUnavailable
		}
		timer := time.NewTimer(5 * time.Millisecond)
		select {
		case <-ctx.Done():
			timer.Stop()
			return ErrDeadline
		case <-timer.C:
		}
	}
}

func (a *authority) read() (Record, error) {
	if err := a.check(); err != nil {
		return Record{}, err
	}
	f, err := child(a.dir, stateName, syscall.O_RDONLY, 0)
	if err != nil {
		return Record{}, err
	}
	defer f.Close()
	before, err := statFile(f)
	if err != nil || !controlled(before, a.p, false) || before.Size <= 0 || before.Size > MaxBytes {
		return Record{}, ErrUnavailable
	}
	raw, err := io.ReadAll(io.LimitReader(f, MaxBytes+1))
	if err != nil {
		return Record{}, ErrUnavailable
	}
	after, err := statFile(f)
	if err != nil || !sameMeta(before, after) || int64(len(raw)) != before.Size {
		return Record{}, ErrUnavailable
	}
	other, err := child(a.dir, stateName, syscall.O_RDONLY, 0)
	if err != nil {
		return Record{}, err
	}
	defer other.Close()
	now, err := statFile(other)
	if err != nil || !sameMeta(before, now) || a.check() != nil {
		return Record{}, ErrUnavailable
	}
	r, err := Parse(raw)
	if err != nil {
		return Record{}, ErrUnavailable
	}
	return r, nil
}

func acquireMaintenance(ctx context.Context, p Policy) (*MaintenanceLease, error) {
	if os.Geteuid() != p.OwnerUID {
		return nil, ErrUnavailable
	}
	a, err := openAuthority(p, false)
	if err != nil {
		return nil, err
	}
	if err = lock(ctx, a.lock, true); err != nil {
		a.close()
		return nil, err
	}
	if _, err = a.read(); err != nil {
		a.close()
		return nil, err
	}
	return &MaintenanceLease{a: a}, nil
}

func acquireRead(ctx context.Context, p Policy, expected Record, readOnly bool) (*ReadLease, error) {
	if Validate(expected) != nil || expected.State != Open || expected.Generation == math.MaxInt64 || len(expected.SeenEncryptionKeyIDs) == MaxSeen {
		return nil, ErrConflict
	}
	a, err := openAuthority(p, readOnly)
	if err != nil {
		return nil, err
	}
	if err = lock(ctx, a.lock, false); err != nil {
		a.close()
		return nil, err
	}
	r, err := a.read()
	if err != nil || r.State != Open || !reflect.DeepEqual(r, expected) {
		a.close()
		if err != nil {
			return nil, err
		}
		return nil, ErrConflict
	}
	return &ReadLease{a: a, expected: clone(expected)}, nil
}

func (l *ReadLease) Check() error {
	l.mu.Lock()
	defer l.mu.Unlock()
	if l.a == nil {
		return ErrUnavailable
	}
	r, err := l.a.read()
	if err != nil {
		return err
	}
	if !reflect.DeepEqual(r, l.expected) || r.State != Open {
		return ErrConflict
	}
	return nil
}

func (l *ReadLease) Close() error {
	l.mu.Lock()
	defer l.mu.Unlock()
	if l.a != nil {
		l.a.close()
		l.a = nil
	}
	return nil
}

func (l *MaintenanceLease) Close() error {
	l.mu.Lock()
	defer l.mu.Unlock()
	if l.a != nil {
		l.a.close()
		l.a = nil
	}
	return nil
}

func (l *MaintenanceLease) Snapshot() (Record, error) {
	l.mu.Lock()
	defer l.mu.Unlock()
	if l.a == nil || l.poisoned {
		return Record{}, ErrUnavailable
	}
	return l.a.read()
}

// Commit permits only validated transitions under the same exclusive lease and
// an exact expected record (including generation/operation/binding/history).
// It never enrolls budgets, verifies key material, or approves DB readiness.
func (l *MaintenanceLease) Commit(expected, next Record) error { return l.commit(expected, next, nil) }

func (l *MaintenanceLease) commit(expected, next Record, fault func(string) error) error {
	l.mu.Lock()
	defer l.mu.Unlock()
	if l.a == nil || l.poisoned {
		return ErrUnavailable
	}
	current, err := l.a.read()
	if err != nil {
		return err
	}
	if !reflect.DeepEqual(current, expected) || !allowed(current, next) {
		return ErrConflict
	}
	if reflect.DeepEqual(current, next) {
		// A previous process could have renamed successfully but failed parent
		// fsync. Retrying the same record confirms durability without replacing
		// the inode, resetting counters, or discarding the original timestamp.
		f, err := child(l.a.dir, stateName, syscall.O_RDONLY, 0)
		if err != nil {
			l.poisoned = true
			return ErrUncertain
		}
		var syncErr error
		if fault != nil {
			syncErr = fault("retry_file_sync")
		}
		if syncErr == nil {
			syncErr = f.Sync()
		}
		f.Close()
		if syncErr == nil && fault != nil {
			syncErr = fault("retry_directory_sync")
		}
		if syncErr != nil || l.a.dir.Sync() != nil {
			l.poisoned = true
			return ErrUncertain
		}
		confirmed, err := l.a.read()
		if err != nil || !reflect.DeepEqual(confirmed, current) {
			l.poisoned = true
			return ErrUncertain
		}
		return nil
	}
	if err = l.a.write(next, fault); err != nil {
		l.poisoned = true
		return err
	}
	return nil
}

func setupFile(f *os.File, p Policy) error {
	if f.Chown(p.OwnerUID, p.RuntimeGID) != nil || f.Chmod(0640) != nil {
		return ErrUnavailable
	}
	s, err := statFile(f)
	if err != nil || !controlled(s, p, false) {
		return ErrUnavailable
	}
	return nil
}

func bootstrap(ctx context.Context, p Policy, initial Record) (LockIdentity, error) {
	if os.Geteuid() != p.OwnerUID || Validate(initial) != nil || initial.State != Fenced || initial.Generation != 1 || initial.Binding != nil || len(initial.SeenEncryptionKeyIDs) != 0 || p.LockIdentity != (LockIdentity{}) {
		return LockIdentity{}, ErrConflict
	}
	if ctx == nil {
		return LockIdentity{}, ErrDeadline
	}
	if _, ok := ctx.Deadline(); !ok || ctx.Err() != nil {
		return LockIdentity{}, ErrDeadline
	}
	dir, err := openDirectory(p)
	if err != nil {
		return LockIdentity{}, err
	}
	defer dir.Close()
	// Any existing state/lock (even corrupt) forbids bootstrap. No unlink repair.
	for _, name := range []string{stateName, lockName} {
		fd, err := syscall.Openat(int(dir.Fd()), name, 0x200000|syscall.O_NOFOLLOW|syscall.O_CLOEXEC, 0)
		if err == nil {
			syscall.Close(fd)
			return LockIdentity{}, ErrConflict
		}
		if err != syscall.ENOENT {
			return LockIdentity{}, ErrUnavailable
		}
	}
	f, err := child(dir, lockName, syscall.O_RDWR|syscall.O_CREAT|syscall.O_EXCL, 0640)
	if err != nil {
		return LockIdentity{}, err
	}
	defer f.Close()
	if setupFile(f, p) != nil || f.Sync() != nil || dir.Sync() != nil {
		return LockIdentity{}, ErrUncertain
	}
	ls, err := statFile(f)
	if err != nil {
		return LockIdentity{}, ErrUncertain
	}
	identity := LockIdentity{uint64(ls.Dev), ls.Ino}
	p.LockIdentity = identity
	a := &authority{p, dir, f, false}
	if err = lock(ctx, f, true); err != nil {
		return LockIdentity{}, err
	}
	if err = a.check(); err != nil {
		return LockIdentity{}, err
	}
	if err := a.write(initial, nil); err != nil {
		return LockIdentity{}, err
	}
	return identity, nil
}

// fault is private to deterministic IO-failure tests, never an external option.
func (a *authority) write(next Record, fault func(string) error) error {
	raw, err := Encode(next)
	if err != nil {
		return err
	}
	if err = a.check(); err != nil {
		return err
	}
	var random [16]byte
	if _, err = rand.Read(random[:]); err != nil {
		return ErrUnavailable
	}
	name := ".admission-" + hex.EncodeToString(random[:]) + ".tmp"
	f, err := child(a.dir, name, syscall.O_RDWR|syscall.O_CREAT|syscall.O_EXCL, 0640)
	if err != nil {
		return ErrUnavailable
	}
	defer f.Close()
	defer syscall.Unlinkat(int(a.dir.Fd()), name)
	fail := func(stage string) bool { return fault != nil && fault(stage) != nil }
	if setupFile(f, a.p) != nil || fail("write") {
		return ErrUncertain
	}
	if n, err := f.Write(raw); err != nil || n != len(raw) {
		return ErrUncertain
	}
	if fail("file_sync") || f.Sync() != nil || fail("before_rename") || a.check() != nil {
		return ErrUncertain
	}
	if syscall.Renameat(int(a.dir.Fd()), name, int(a.dir.Fd()), stateName) != nil {
		return ErrUncertain
	}
	if fail("directory_sync") || a.dir.Sync() != nil || fail("after_sync") {
		return ErrUncertain
	}
	r, err := a.read()
	if err != nil || !reflect.DeepEqual(r, next) {
		return ErrUncertain
	}
	return nil
}
