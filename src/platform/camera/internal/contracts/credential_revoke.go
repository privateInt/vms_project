package contracts

import (
	"strconv"

	"vms.local/platform/internal/httpapi"
)

// The immutable version is an exact decoded path segment, never a float or latest.
func ParseCredentialVersion(value string) (int64, bool) {
	if len(value) < 1 || len(value) > 19 || value[0] < '1' || value[0] > '9' {
		return 0, false
	}
	for _, b := range []byte(value) {
		if b < '0' || b > '9' {
			return 0, false
		}
	}
	n, err := strconv.ParseInt(value, 10, 64)
	return n, err == nil && n > 0
}

// CredentialRevoke carries only the parent identity; version comes from the path.
// It neither accepts a force option nor lets the caller assert an unused state.
type CredentialRevoke struct{ SchemaVersion, DeviceID string }

func (d *CredentialRevoke) UnmarshalJSON(data []byte) error {
	*d = CredentialRevoke{}
	if len(data) > int(httpapi.MaxBodyBytes) || !credentialUnicode(data) {
		return invalidCredentialJSON
	}
	fields, err := credentialObject(data, "schema_version", "device_id")
	if err != nil {
		return invalidCredentialJSON
	}
	var input CredentialRevoke
	for key, value := range fields {
		if key == "schema_version" {
			err = credentialString(value, &input.SchemaVersion)
		} else {
			err = credentialString(value, &input.DeviceID)
		}
		if err != nil {
			return invalidCredentialJSON
		}
	}
	*d = input
	return nil
}

func (d CredentialRevoke) Validate() []httpapi.Violation {
	var result []httpapi.Violation
	if d.SchemaVersion != "v1" {
		result = append(result, httpapi.Violation{Field: "schema_version", Code: "VERSION", Message: "Must be v1"})
	}
	if !ValidDeviceID(d.DeviceID) {
		result = append(result, httpapi.Violation{Field: "device_id", Code: "IDENTIFIER", Message: "A valid device ID is required"})
	}
	return result
}
