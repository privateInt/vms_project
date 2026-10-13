package credentialcrypto

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"testing"
)

const oldEnc = "enc-1111111111111111"
const newEnc = "enc-3333333333333333"
const oldMac = "idem-2222222222222222"
const newMac = "idem-4444444444444444"

func testBundle(rotated bool) keyBundle {
	b := keyBundle{1,
		keySet{oldEnc, map[string]string{oldEnc: base64.StdEncoding.EncodeToString(bytes.Repeat([]byte{1}, 32))}},
		keySet{oldMac, map[string]string{oldMac: base64.StdEncoding.EncodeToString(bytes.Repeat([]byte{2}, 32))}}}
	if rotated {
		b.Encryption.Active = newEnc
		b.Idempotency.Active = newMac
		b.Encryption.Keys[newEnc] = base64.StdEncoding.EncodeToString(bytes.Repeat([]byte{3}, 32))
		b.Idempotency.Keys[newMac] = base64.StdEncoding.EncodeToString(bytes.Repeat([]byte{4}, 32))
	}
	return b
}

func bundleBytes(t *testing.T, b keyBundle) []byte {
	t.Helper()
	data, err := json.Marshal(b)
	if err != nil {
		t.Fatal(err)
	}
	return data
}

func testRing(t *testing.T, rotated bool) *Keyring {
	t.Helper()
	k, err := ParseKeyBundle(bundleBytes(t, testBundle(rotated)))
	if err != nil {
		t.Fatal(err)
	}
	return k
}

func TestKeyBundleRejectsMalformedWire(t *testing.T) {
	valid := bundleBytes(t, testBundle(false))
	cases := map[string][]byte{
		"empty":             nil,
		"oversize":          bytes.Repeat([]byte{' '}, MaxBundleBytes+1),
		"invalid UTF8":      {0xff},
		"array":             []byte(`[]`),
		"null":              []byte(`null`),
		"trailing":          append(bytes.Clone(valid), []byte(` {}`)...),
		"duplicate escaped": bytes.Replace(valid, []byte(`"format_version":1`), []byte(`"format_version":1,"for\u006dat_version":1`), 1),
		"case alias":        bytes.Replace(valid, []byte(`"format_version"`), []byte(`"FORMAT_VERSION"`), 1),
		"nested case alias": bytes.Replace(valid, []byte(`"active_key_id"`), []byte(`"ACTIVE_KEY_ID"`), 1),
		"unknown":           bytes.Replace(valid, []byte(`"format_version":1`), []byte(`"format_version":1,"extra":0`), 1),
		"boolean format":    bytes.Replace(valid, []byte(`"format_version":1`), []byte(`"format_version":true`), 1),
		"float format":      bytes.Replace(valid, []byte(`"format_version":1`), []byte(`"format_version":1.0`), 1),
		"exponent format":   bytes.Replace(valid, []byte(`"format_version":1`), []byte(`"format_version":1e0`), 1),
		"NaN":               []byte(`{"format_version":NaN}`),
		"depth":             []byte(strings.Repeat("[", 18) + "1" + strings.Repeat("]", 18)),
	}
	for name, data := range cases {
		t.Run(name, func(t *testing.T) {
			k, err := ParseKeyBundle(data)
			if k != nil || !errors.Is(err, ErrKeyBundle) || err.Error() != "CREDENTIAL_KEY_BUNDLE_INVALID" {
				t.Fatalf("unexpected rejection: %v", err)
			}
		})
	}
}

func TestKeyBundleRejectsInvalidHistory(t *testing.T) {
	cases := map[string]func(*keyBundle){
		"version":                func(b *keyBundle) { b.Format = 2 },
		"empty history":          func(b *keyBundle) { b.Encryption.Keys = nil },
		"missing active":         func(b *keyBundle) { b.Encryption.Active = newEnc },
		"wrong purpose":          func(b *keyBundle) { b.Encryption.Keys[oldMac] = b.Encryption.Keys[oldEnc] },
		"uppercase ID":           func(b *keyBundle) { b.Encryption.Active = "enc-AAAAAAAAAAAAAAAA" },
		"bad base64":             func(b *keyBundle) { b.Encryption.Keys[oldEnc] = "!" },
		"short key":              func(b *keyBundle) { b.Encryption.Keys[oldEnc] = base64.StdEncoding.EncodeToString(make([]byte, 31)) },
		"newline base64":         func(b *keyBundle) { b.Encryption.Keys[oldEnc] += "\n" },
		"unpadded base64":        func(b *keyBundle) { b.Encryption.Keys[oldEnc] = strings.TrimRight(b.Encryption.Keys[oldEnc], "=") },
		"same cross purpose key": func(b *keyBundle) { b.Idempotency.Keys[oldMac] = b.Encryption.Keys[oldEnc] },
		"same history key":       func(b *keyBundle) { b.Encryption.Keys[newEnc] = b.Encryption.Keys[oldEnc] },
		"too many keys": func(b *keyBundle) {
			for i := 2; i <= 17; i++ {
				b.Encryption.Keys[fmt.Sprintf("enc-%016x", i)] = base64.StdEncoding.EncodeToString(bytes.Repeat([]byte{byte(i + 5)}, 32))
			}
		},
	}
	for name, change := range cases {
		t.Run(name, func(t *testing.T) {
			b := testBundle(false)
			change(&b)
			if k, err := ParseKeyBundle(bundleBytes(t, b)); k != nil || !errors.Is(err, ErrKeyBundle) {
				t.Fatalf("unexpected rejection: %v", err)
			}
		})
	}
}

func TestKeyringOwnsParsedBytesAndHidesKeys(t *testing.T) {
	input := bundleBytes(t, testBundle(true))
	k, err := ParseKeyBundle(input)
	if err != nil {
		t.Fatal(err)
	}
	clear(input)
	if k.ActiveEncryptionID() != newEnc || k.ActiveIdempotencyID() != newMac {
		t.Fatal("wrong active IDs")
	}
	var absent *Keyring
	if absent.ActiveEncryptionID() != "" || absent.ActiveIdempotencyID() != "" {
		t.Fatal("nil ID access")
	}
	for _, value := range []any{k, *k, struct{ Ring *Keyring }{k}} {
		for _, format := range []string{"%v", "%+v", "%#v"} {
			out := fmt.Sprintf(format, value)
			if strings.Contains(out, testBundle(false).Encryption.Keys[oldEnc]) || strings.Contains(out, "encryption:map") || !strings.Contains(out, "redacted") {
				t.Fatal("private key formatting disclosed")
			}
		}
		if _, err := json.Marshal(value); !errors.Is(err, ErrDisclosure) {
			t.Fatal("private key JSON allowed")
		}
	}
}
