//go:build linux

package credentialcrypto

import (
	"crypto/sha256"
	"encoding/hex"
	"os"
	"testing"
)

func TestProtectedReceiptRequiresActualFileLoad(t *testing.T) {
	ring := testRing(t, false)
	if hash, ro, err := ring.ProtectedBundleReceipt(); hash != "" || ro || err != ErrKeyFile {
		t.Fatal("parser forged file receipt")
	}
	var missing *Keyring
	if _, _, err := missing.ProtectedBundleReceipt(); err != ErrKeyFile {
		t.Fatal("nil receipt accepted")
	}
}

func TestProtectedReceiptBindsExactBytesAndImmutableKeys(t *testing.T) {
	path, body := keyFileFixture(t)
	a, err := LoadKeyBundleFile(path)
	if err != nil {
		t.Fatal(err)
	}
	digest := sha256.Sum256(body)
	before, ro, err := a.ProtectedBundleReceipt()
	if err != nil || before != hex.EncodeToString(digest[:]) || ro {
		t.Fatal("wrong exact-byte receipt or writable mount claimed RO")
	}
	changed := append(append([]byte{}, body...), []byte("\n ")...)
	if err = os.WriteFile(path, changed, 0600); err != nil {
		t.Fatal(err)
	}
	b, err := LoadKeyBundleFile(path)
	if err != nil {
		t.Fatal(err)
	}
	after, _, _ := b.ProtectedBundleReceipt()
	still, _, _ := a.ProtectedBundleReceipt()
	if after == before || still != before || a.ActiveEncryptionID() != b.ActiveEncryptionID() || a.ActiveIdempotencyID() != b.ActiveIdempotencyID() {
		t.Fatal("receipt aliases file or canonicalizes bytes")
	}
	if err = os.Chmod(path, 0400); err != nil {
		t.Fatal(err)
	}
	c, err := LoadKeyBundleFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if _, readonly, _ := c.ProtectedBundleReceipt(); readonly {
		t.Fatal("mode0400 on RW mount accepted as read-only mount")
	}
}
