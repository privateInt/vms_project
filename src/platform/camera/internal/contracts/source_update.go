package contracts

import (
	"bytes"
	"encoding/json"
	"errors"
	"strings"
	"unicode/utf8"

	"vms.local/platform/internal/httpapi"
)

// SourceUpdate is a version-checked display-name replacement command.
type SourceUpdate struct {
	SchemaVersion   string `json:"schema_version"`
	ExpectedVersion int64  `json:"expected_version"`
	DisplayName     string `json:"display_name"`
}

// Decode exact field names and unique keys without passing versions through
// floating point. Missing fields retain zero values for semantic validation.
func (d *SourceUpdate) UnmarshalJSON(data []byte) error {
	bad := errors.New("invalid source update JSON")
	if !utf8.Valid(data) {
		return bad
	}
	dec := json.NewDecoder(bytes.NewReader(data))
	dec.UseNumber()
	token, err := dec.Token()
	if err != nil || token != json.Delim('{') {
		return bad
	}
	var input SourceUpdate
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
		case "schema_version", "display_name":
			text, ok := value.(string)
			if !ok {
				return bad
			}
			if key == "schema_version" {
				input.SchemaVersion = text
			} else {
				input.DisplayName = text
			}
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

func (d SourceUpdate) Validate() []httpapi.Violation {
	var result []httpapi.Violation
	add := func(field, code, message string) {
		result = append(result, httpapi.Violation{Field: field, Code: code, Message: message})
	}
	if d.SchemaVersion != "v1" {
		add("schema_version", "VERSION", "Must be v1")
	}
	if d.ExpectedVersion < 1 {
		add("expected_version", "RANGE", "A positive source version is required")
	}
	if strings.TrimSpace(d.DisplayName) == "" || utf8.RuneCountInString(d.DisplayName) > 128 || strings.ContainsRune(d.DisplayName, 0) || !utf8.ValidString(d.DisplayName) {
		add("display_name", "LENGTH", "Provide a nonblank UTF-8 name of at most 128 characters without NUL")
	}
	return result
}
