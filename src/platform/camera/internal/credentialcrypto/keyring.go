// Package credentialcrypto supplies private credential primitives. It does not
// authorize references, reserve database usage or connect devices.
package credentialcrypto

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"errors"
	"io"
	"regexp"
	"unicode/utf8"
)

var (
	ErrKeyBundle      = errors.New("CREDENTIAL_KEY_BUNDLE_INVALID")
	ErrContext        = errors.New("CREDENTIAL_CONTEXT_INVALID")
	ErrSecret         = errors.New("CREDENTIAL_SECRET_INVALID")
	ErrEnvelope       = errors.New("CREDENTIAL_ENVELOPE_INVALID")
	ErrAuthentication = errors.New("CREDENTIAL_AUTHENTICATION_FAILED")
	ErrKeyUnavailable = errors.New("CREDENTIAL_KEY_UNAVAILABLE")
	ErrReservation    = errors.New("CREDENTIAL_ENCRYPTION_RESERVATION_INVALID")
	ErrFingerprint    = errors.New("CREDENTIAL_FINGERPRINT_INVALID")
	ErrDisclosure     = errors.New("CREDENTIAL_PRIVATE_VALUE_NOT_SERIALIZABLE")
	identifier        = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`)
	encID             = regexp.MustCompile(`^enc-[0-9a-f]{16}$`)
	macID             = regexp.MustCompile(`^idem-[0-9a-f]{16}$`)
	hexDigest         = regexp.MustCompile(`^[0-9a-f]{64}$`)
)

const MaxBundleBytes = 32768

type keySet struct {
	Active string            `json:"active_key_id"`
	Keys   map[string]string `json:"keys"`
}

type keyBundle struct {
	Format      int    `json:"format_version"`
	Encryption  keySet `json:"encryption"`
	Idempotency keySet `json:"idempotency"`
}

// Keyring is immutable after parsing. It deliberately has no key export API.
type Keyring struct {
	activeEncryption, activeIdempotency string
	encryption, idempotency             map[string][32]byte
	bundleSHA256                        string
	readOnlyMount                       bool
}

func (k Keyring) String() string               { return "credentialcrypto.Keyring([redacted])" }
func (k Keyring) GoString() string             { return k.String() }
func (k Keyring) MarshalJSON() ([]byte, error) { return nil, ErrDisclosure }

func (k *Keyring) ActiveEncryptionID() string {
	if k == nil {
		return ""
	}
	return k.activeEncryption
}
func (k *Keyring) ActiveIdempotencyID() string {
	if k == nil {
		return ""
	}
	return k.activeIdempotency
}

// strictDecode rejects unknown/duplicate keys (including escaped aliases),
// trailing JSON and excessive nesting before decoding into the typed wire.
func strictDecode(data []byte, limit int, target any) error {
	if len(data) == 0 || len(data) > limit || !utf8.Valid(data) {
		return ErrKeyBundle
	}
	d := json.NewDecoder(bytes.NewReader(data))
	d.UseNumber()
	var walk func(int) error
	walk = func(depth int) error {
		if depth > 16 {
			return ErrKeyBundle
		}
		token, err := d.Token()
		if err != nil {
			return ErrKeyBundle
		}
		if delim, ok := token.(json.Delim); ok {
			switch delim {
			case '{':
				seen := map[string]bool{}
				for d.More() {
					name, err := d.Token()
					if err != nil {
						return ErrKeyBundle
					}
					key, ok := name.(string)
					if !ok || seen[key] {
						return ErrKeyBundle
					}
					seen[key] = true
					if err := walk(depth + 1); err != nil {
						return err
					}
				}
				end, err := d.Token()
				if err != nil || end != json.Delim('}') {
					return ErrKeyBundle
				}
			case '[':
				for d.More() {
					if err := walk(depth + 1); err != nil {
						return err
					}
				}
				end, err := d.Token()
				if err != nil || end != json.Delim(']') {
					return ErrKeyBundle
				}
			default:
				return ErrKeyBundle
			}
		}
		return nil
	}
	if err := walk(0); err != nil {
		return err
	}
	if _, err := d.Token(); err != io.EOF {
		return ErrKeyBundle
	}
	d = json.NewDecoder(bytes.NewReader(data))
	d.DisallowUnknownFields()
	if err := d.Decode(target); err != nil {
		return ErrKeyBundle
	}
	return nil
}

// ParseKeyBundle requires protected caller-supplied bytes. Filesystem ownership,
// permissions are checked by LoadKeyBundleFile. Read-only mounts and restore
// admission still require separate runtime verification.
func ParseKeyBundle(data []byte) (*Keyring, error) {
	var wire keyBundle
	if err := strictDecode(data, MaxBundleBytes, &wire); err != nil || wire.Format != 1 {
		return nil, ErrKeyBundle
	}
	fields, ok := exactFields(data, "format_version", "encryption", "idempotency")
	if !ok {
		return nil, ErrKeyBundle
	}
	for _, name := range []string{"encryption", "idempotency"} {
		if _, ok := exactFields(fields[name], "active_key_id", "keys"); !ok {
			return nil, ErrKeyBundle
		}
	}
	k := &Keyring{activeEncryption: wire.Encryption.Active, activeIdempotency: wire.Idempotency.Active,
		encryption: map[string][32]byte{}, idempotency: map[string][32]byte{}}
	seen := map[[32]byte]bool{}
	for _, part := range []struct {
		set     keySet
		pattern *regexp.Regexp
		out     map[string][32]byte
	}{
		{wire.Encryption, encID, k.encryption}, {wire.Idempotency, macID, k.idempotency},
	} {
		if len(part.set.Keys) < 1 || len(part.set.Keys) > 16 || !part.pattern.MatchString(part.set.Active) {
			return nil, ErrKeyBundle
		}
		for name, encoded := range part.set.Keys {
			if !part.pattern.MatchString(name) {
				return nil, ErrKeyBundle
			}
			decoded, err := base64.StdEncoding.Strict().DecodeString(encoded)
			if err != nil || len(decoded) != 32 || base64.StdEncoding.EncodeToString(decoded) != encoded {
				return nil, ErrKeyBundle
			}
			var value [32]byte
			copy(value[:], decoded)
			if seen[value] {
				return nil, ErrKeyBundle
			}
			seen[value] = true
			part.out[name] = value
		}
		if _, ok := part.out[part.set.Active]; !ok {
			return nil, ErrKeyBundle
		}
	}
	return k, nil
}

// encoding/json accepts case-insensitive struct field aliases. The private wire
// deliberately accepts only the exact field names shared with the key preparer.
func exactFields(data []byte, names ...string) (map[string]json.RawMessage, bool) {
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(data, &fields); err != nil || len(fields) != len(names) {
		return nil, false
	}
	for _, name := range names {
		if _, ok := fields[name]; !ok {
			return nil, false
		}
	}
	return fields, true
}
