package contracts

import (
	"encoding/base64"
	"encoding/json"
	"errors"
)

type sourceCursor struct {
	Scope    string `json:"scope"`
	After    string `json:"after"`
	DeviceID string `json:"device_id"`
}

func EncodeSourceCursor(after, deviceID string) string {
	b, _ := json.Marshal(sourceCursor{Scope: "camera.sources:v1", After: after, DeviceID: deviceID})
	return base64.RawURLEncoding.EncodeToString(b)
}

// Cursors are opaque pagination positions, not authentication credentials. Bind
// each cursor to the exact filter and reject noncanonical/foreign payloads.
func DecodeSourceCursor(cursor, deviceID string) (string, error) {
	bad := errors.New("invalid cursor")
	if deviceID != "" && !ValidDeviceID(deviceID) {
		return "", bad
	}
	if cursor == "" {
		return "", nil
	}
	if len(cursor) > 512 {
		return "", bad
	}
	b, err := base64.RawURLEncoding.Strict().DecodeString(cursor)
	var c sourceCursor
	if err != nil || json.Unmarshal(b, &c) != nil || c.Scope != "camera.sources:v1" ||
		!ValidDeviceID(c.After) || c.DeviceID != deviceID || EncodeSourceCursor(c.After, c.DeviceID) != cursor {
		return "", bad
	}
	return c.After, nil
}
