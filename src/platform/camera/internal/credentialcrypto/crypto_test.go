package credentialcrypto

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"sync"
	"testing"
)

func testContext() Context {
	return Context{"site-1", "device-1", "credential-1", 1, strings.Repeat("a", 64)}
}
func testScope() RequestScope {
	return RequestScope{"admin-1", "POST", "/api/v1/credentials", strings.Repeat("b", 64)}
}
func testSecret(t *testing.T) Secret {
	t.Helper()
	s, err := NewSecret("합성 사용자", " synthetic password <> ")
	if err != nil {
		t.Fatal(err)
	}
	return s
}
func sealed(t *testing.T, k *Keyring) Envelope {
	t.Helper()
	e, err := k.Seal(testContext(), testSecret(t), Reservation{k.ActiveEncryptionID(), 1})
	if err != nil {
		t.Fatal(err)
	}
	return e
}
func requireZeroSecret(t *testing.T, s Secret, err, want error) {
	t.Helper()
	if !errors.Is(err, want) || s.Username() != "" || s.Password() != "" {
		t.Fatalf("unexpected failure: %v", err)
	}
}

func TestSecretValidationAndRedaction(t *testing.T) {
	cases := []struct{ name, user, password string }{
		{"empty user", "", "p"}, {"empty password", "u", ""}, {"whitespace user", " \u3000 ", "p"},
		{"long user", strings.Repeat("u", 129), "p"}, {"long password", "u", strings.Repeat("p", 4097)},
		{"invalid user UTF8", string([]byte{0xff}), "p"}, {"invalid password UTF8", "u", string([]byte{0xff})},
		{"user control", "u\n", "p"}, {"password control", "u", "p\x00"}, {"DEL", "u", "p\x7f"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) { s, err := NewSecret(c.user, c.password); requireZeroSecret(t, s, err, ErrSecret) })
	}
	s := testSecret(t)
	for _, value := range []any{s, &s, struct{ Secret Secret }{s}} {
		for _, format := range []string{"%v", "%+v", "%#v"} {
			out := fmt.Sprintf(format, value)
			if strings.Contains(out, s.Username()) || strings.Contains(out, s.Password()) || !strings.Contains(out, "redacted") {
				t.Fatal("secret formatting disclosed")
			}
		}
		if _, err := json.Marshal(value); !errors.Is(err, ErrDisclosure) {
			t.Fatal("secret JSON allowed")
		}
	}
	if _, err := NewSecret("u", "   "); err != nil {
		t.Fatal("password whitespace must be preserved")
	}
}

func TestSealOpenRoundTripAndNonce(t *testing.T) {
	k := testRing(t, false)
	s := testSecret(t)
	e := sealed(t, k)
	recovered, err := k.Open(testContext(), e)
	if err != nil || recovered != s {
		t.Fatalf("round trip failed: %v", err)
	}
	next, err := k.Seal(testContext(), s, Reservation{oldEnc, 2})
	if err != nil {
		t.Fatal(err)
	}
	if bytes.Equal(e.Ciphertext[:12], next.Ciphertext[:12]) {
		t.Fatal("nonce reused")
	}
	if bytes.Contains(e.Ciphertext, []byte(s.Username())) || bytes.Contains(e.Ciphertext, []byte(s.Password())) {
		t.Fatal("plaintext ciphertext")
	}
	wire, err := json.Marshal(e)
	if err != nil {
		t.Fatal(err)
	}
	var transported Envelope
	if err := json.Unmarshal(wire, &transported); err != nil {
		t.Fatal(err)
	}
	if recovered, err := k.Open(testContext(), transported); err != nil || recovered != s {
		t.Fatal("envelope transport failed")
	}
}

func TestMaximumEscapedSecretRoundTrip(t *testing.T) {
	k := testRing(t, false)
	s, err := NewSecret(strings.Repeat("<", 128), strings.Repeat("&", 4096))
	if err != nil {
		t.Fatal(err)
	}
	e, err := k.Seal(testContext(), s, Reservation{oldEnc, 1})
	if err != nil {
		t.Fatal(err)
	}
	if recovered, err := k.Open(testContext(), e); err != nil || recovered != s {
		t.Fatalf("maximum allowed secret rejected: %v", err)
	}
}

func TestContextSubstitutionFailsAuthentication(t *testing.T) {
	k := testRing(t, false)
	e := sealed(t, k)
	for name, change := range map[string]func(*Context){
		"scope": func(c *Context) { c.ScopeID = "site-2" }, "device": func(c *Context) { c.DeviceID = "device-2" },
		"credential": func(c *Context) { c.CredentialID = "credential-2" }, "version": func(c *Context) { c.CredentialVersion = 2 },
		"policy": func(c *Context) { c.TargetPolicySHA256 = strings.Repeat("c", 64) },
	} {
		t.Run(name, func(t *testing.T) {
			c := testContext()
			change(&c)
			s, err := k.Open(c, e)
			requireZeroSecret(t, s, err, ErrAuthentication)
		})
	}
}

func TestCiphertextAndAuthenticatedMetadataTampering(t *testing.T) {
	k := testRing(t, true)
	e := sealed(t, k)
	for _, index := range []int{0, 12, len(e.Ciphertext) - 1} {
		t.Run(fmt.Sprint(index), func(t *testing.T) {
			changed := e
			changed.Ciphertext = bytes.Clone(e.Ciphertext)
			changed.Ciphertext[index] ^= 1
			s, err := k.Open(testContext(), changed)
			requireZeroSecret(t, s, err, ErrAuthentication)
		})
	}
	for name, change := range map[string]func(*Envelope){"sequence": func(e *Envelope) { e.EncryptionUse++ }, "existing other key": func(e *Envelope) { e.KeyID = oldEnc }} {
		t.Run(name, func(t *testing.T) {
			changed := e
			change(&changed)
			s, err := k.Open(testContext(), changed)
			requireZeroSecret(t, s, err, ErrAuthentication)
		})
	}
}

func TestEnvelopeRejectionAndMissingExactKey(t *testing.T) {
	k := testRing(t, false)
	e := sealed(t, k)
	for name, change := range map[string]func(*Envelope){
		"version": func(e *Envelope) { e.FormatVersion = 2 }, "algorithm": func(e *Envelope) { e.Algorithm = "AES-CBC" },
		"bad ID": func(e *Envelope) { e.KeyID = oldMac }, "zero use": func(e *Envelope) { e.EncryptionUse = 0 },
		"over budget": func(e *Envelope) { e.EncryptionUse = MaxEncryptionUse + 1 }, "short ciphertext": func(e *Envelope) { e.Ciphertext = make([]byte, 27) },
		"long ciphertext": func(e *Envelope) { e.Ciphertext = make([]byte, maxSecretWireBytes+29) },
	} {
		t.Run(name, func(t *testing.T) {
			changed := e
			change(&changed)
			s, err := k.Open(testContext(), changed)
			requireZeroSecret(t, s, err, ErrEnvelope)
		})
	}
	e.KeyID = newEnc
	s, err := k.Open(testContext(), e)
	requireZeroSecret(t, s, err, ErrKeyUnavailable)
	var absent *Keyring
	s, err = absent.Open(testContext(), sealed(t, k))
	requireZeroSecret(t, s, err, ErrKeyUnavailable)
}

func TestSealRequiresValidContextSecretAndReservation(t *testing.T) {
	k := testRing(t, false)
	s := testSecret(t)
	for name, change := range map[string]func(*Context){
		"empty scope": func(c *Context) { c.ScopeID = "" }, "bad device": func(c *Context) { c.DeviceID = "device/1" },
		"bad credential": func(c *Context) { c.CredentialID = " " }, "zero version": func(c *Context) { c.CredentialVersion = 0 },
		"negative version": func(c *Context) { c.CredentialVersion = -1 }, "uppercase policy": func(c *Context) { c.TargetPolicySHA256 = strings.Repeat("A", 64) },
	} {
		t.Run(name, func(t *testing.T) {
			c := testContext()
			change(&c)
			if e, err := k.Seal(c, s, Reservation{oldEnc, 1}); !errors.Is(err, ErrContext) || e.Ciphertext != nil {
				t.Fatal("context accepted")
			}
			got, err := k.Open(c, sealed(t, k))
			requireZeroSecret(t, got, err, ErrContext)
		})
	}
	for _, r := range []Reservation{{oldEnc, 0}, {oldEnc, MaxEncryptionUse + 1}, {newEnc, 1}, {oldMac, 1}} {
		if _, err := k.Seal(testContext(), s, r); !errors.Is(err, ErrReservation) {
			t.Fatal("reservation accepted")
		}
	}
	if e, err := k.Seal(testContext(), s, Reservation{oldEnc, MaxEncryptionUse}); err != nil {
		t.Fatal(err)
	} else if _, err := k.Open(testContext(), e); err != nil {
		t.Fatal(err)
	}
	if _, err := k.Seal(testContext(), Secret{}, Reservation{oldEnc, 1}); !errors.Is(err, ErrSecret) {
		t.Fatal("zero secret accepted")
	}
	var absent *Keyring
	if _, err := absent.Seal(testContext(), s, Reservation{oldEnc, 1}); !errors.Is(err, ErrKeyUnavailable) {
		t.Fatal("nil keyring accepted")
	}
}

func TestAuthenticatedInvalidSecretWireRejected(t *testing.T) {
	k := testRing(t, false)
	e := sealed(t, k)
	for name, body := range map[string][]byte{
		"unknown":    []byte(`{"username":"u","password":"p","extra":1}`),
		"duplicate":  []byte(`{"username":"u","password":"p","pass\u0077ord":"other"}`),
		"case alias": []byte(`{"Username":"u","password":"p"}`),
		"missing":    []byte(`{"username":"u"}`), "invalid": []byte(`{"username":"u","password":""}`),
		"trailing": []byte(`{"username":"u","password":"p"} {}`),
	} {
		t.Run(name, func(t *testing.T) {
			changed := e
			changed.Ciphertext = aead(k.encryption[oldEnc]).Seal(nil, nil, body, aad(testContext(), changed))
			s, err := k.Open(testContext(), changed)
			requireZeroSecret(t, s, err, ErrSecret)
		})
	}
}

func TestHistoricalKeysRotationAndIsolatedRestore(t *testing.T) {
	old := testRing(t, false)
	e := sealed(t, old)
	payload := []byte(`{"synthetic":"request"}`)
	f, err := old.Fingerprint(testScope(), payload)
	if err != nil {
		t.Fatal(err)
	}
	rotated := testRing(t, true)
	s, err := rotated.Open(testContext(), e)
	if err != nil || s != testSecret(t) {
		t.Fatal("old key no longer readable")
	}
	if ok, err := rotated.Match(testScope(), payload, f); err != nil || !ok {
		t.Fatal("old HMAC not replayable")
	}
	rewrapped, err := rotated.Seal(testContext(), s, Reservation{newEnc, 1})
	if err != nil || rewrapped.KeyID != newEnc {
		t.Fatal("rewrap failed")
	}
	backup := bytes.Clone(bundleBytes(t, testBundle(true)))
	restored, err := ParseKeyBundle(backup)
	clear(backup)
	if err != nil {
		t.Fatal(err)
	}
	for _, saved := range []Envelope{e, rewrapped} {
		if got, err := restored.Open(testContext(), saved); err != nil || got != s {
			t.Fatal("restored key bundle failed")
		}
	}
	if ok, err := restored.Match(testScope(), payload, f); err != nil || !ok {
		t.Fatal("restored historical HMAC failed")
	}
	b := testBundle(true)
	delete(b.Encryption.Keys, oldEnc)
	delete(b.Idempotency.Keys, oldMac)
	missing, err := ParseKeyBundle(bundleBytes(t, b))
	if err != nil {
		t.Fatal(err)
	}
	got, err := missing.Open(testContext(), e)
	requireZeroSecret(t, got, err, ErrKeyUnavailable)
	if ok, err := missing.Match(testScope(), payload, f); ok || !errors.Is(err, ErrKeyUnavailable) {
		t.Fatal("missing historical HMAC fell back")
	}
}

func TestFingerprintScopeAndRequestBinding(t *testing.T) {
	k := testRing(t, false)
	payload := []byte(`{"password":"synthetic"}`)
	f, err := k.Fingerprint(testScope(), payload)
	if err != nil {
		t.Fatal(err)
	}
	if ok, err := k.Match(testScope(), payload, f); err != nil || !ok {
		t.Fatal("match failed")
	}
	if ok, err := k.Match(testScope(), []byte(`{"password":"changed"}`), f); err != nil || ok {
		t.Fatal("changed request matched")
	}
	for name, change := range map[string]func(*RequestScope){
		"principal": func(s *RequestScope) { s.PrincipalID = "admin-2" }, "method": func(s *RequestScope) { s.Method = "PUT" },
		"path": func(s *RequestScope) { s.Path = "/api/v1/credentials/other" }, "idempotency key": func(s *RequestScope) { s.IdempotencyKeySHA256 = strings.Repeat("c", 64) },
	} {
		t.Run(name, func(t *testing.T) {
			scope := testScope()
			change(&scope)
			if ok, err := k.Match(scope, payload, f); err != nil || ok {
				t.Fatal("changed scope matched")
			}
		})
	}
	next, err := testRing(t, true).Fingerprint(testScope(), payload)
	if err != nil || next.KeyID != newMac || next.Digest == f.Digest {
		t.Fatal("HMAC key rotation not separated")
	}
}

func TestFingerprintRejectsInvalidScopeAndWire(t *testing.T) {
	k := testRing(t, false)
	payload := []byte("synthetic")
	f, err := k.Fingerprint(testScope(), payload)
	if err != nil {
		t.Fatal(err)
	}
	for _, path := range []string{"/api/v1/credentials?x=1", "/api/v1/../credentials", "/api/v1/%63redentials", "/api/v1//credentials", "/api/v1/credentials/", "/credentials", "/api/v1/creds\\other", "/api/v1/" + strings.Repeat("x", 256)} {
		scope := testScope()
		scope.Path = path
		if _, err := k.Fingerprint(scope, payload); !errors.Is(err, ErrFingerprint) {
			t.Fatal("bad path accepted")
		}
	}
	for name, change := range map[string]func(*RequestScope){"principal": func(s *RequestScope) { s.PrincipalID = "" }, "method": func(s *RequestScope) { s.Method = "GET" }, "digest": func(s *RequestScope) { s.IdempotencyKeySHA256 = "raw-key" }} {
		t.Run(name, func(t *testing.T) {
			scope := testScope()
			change(&scope)
			if _, err := k.Fingerprint(scope, payload); !errors.Is(err, ErrFingerprint) {
				t.Fatal("bad scope accepted")
			}
		})
	}
	for name, change := range map[string]func(*Fingerprint){"format": func(f *Fingerprint) { f.FormatVersion = 2 }, "algorithm": func(f *Fingerprint) { f.Algorithm = "SHA256" }, "purpose": func(f *Fingerprint) { f.KeyID = oldEnc }, "digest": func(f *Fingerprint) { f.Digest = strings.Repeat("A", 64) }} {
		t.Run(name, func(t *testing.T) {
			previous := f
			change(&previous)
			if ok, err := k.Match(testScope(), payload, previous); ok || !errors.Is(err, ErrFingerprint) {
				t.Fatal("bad fingerprint accepted")
			}
		})
	}
	for _, body := range [][]byte{nil, make([]byte, 65537)} {
		if _, err := k.Fingerprint(testScope(), body); !errors.Is(err, ErrFingerprint) {
			t.Fatal("invalid canonical length accepted")
		}
		if ok, err := k.Match(testScope(), body, f); ok || !errors.Is(err, ErrFingerprint) {
			t.Fatal("invalid match body accepted")
		}
	}
	var absent *Keyring
	if _, err := absent.Fingerprint(testScope(), payload); !errors.Is(err, ErrKeyUnavailable) {
		t.Fatal("nil fingerprint accepted")
	}
	if ok, err := absent.Match(testScope(), payload, f); ok || !errors.Is(err, ErrKeyUnavailable) {
		t.Fatal("nil match accepted")
	}
}

func TestImmutableKeyringConcurrentUse(t *testing.T) {
	k := testRing(t, true)
	s := testSecret(t)
	var wg sync.WaitGroup
	for i := uint64(1); i <= 32; i++ {
		wg.Add(1)
		go func(use uint64) {
			defer wg.Done()
			e, err := k.Seal(testContext(), s, Reservation{newEnc, use})
			if err != nil {
				t.Error(err)
				return
			}
			got, err := k.Open(testContext(), e)
			if err != nil || got != s {
				t.Error("concurrent decrypt failed")
			}
			f, err := k.Fingerprint(testScope(), []byte("synthetic"))
			if err != nil {
				t.Error(err)
				return
			}
			if ok, err := k.Match(testScope(), []byte("synthetic"), f); err != nil || !ok {
				t.Error("concurrent fingerprint failed")
			}
		}(i)
	}
	wg.Wait()
}
