package contracts

import (
	"bytes"
	"encoding/json"
	"errors"
	"time"
	"unicode/utf8"

	"vms.local/platform/internal/httpapi"
)

// SourceDelete is a version-conditioned registration deletion command.
type SourceDelete struct {
	SchemaVersion   string `json:"schema_version"`
	ExpectedVersion int64  `json:"expected_version"`
}

// Decode exact field names and unique keys without passing versions through
// floating point. Missing fields retain zero values for semantic validation.
func (d *SourceDelete) UnmarshalJSON(data []byte) error {
	bad := errors.New("invalid source delete JSON")
	if !utf8.Valid(data) {
		return bad
	}
	dec := json.NewDecoder(bytes.NewReader(data))
	dec.UseNumber()
	token, err := dec.Token()
	if err != nil || token != json.Delim('{') {
		return bad
	}
	var input SourceDelete
	seen := map[string]bool{}
	for dec.More() {
		token, err = dec.Token()
		if err != nil {
			return bad
		}
		key, ok := token.(string)
		if !ok || seen[key] {
			return bad
		}
		seen[key] = true
		var value any
		if err = dec.Decode(&value); err != nil {
			return bad
		}
		switch key {
		case "schema_version":
			text, ok := value.(string)
			if !ok {
				return bad
			}
			input.SchemaVersion = text
		case "expected_version":
			number, ok := value.(json.Number)
			if !ok {
				return bad
			}
			input.ExpectedVersion, err = number.Int64()
			if err != nil {
				return bad
			}
		default:
			return bad
		}
	}
	if token, err = dec.Token(); err != nil || token != json.Delim('}') {
		return bad
	}
	*d = input
	return nil
}

func (d SourceDelete) Validate() []httpapi.Violation {
	var result []httpapi.Violation
	if d.SchemaVersion != "v1" {
		result = append(result, httpapi.Violation{Field: "schema_version", Code: "VERSION", Message: "Must be v1"})
	}
	if d.ExpectedVersion < 1 {
		result = append(result, httpapi.Violation{Field: "expected_version", Code: "RANGE", Message: "A positive source version is required"})
	}
	return result
}

// SourceDeletion is the durable receipt, not an active VideoSource snapshot.
type SourceDeletion struct {
	SchemaVersion string    `json:"schema_version"`
	SourceID      string    `json:"source_id"`
	Version       int64     `json:"version"`
	DeletedAt     time.Time `json:"deleted_at"`
}
