//go:build linux

package credentialcrypto

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"testing"
)

func keyFileFixture(t *testing.T) (string, []byte) {
	t.Helper()
	directory := filepath.Join(t.TempDir(), "keys")
	if err := os.Mkdir(directory, 0700); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(directory, "key-bundle.json")
	body := bundleBytes(t, testBundle(true))
	if err := os.WriteFile(path, body, 0600); err != nil {
		t.Fatal(err)
	}
	return path, body
}

func rejectedKeyFile(t *testing.T, path string) {
	t.Helper()
	ring, err := LoadKeyBundleFile(path)
	if ring != nil || !errors.Is(err, ErrKeyFile) || err.Error() != "CREDENTIAL_KEY_FILE_UNAVAILABLE" || errors.Unwrap(err) != nil {
		t.Fatal("unsafe or missing loader rejection", err)
	}
	for _, format := range []string{"%v", "%+v", "%#v"} {
		if path != "" && strings.Contains(fmt.Sprintf(format, err), path) {
			t.Fatal("path exposed")
		}
	}
}

func TestPrivateKeyFileLoadsImmutableHistoryWithoutWriting(t *testing.T) {
	path, body := keyFileFixture(t)
	before, _ := os.Stat(path)
	ring, err := LoadKeyBundleFile(path)
	if err != nil || ring.ActiveEncryptionID() != newEnc || ring.ActiveIdempotencyID() != newMac {
		t.Fatal("load failed", err)
	}
	present, _ := os.Stat(path)
	loadedBody, err := os.ReadFile(path)
	if err != nil || !bytes.Equal(body, loadedBody) || !before.ModTime().Equal(present.ModTime()) || !os.SameFile(before, present) {
		t.Fatal("loader wrote or replaced the source")
	}
	ctx := Context{"scope", "device", "credential", 1, strings.Repeat("a", 64)}
	secret, _ := NewSecret("synthetic-user", "synthetic-password")
	envelope, _ := testRing(t, false).Seal(ctx, secret, Reservation{oldEnc, 1})
	if recovered, err := ring.Open(ctx, envelope); err != nil || recovered.Password() != secret.Password() {
		t.Fatal("historical key lost", err)
	}
	scope := RequestScope{"admin", "POST", "/api/v1/credentials", strings.Repeat("b", 64)}
	previous, _ := testRing(t, false).Fingerprint(scope, []byte("synthetic-request"))
	if matched, err := ring.Match(scope, []byte("synthetic-request"), previous); err != nil || !matched {
		t.Fatal("old HMAC lost", err)
	}
	if err := os.WriteFile(path, []byte("changed-after-load"), 0600); err != nil {
		t.Fatal(err)
	}
	if recovered, err := ring.Open(ctx, envelope); err != nil || recovered.Password() != secret.Password() {
		t.Fatal("ring aliases file", err)
	}
	if _, err := json.Marshal(ring); !errors.Is(err, ErrDisclosure) {
		t.Fatal("ring serialized")
	}
	if err := os.WriteFile(path, body, 0600); err != nil {
		t.Fatal(err)
	}
	after, _ := os.Stat(path)
	if !os.SameFile(before, after) || after.Mode().Perm() != 0600 {
		t.Fatal("loader altered file")
	}
}

func TestPrivateKeyFileRejectsPermissionsWithoutRepair(t *testing.T) {
	for _, mode := range []os.FileMode{0644, 0640, 0660, 0200, 0600 | os.ModeSetuid} {
		path, body := keyFileFixture(t)
		if err := os.Chmod(path, mode); err != nil {
			t.Fatal(err)
		}
		rejectedKeyFile(t, path)
		info, _ := os.Stat(path)
		if info.Mode()&(os.ModePerm|os.ModeSetuid) != mode {
			t.Fatal("loader repaired permissions")
		}
		if err := os.Chmod(path, 0600); err != nil {
			t.Fatal(err)
		}
		current, _ := os.ReadFile(path)
		if !bytes.Equal(body, current) {
			t.Fatal("rejected file changed")
		}
	}
	path, _ := keyFileFixture(t)
	if err := os.Chmod(filepath.Dir(path), 0755); err != nil {
		t.Fatal(err)
	}
	rejectedKeyFile(t, path)
}

func TestPrivateKeyFileRejectsRedirectsAndSpecialFiles(t *testing.T) {
	path, _ := keyFileFixture(t)
	alias := filepath.Join(filepath.Dir(path), "alias.json")
	if err := os.Symlink(path, alias); err != nil {
		t.Fatal(err)
	}
	rejectedKeyFile(t, alias)
	ancestor := filepath.Join(filepath.Dir(filepath.Dir(path)), "linked-directory")
	if err := os.Symlink(filepath.Dir(path), ancestor); err != nil {
		t.Fatal(err)
	}
	rejectedKeyFile(t, filepath.Join(ancestor, filepath.Base(path)))
	if err := os.Link(path, alias+"-hard"); err != nil {
		t.Fatal(err)
	}
	rejectedKeyFile(t, path)
	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}
	if err := syscall.Mkfifo(path, 0600); err != nil {
		t.Fatal(err)
	}
	rejectedKeyFile(t, path)
	rejectedKeyFile(t, filepath.Dir(path))
}

func TestPrivateKeyFileRejectsMalformedMissingAndRelativePaths(t *testing.T) {
	for _, body := range [][]byte{nil, []byte("{}"), []byte("synthetic-private-key-invalid"), bytes.Repeat([]byte{' '}, MaxBundleBytes+1), []byte(`{"format_version":1,"format_version":1}`)} {
		path, _ := keyFileFixture(t)
		if err := os.WriteFile(path, body, 0600); err != nil {
			t.Fatal(err)
		}
		rejectedKeyFile(t, path)
	}
	for _, path := range []string{"", "relative/key-bundle.json", "/", "/tmp//keys.json", "/tmp/../keys.json", "/does-not-exist/private-credential-key"} {
		rejectedKeyFile(t, path)
	}
}

func TestPrivateKeyFileAcceptsReadOnlyModesAndRejectsForeignUID(t *testing.T) {
	path, _ := keyFileFixture(t)
	if err := os.Chmod(path, 0400); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(filepath.Dir(path), 0500); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.Chmod(filepath.Dir(path), 0700) })
	if _, err := LoadKeyBundleFile(path); err != nil {
		t.Fatal("read-only file failed", err)
	}
	info := syscall.Stat_t{Mode: syscall.S_IFREG | 0400, Uid: uint32(os.Geteuid() + 1), Nlink: 1, Size: 100}
	if validPrivateKeyFile(info) {
		t.Fatal("foreign UID accepted")
	}
	// Native Docker verification supplies a DSN and can change actual file UID.
	// Local virtual filesystems still verify the UID decision with a synthetic stat.
	if os.Geteuid() == 0 && os.Getenv("CAMERA_TEST_DATABASE_URL") != "" && os.Getenv("CAMERA_TEST_ENGINE") != "pglite" {
		if err := os.Chmod(filepath.Dir(path), 0700); err != nil {
			t.Fatal(err)
		}
		if err := os.Chown(path, 1, -1); err != nil {
			t.Fatal(err)
		}
		rejectedKeyFile(t, path)
	}
}

func TestPrivateKeyFileDetectsChangedIdentityAndMetadata(t *testing.T) {
	a := syscall.Stat_t{Dev: 1, Ino: 2, Mode: syscall.S_IFREG | 0600, Uid: uint32(os.Geteuid()), Nlink: 1, Size: 100}
	if !samePrivateKeyFile(a, a) {
		t.Fatal("stable metadata rejected")
	}
	for _, change := range []func(*syscall.Stat_t){func(s *syscall.Stat_t) { s.Ino++ }, func(s *syscall.Stat_t) { s.Dev++ }, func(s *syscall.Stat_t) { s.Mode = 0644 }, func(s *syscall.Stat_t) { s.Size++ }, func(s *syscall.Stat_t) { s.Uid++ }, func(s *syscall.Stat_t) { s.Gid++ }, func(s *syscall.Stat_t) { s.Nlink++ }, func(s *syscall.Stat_t) { s.Mtim.Nsec++ }, func(s *syscall.Stat_t) { s.Ctim.Nsec++ }} {
		b := a
		change(&b)
		if samePrivateKeyFile(a, b) {
			t.Fatal("metadata drift accepted")
		}
	}
}
