//go:build linux

package credentialcrypto

import (
	"crypto/sha256"
	"encoding/hex"
	"io"
	"os"
	"path/filepath"
	"strings"
	"syscall"
)

const privateDirectoryFlags = syscall.O_RDONLY | syscall.O_DIRECTORY | syscall.O_NOFOLLOW | syscall.O_CLOEXEC

func privateKeyFile(path string) (*os.File, syscall.Stat_t, error) {
	var parent syscall.Stat_t
	if !filepath.IsAbs(path) || filepath.Clean(path) != path || path == "/" {
		return nil, parent, ErrKeyFile
	}
	parts := strings.Split(strings.TrimPrefix(path, "/"), "/")
	directory, err := syscall.Open("/", privateDirectoryFlags, 0)
	if err != nil {
		return nil, parent, ErrKeyFile
	}
	defer func() { _ = syscall.Close(directory) }()
	for _, part := range parts[:len(parts)-1] {
		next, err := syscall.Openat(directory, part, privateDirectoryFlags, 0)
		if err != nil {
			return nil, parent, ErrKeyFile
		}
		_ = syscall.Close(directory)
		directory = next
	}
	if syscall.Fstat(directory, &parent) != nil || parent.Uid != uint32(os.Geteuid()) ||
		(parent.Mode&07777 != 0700 && parent.Mode&07777 != 0500) {
		return nil, parent, ErrKeyFile
	}
	descriptor, err := syscall.Openat(directory, parts[len(parts)-1],
		syscall.O_RDONLY|syscall.O_NOFOLLOW|syscall.O_CLOEXEC|syscall.O_NONBLOCK, 0)
	if err != nil {
		return nil, parent, ErrKeyFile
	}
	return os.NewFile(uintptr(descriptor), "private-credential-bundle"), parent, nil
}

func validPrivateKeyFile(info syscall.Stat_t) bool {
	return info.Mode&syscall.S_IFMT == syscall.S_IFREG && info.Uid == uint32(os.Geteuid()) &&
		info.Nlink == 1 && (info.Mode&07777 == 0600 || info.Mode&07777 == 0400) &&
		info.Size > 0 && info.Size <= MaxBundleBytes
}

func samePrivateKeyFile(a, b syscall.Stat_t) bool {
	return a.Dev == b.Dev && a.Ino == b.Ino && a.Size == b.Size && a.Mode == b.Mode &&
		a.Uid == b.Uid && a.Gid == b.Gid && a.Nlink == b.Nlink && a.Mtim == b.Mtim && a.Ctim == b.Ctim
}

// LoadKeyBundleFile reads a bounded, current-UID-owned private regular file.
// Every path component is opened without following symlinks. It never creates,
// repairs, replaces or prints a bundle. It records exact bytes and observed
// read-only mount status; a future runtime must enforce admission and hold the
// external lease for the complete credential operation before using keys.
func LoadKeyBundleFile(path string) (*Keyring, error) {
	file, parent, err := privateKeyFile(path)
	if err != nil {
		return nil, ErrKeyFile
	}
	defer file.Close()
	var before, after syscall.Stat_t
	if syscall.Fstat(int(file.Fd()), &before) != nil || !validPrivateKeyFile(before) {
		return nil, ErrKeyFile
	}
	body, err := io.ReadAll(io.LimitReader(file, MaxBundleBytes+1))
	defer clear(body)
	if err != nil || int64(len(body)) != before.Size || syscall.Fstat(int(file.Fd()), &after) != nil || !samePrivateKeyFile(before, after) {
		return nil, ErrKeyFile
	}
	// Reopen through the complete path to reject replaced ancestors or entries.
	present, currentParent, err := privateKeyFile(path)
	if err != nil {
		return nil, ErrKeyFile
	}
	defer present.Close()
	var current syscall.Stat_t
	if syscall.Fstat(int(present.Fd()), &current) != nil || !samePrivateKeyFile(after, current) ||
		parent.Dev != currentParent.Dev || parent.Ino != currentParent.Ino {
		return nil, ErrKeyFile
	}
	ring, err := ParseKeyBundle(body)
	if err != nil {
		return nil, ErrKeyFile
	}
	var mount syscall.Statfs_t
	if syscall.Fstatfs(int(present.Fd()), &mount) != nil {
		return nil, ErrKeyFile
	}
	digest := sha256.Sum256(body)
	ring.bundleSHA256 = hex.EncodeToString(digest[:])
	ring.readOnlyMount = mount.Flags&1 != 0 // Linux ST_RDONLY; mode0400 alone is insufficient.
	return ring, nil
}
