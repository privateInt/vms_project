package contracts

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"errors"
	"strings"
	"time"
	"unicode/utf8"

	"vms.local/platform/internal/httpapi"
)

type DeviceCreate struct {
	SchemaVersion string `json:"schema_version"`
	DeviceID      string `json:"device_id"`
	DisplayName   string `json:"display_name"`
	DeviceKind    string `json:"device_kind"`
}

// Exact field names, types and unique keys avoid ambiguous idempotency inputs.
func (d *DeviceCreate) UnmarshalJSON(data []byte) error {
	bad := errors.New("invalid device JSON")
	if !utf8.Valid(data) {
		return bad
	}
	dec := json.NewDecoder(bytes.NewReader(data))
	token, err := dec.Token()
	if err != nil || token != json.Delim('{') {
		return bad
	}
	*d = DeviceCreate{}
	fields := map[string]*string{"schema_version": &d.SchemaVersion, "device_id": &d.DeviceID, "display_name": &d.DisplayName, "device_kind": &d.DeviceKind}
	seen := map[string]bool{}
	for dec.More() {
		token, err = dec.Token()
		if err != nil {
			return bad
		}
		key, ok := token.(string)
		field, known := fields[key]
		if !ok || !known || seen[key] {
			return bad
		}
		seen[key] = true
		var value any
		if err = dec.Decode(&value); err != nil {
			return bad
		}
		text, ok := value.(string)
		if !ok {
			return bad
		}
		*field = text
	}
	_, err = dec.Token()
	return err
}

func (d DeviceCreate) Validate() []httpapi.Violation {
	var v []httpapi.Violation
	add := func(field, code, message string) {
		v = append(v, httpapi.Violation{Field: field, Code: code, Message: message})
	}
	if d.SchemaVersion != "v1" {
		add("schema_version", "VERSION", "Must be v1")
	}
	if !ValidDeviceID(d.DeviceID) {
		add("device_id", "IDENTIFIER", "A stable device ID of 1 to 64 ASCII characters is required")
	}
	if strings.TrimSpace(d.DisplayName) == "" || utf8.RuneCountInString(d.DisplayName) > 128 || strings.ContainsRune(d.DisplayName, 0) {
		add("display_name", "LENGTH", "Provide a nonblank name of at most 128 characters without NUL")
	}
	if !oneOf(d.DeviceKind, "CCTV", "SMART_GLASSES", "TEST") {
		add("device_kind", "ENUM", "Unsupported device kind")
	}
	return v
}

func ValidDeviceID(value string) bool { return identifier.MatchString(value) }
func ValidIdempotencyKey(key string) bool {
	if len(key) < 1 || len(key) > 128 {
		return false
	}
	for _, b := range []byte(key) {
		if b < 33 || b > 126 {
			return false
		}
	}
	return true
}

type Device struct {
	SchemaVersion string    `json:"schema_version"`
	DeviceID      string    `json:"device_id"`
	DisplayName   string    `json:"display_name"`
	DeviceKind    string    `json:"device_kind"`
	Version       int64     `json:"version"`
	CreatedAt     time.Time `json:"created_at"`
	UpdatedAt     time.Time `json:"updated_at"`
}

type deviceCursor struct {
	Scope string `json:"scope"`
	After string `json:"after"`
}

func EncodeDeviceCursor(after string) string {
	b, _ := json.Marshal(deviceCursor{Scope: "camera.devices:v1", After: after})
	return base64.RawURLEncoding.EncodeToString(b)
}
func DecodeDeviceCursor(cursor string) (string, error) {
	if cursor == "" {
		return "", nil
	}
	if len(cursor) > 512 {
		return "", errors.New("invalid cursor")
	}
	b, err := base64.RawURLEncoding.Strict().DecodeString(cursor)
	var c deviceCursor
	if err != nil || json.Unmarshal(b, &c) != nil || c.Scope != "camera.devices:v1" || !ValidDeviceID(c.After) || EncodeDeviceCursor(c.After) != cursor {
		return "", errors.New("invalid cursor")
	}
	return c.After, nil
}
