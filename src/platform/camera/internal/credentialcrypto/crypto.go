package credentialcrypto

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"strings"
	"unicode/utf8"
)

// MaxEncryptionUse stays below the random-GCM 2^32 messages/key limit. A
// persistent, atomic per-key budget must reserve each use before Seal; failed
// attempts consume their reservation. Process-local counters are insufficient.
const MaxEncryptionUse uint64 = (1 << 32) - 1

// Includes the worst-case six-byte JSON escape of each allowed input byte.
const maxSecretWireBytes = 32768

type Secret struct{ username, password string }
type secretWire struct {
	Username string `json:"username"`
	Password string `json:"password"`
}

func NewSecret(username, password string) (Secret, error) {
	valid := func(value string, max int) bool {
		if len(value) < 1 || len(value) > max || !utf8.ValidString(value) {
			return false
		}
		for _, r := range value {
			if r < 32 || r == 127 {
				return false
			}
		}
		return true
	}
	if !valid(username, 128) || strings.TrimSpace(username) == "" || !valid(password, 4096) {
		return Secret{}, ErrSecret
	}
	return Secret{username, password}, nil
}
func (s Secret) Username() string             { return s.username }
func (s Secret) Password() string             { return s.password }
func (s Secret) String() string               { return "credentialcrypto.Secret([redacted])" }
func (s Secret) GoString() string             { return s.String() }
func (s Secret) MarshalJSON() ([]byte, error) { return nil, ErrDisclosure }

type Context struct {
	ScopeID            string `json:"scope_id"`
	DeviceID           string `json:"device_id"`
	CredentialID       string `json:"credential_id"`
	CredentialVersion  int64  `json:"credential_version"`
	TargetPolicySHA256 string `json:"target_policy_sha256"`
}

func (c Context) valid() bool {
	return identifier.MatchString(c.ScopeID) && identifier.MatchString(c.DeviceID) &&
		identifier.MatchString(c.CredentialID) && c.CredentialVersion >= 1 && hexDigest.MatchString(c.TargetPolicySHA256)
}

// Reservation is issued by the future trusted storage ledger, never by an HTTP
// request. This primitive checks its range/key; it cannot prove global uniqueness.
type Reservation struct {
	KeyID string
	Use   uint64
}
type Envelope struct {
	FormatVersion int    `json:"format_version"`
	Algorithm     string `json:"algorithm"`
	KeyID         string `json:"key_id"`
	EncryptionUse uint64 `json:"encryption_use"`
	Ciphertext    []byte `json:"ciphertext"` // 12-byte random nonce, payload, 16-byte tag.
}

func aad(c Context, e Envelope) []byte {
	v := struct {
		Purpose   string  `json:"purpose"`
		Format    int     `json:"format_version"`
		Algorithm string  `json:"algorithm"`
		KeyID     string  `json:"key_id"`
		Use       uint64  `json:"encryption_use"`
		Context   Context `json:"context"`
	}{"camera-credential-secret-v1", e.FormatVersion, e.Algorithm, e.KeyID, e.EncryptionUse, c}
	body, _ := json.Marshal(v)
	return body
}
func aead(key [32]byte) cipher.AEAD {
	block, _ := aes.NewCipher(key[:])
	gcm, _ := cipher.NewGCMWithRandomNonce(block)
	return gcm
}

func (k *Keyring) Seal(c Context, s Secret, reservation Reservation) (Envelope, error) {
	if !c.valid() {
		return Envelope{}, ErrContext
	}
	if _, err := NewSecret(s.username, s.password); err != nil {
		return Envelope{}, ErrSecret
	}
	if k == nil {
		return Envelope{}, ErrKeyUnavailable
	}
	key, ok := k.encryption[k.activeEncryption]
	if !ok {
		return Envelope{}, ErrKeyUnavailable
	}
	if reservation.KeyID != k.activeEncryption || reservation.Use < 1 || reservation.Use > MaxEncryptionUse {
		return Envelope{}, ErrReservation
	}
	e := Envelope{FormatVersion: 1, Algorithm: "AES-256-GCM-RANDOM-NONCE", KeyID: k.activeEncryption, EncryptionUse: reservation.Use}
	body, err := json.Marshal(secretWire{s.username, s.password})
	if err != nil {
		return Envelope{}, ErrSecret
	}
	e.Ciphertext = aead(key).Seal(nil, nil, body, aad(c, e))
	clear(body)
	return e, nil
}

func (k *Keyring) Open(c Context, e Envelope) (Secret, error) {
	if !c.valid() {
		return Secret{}, ErrContext
	}
	if e.FormatVersion != 1 || e.Algorithm != "AES-256-GCM-RANDOM-NONCE" || !encID.MatchString(e.KeyID) ||
		e.EncryptionUse < 1 || e.EncryptionUse > MaxEncryptionUse || len(e.Ciphertext) < 28 || len(e.Ciphertext) > maxSecretWireBytes+28 {
		return Secret{}, ErrEnvelope
	}
	if k == nil {
		return Secret{}, ErrKeyUnavailable
	}
	key, ok := k.encryption[e.KeyID]
	if !ok {
		return Secret{}, ErrKeyUnavailable
	}
	body, err := aead(key).Open(nil, nil, e.Ciphertext, aad(c, e))
	if err != nil {
		return Secret{}, ErrAuthentication
	}
	defer clear(body)
	var wire secretWire
	if err := strictDecode(body, maxSecretWireBytes, &wire); err != nil {
		return Secret{}, ErrSecret
	}
	if _, ok := exactFields(body, "username", "password"); !ok {
		return Secret{}, ErrSecret
	}
	return NewSecret(wire.Username, wire.Password)
}

type RequestScope struct {
	PrincipalID          string `json:"principal_id"`
	Method               string `json:"method"`
	Path                 string `json:"path"`
	IdempotencyKeySHA256 string `json:"idempotency_key_sha256"`
}

func (s RequestScope) valid() bool {
	if !identifier.MatchString(s.PrincipalID) || !hexDigest.MatchString(s.IdempotencyKeySHA256) ||
		(s.Method != "POST" && s.Method != "PUT" && s.Method != "PATCH" && s.Method != "DELETE") ||
		len(s.Path) > 256 || !strings.HasPrefix(s.Path, "/api/v1/") || strings.Contains(s.Path, "//") {
		return false
	}
	for _, segment := range strings.Split(strings.TrimPrefix(s.Path, "/"), "/") {
		if !identifier.MatchString(segment) || segment == "." || segment == ".." {
			return false
		}
	}
	return true
}

type Fingerprint struct {
	FormatVersion int    `json:"format_version"`
	Algorithm     string `json:"algorithm"`
	KeyID         string `json:"key_id"`
	Digest        string `json:"digest"`
}

// Canonical bytes must come from strict, validated DTO serialization. This layer
// neither parses untrusted JSON nor persists the private request bytes.
func digest(key [32]byte, scope RequestScope, canonical []byte) string {
	mac := hmac.New(sha256.New, key[:])
	header, _ := json.Marshal(struct {
		Purpose string       `json:"purpose"`
		Scope   RequestScope `json:"scope"`
	}{"camera-private-request-v1", scope})
	var size [8]byte
	binary.BigEndian.PutUint64(size[:], uint64(len(header)))
	mac.Write(size[:])
	mac.Write(header)
	binary.BigEndian.PutUint64(size[:], uint64(len(canonical)))
	mac.Write(size[:])
	mac.Write(canonical)
	return hex.EncodeToString(mac.Sum(nil))
}
func (k *Keyring) Fingerprint(scope RequestScope, canonical []byte) (Fingerprint, error) {
	if !scope.valid() || len(canonical) < 1 || len(canonical) > 65536 {
		return Fingerprint{}, ErrFingerprint
	}
	if k == nil {
		return Fingerprint{}, ErrKeyUnavailable
	}
	key, ok := k.idempotency[k.activeIdempotency]
	if !ok {
		return Fingerprint{}, ErrKeyUnavailable
	}
	return Fingerprint{1, "HMAC-SHA256", k.activeIdempotency, digest(key, scope, canonical)}, nil
}
func (k *Keyring) Match(scope RequestScope, canonical []byte, previous Fingerprint) (bool, error) {
	if !scope.valid() || len(canonical) < 1 || len(canonical) > 65536 || previous.FormatVersion != 1 ||
		previous.Algorithm != "HMAC-SHA256" || !macID.MatchString(previous.KeyID) || !hexDigest.MatchString(previous.Digest) {
		return false, ErrFingerprint
	}
	if k == nil {
		return false, ErrKeyUnavailable
	}
	key, ok := k.idempotency[previous.KeyID]
	if !ok {
		return false, ErrKeyUnavailable
	}
	expected, _ := hex.DecodeString(digest(key, scope, canonical))
	actual, _ := hex.DecodeString(previous.Digest)
	return hmac.Equal(expected, actual), nil
}
