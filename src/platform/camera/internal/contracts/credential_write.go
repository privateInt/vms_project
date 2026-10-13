package contracts

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"net/netip"
	"regexp"
	"strconv"
	"strings"
	"unicode/utf8"

	"vms.local/platform/camera/internal/credentialcrypto"
	"vms.local/platform/internal/httpapi"
)

var invalidCredentialJSON = errors.New("invalid credential JSON")
var credentialDNSLabel = regexp.MustCompile(`^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$`)

// CredentialVersionWrite is transient, write-only input. Formatting and JSON
// serialization must never disclose its secret or private target.
type CredentialVersionWrite struct {
	SchemaVersion      string
	DeviceID           string
	ExpectedVersion    int64
	Protocol, Host     string
	Port               int64
	username, password string
	hasExpectedVersion bool
}

func (d CredentialVersionWrite) String() string {
	return "contracts.CredentialVersionWrite([redacted])"
}
func (d CredentialVersionWrite) GoString() string { return d.String() }
func (d CredentialVersionWrite) MarshalJSON() ([]byte, error) {
	return nil, credentialcrypto.ErrDisclosure
}
func (d *CredentialVersionWrite) Clear() { *d = CredentialVersionWrite{} }
func (d CredentialVersionWrite) Secret() (credentialcrypto.Secret, error) {
	return credentialcrypto.NewSecret(d.username, d.password)
}

// Preserve exact strings and signed integer tokens. Go's JSON decoder otherwise
// replaces unpaired UTF-16 surrogates, which would silently change a password.
func credentialUnicode(data []byte) bool {
	if !utf8.Valid(data) {
		return false
	}
	for i := 0; i < len(data); i++ {
		if data[i] != '\\' {
			continue
		}
		i++
		if i >= len(data) {
			return false
		}
		if data[i] != 'u' {
			continue
		}
		if i+4 >= len(data) {
			return false
		}
		n, err := strconv.ParseUint(string(data[i+1:i+5]), 16, 16)
		if err != nil {
			return false
		}
		i += 4
		if n >= 0xdc00 && n <= 0xdfff {
			return false
		}
		if n < 0xd800 || n > 0xdbff {
			continue
		}
		if i+6 >= len(data) || data[i+1] != '\\' || data[i+2] != 'u' {
			return false
		}
		low, err := strconv.ParseUint(string(data[i+3:i+7]), 16, 16)
		if err != nil || low < 0xdc00 || low > 0xdfff {
			return false
		}
		i += 6
	}
	return true
}

func credentialObject(data []byte, allowed ...string) (map[string]json.RawMessage, error) {
	dec := json.NewDecoder(bytes.NewReader(data))
	token, err := dec.Token()
	if err != nil || token != json.Delim('{') {
		return nil, invalidCredentialJSON
	}
	fields := map[string]bool{}
	for _, key := range allowed {
		fields[key] = true
	}
	result := map[string]json.RawMessage{}
	for dec.More() {
		token, err = dec.Token()
		key, ok := token.(string)
		if err != nil || !ok || !fields[key] || result[key] != nil {
			return nil, invalidCredentialJSON
		}
		var raw json.RawMessage
		if dec.Decode(&raw) != nil {
			return nil, invalidCredentialJSON
		}
		result[key] = raw
	}
	if token, err = dec.Token(); err != nil || token != json.Delim('}') {
		return nil, invalidCredentialJSON
	}
	var extra any
	if dec.Decode(&extra) != io.EOF {
		return nil, invalidCredentialJSON
	}
	return result, nil
}

func credentialString(raw []byte, value *string) error {
	var parsed any
	if json.Unmarshal(raw, &parsed) != nil {
		return invalidCredentialJSON
	}
	text, ok := parsed.(string)
	if !ok {
		return invalidCredentialJSON
	}
	*value = text
	return nil
}
func credentialInteger(raw []byte, value *int64) error {
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.UseNumber()
	var parsed any
	if dec.Decode(&parsed) != nil {
		return invalidCredentialJSON
	}
	number, ok := parsed.(json.Number)
	if !ok {
		return invalidCredentialJSON
	}
	n, err := number.Int64()
	if err != nil {
		return invalidCredentialJSON
	}
	*value = n
	return nil
}

func (d *CredentialVersionWrite) UnmarshalJSON(data []byte) error {
	d.Clear()
	if len(data) > int(httpapi.MaxBodyBytes) || !credentialUnicode(data) {
		return invalidCredentialJSON
	}
	fields, err := credentialObject(data, "schema_version", "device_id", "expected_version", "target", "secret")
	if err != nil {
		return err
	}
	var input CredentialVersionWrite
	for key, value := range fields {
		switch key {
		case "schema_version":
			err = credentialString(value, &input.SchemaVersion)
		case "device_id":
			err = credentialString(value, &input.DeviceID)
		case "expected_version":
			err = credentialInteger(value, &input.ExpectedVersion)
			input.hasExpectedVersion = true
		case "target":
			var object map[string]json.RawMessage
			object, err = credentialObject(value, "protocol", "host", "port")
			if err == nil {
				for key, raw := range object {
					switch key {
					case "protocol":
						err = credentialString(raw, &input.Protocol)
					case "host":
						err = credentialString(raw, &input.Host)
					case "port":
						err = credentialInteger(raw, &input.Port)
					}
					if err != nil {
						break
					}
				}
			}
		case "secret":
			var object map[string]json.RawMessage
			object, err = credentialObject(value, "username", "password")
			if err == nil {
				for key, raw := range object {
					if key == "username" {
						err = credentialString(raw, &input.username)
					} else {
						err = credentialString(raw, &input.password)
					}
					if err != nil {
						break
					}
				}
			}
		}
		if err != nil {
			return invalidCredentialJSON
		}
	}
	*d = input
	return nil
}

// This is private target policy syntax, not permission to resolve or dial.
// Storage and HTTP use the same predicate without normalizing host spelling.
func ValidCredentialTarget(protocol, host string, port int64) bool {
	if protocol != "RTSP" || port < 1 || port > 65535 || len(host) < 1 || len(host) > 253 {
		return false
	}
	if address, err := netip.ParseAddr(host); err == nil {
		return address.Zone() == "" && address.String() == host
	}
	if strings.ContainsAny(host, ":/%@?#\\") {
		return false
	}
	labels := strings.Split(host, ".")
	if len(labels) < 2 {
		return false
	}
	allNumeric := true
	for _, label := range labels {
		if !credentialDNSLabel.MatchString(label) {
			return false
		}
		for _, r := range label {
			if r < '0' || r > '9' {
				allNumeric = false
			}
		}
	}
	last := labels[len(labels)-1]
	return !allNumeric && ((last[0] >= 'A' && last[0] <= 'Z') || (last[0] >= 'a' && last[0] <= 'z'))
}

func (d CredentialVersionWrite) Validate() []httpapi.Violation {
	var result []httpapi.Violation
	add := func(field, code, message string) {
		result = append(result, httpapi.Violation{Field: field, Code: code, Message: message})
	}
	if d.SchemaVersion != "v1" {
		add("schema_version", "VERSION", "Must be v1")
	}
	if !ValidDeviceID(d.DeviceID) {
		add("device_id", "IDENTIFIER", "A valid device ID is required")
	}
	if !d.hasExpectedVersion || d.ExpectedVersion < 0 {
		add("expected_version", "RANGE", "An explicit nonnegative credential head version is required")
	}
	if !ValidCredentialTarget(d.Protocol, d.Host, d.Port) {
		add("target", "TARGET", "Provide an exact RTSP host and port")
	}
	if _, err := d.Secret(); err != nil {
		add("secret", "SECRET", "Provide valid username and password strings")
	}
	return result
}
