package contracts

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"strings"
	"time"
	"unicode/utf8"

	"vms.local/platform/internal/httpapi"
)

type SourceCreate struct {
	SchemaVersion string    `json:"schema_version"`
	SourceID      string    `json:"source_id"`
	DeviceID      string    `json:"device_id"`
	ChannelKey    string    `json:"channel_key"`
	DisplayName   string    `json:"display_name"`
	Transport     string    `json:"transport"`
	InputMode     string    `json:"input_mode"`
	MotionMode    string    `json:"motion_mode"`
	Profiles      []Profile `json:"profiles"`
}

// Registration inputs require exact names and types, unique keys and non-null
// values, including profile objects. Missing required fields fail Validate.
func strictSourceObject(data []byte, fields map[string]any) error {
	bad := errors.New("invalid source JSON")
	if !utf8.Valid(data) {
		return bad
	}
	dec := json.NewDecoder(bytes.NewReader(data))
	token, err := dec.Token()
	if err != nil || token != json.Delim('{') {
		return bad
	}
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
		var raw json.RawMessage
		if dec.Decode(&raw) != nil || bytes.Equal(bytes.TrimSpace(raw), []byte("null")) || json.Unmarshal(raw, field) != nil {
			return bad
		}
	}
	_, err = dec.Token()
	return err
}

type sourceProfileInput Profile

func (p *sourceProfileInput) UnmarshalJSON(data []byte) error {
	*p = sourceProfileInput{}
	return strictSourceObject(data, map[string]any{"profile_id": &p.ProfileID, "codec": &p.Codec, "width": &p.Width, "height": &p.Height, "fps": &p.FPS})
}

func (s *SourceCreate) UnmarshalJSON(data []byte) error {
	*s = SourceCreate{}
	var profiles []sourceProfileInput
	err := strictSourceObject(data, map[string]any{
		"schema_version": &s.SchemaVersion, "source_id": &s.SourceID, "device_id": &s.DeviceID,
		"channel_key": &s.ChannelKey, "display_name": &s.DisplayName, "transport": &s.Transport,
		"input_mode": &s.InputMode, "motion_mode": &s.MotionMode, "profiles": &profiles,
	})
	if err != nil {
		return err
	}
	s.Profiles = make([]Profile, len(profiles))
	for i, p := range profiles {
		s.Profiles[i] = Profile(p)
	}
	return nil
}

func (s SourceCreate) Validate() []httpapi.Violation {
	var v []httpapi.Violation
	add := func(f, c, m string) { v = append(v, httpapi.Violation{Field: f, Code: c, Message: m}) }
	if s.SourceID == "validate" {
		add("source_id", "RESERVED", "This ID is reserved for the existing validation endpoint")
	}
	if s.SchemaVersion != "v1" {
		add("schema_version", "VERSION", "Must be v1")
	}
	for _, item := range []struct{ name, value string }{{"source_id", s.SourceID}, {"device_id", s.DeviceID}, {"channel_key", s.ChannelKey}} {
		if !identifier.MatchString(item.value) {
			add(item.name, "IDENTIFIER", "A stable ID of 1 to 64 ASCII characters is required")
		}
	}
	if !utf8.ValidString(s.DisplayName) || strings.TrimSpace(s.DisplayName) == "" || utf8.RuneCountInString(s.DisplayName) > 128 || strings.ContainsRune(s.DisplayName, 0) {
		add("display_name", "LENGTH", "Provide a nonblank name of at most 128 characters without NUL")
	}
	if !oneOf(s.Transport, "RTSP", "WEBRTC") {
		add("transport", "ENUM", "Must be RTSP or WEBRTC")
	}
	if (s.Transport == "RTSP" && s.InputMode != "PULL") || (s.Transport == "WEBRTC" && s.InputMode != "PUSH") {
		add("input_mode", "TRANSPORT_MODE", "Supports RTSP/PULL and WEBRTC/PUSH")
	}
	if !oneOf(s.MotionMode, "FIXED", "MOVING", "UNKNOWN") {
		add("motion_mode", "ENUM", "Unsupported motion mode")
	}
	if len(s.Profiles) < 1 || len(s.Profiles) > 8 {
		add("profiles", "LENGTH", "Provide 1 to 8 profiles")
	}
	seen := map[string]bool{}
	for i, p := range s.Profiles {
		f := fmt.Sprintf("profiles[%d]", i)
		if !identifier.MatchString(p.ProfileID) {
			add(f+".profile_id", "IDENTIFIER", "A profile ID is required")
		}
		if seen[p.ProfileID] {
			add(f+".profile_id", "DUPLICATE", "Profile IDs must be unique within a source")
		}
		seen[p.ProfileID] = true
		if !oneOf(p.Codec, "AUTO", "H264", "H265", "VP8", "VP9", "AV1") {
			add(f+".codec", "ENUM", "Unsupported declared codec")
		}
		if p.Width < 1 || p.Width > 16384 || p.Height < 1 || p.Height > 16384 {
			add(f, "DIMENSIONS", "Width and height must be between 1 and 16384")
		}
		if math.IsNaN(p.FPS) || math.IsInf(p.FPS, 0) || p.FPS <= 0 || p.FPS > 240 {
			add(f+".fps", "RANGE", "Declared FPS must be greater than 0 and at most 240")
		}
	}
	return v
}

type VideoSource struct {
	SchemaVersion string    `json:"schema_version"`
	SourceID      string    `json:"source_id"`
	DeviceID      string    `json:"device_id"`
	ChannelKey    string    `json:"channel_key"`
	DisplayName   string    `json:"display_name"`
	Transport     string    `json:"transport"`
	InputMode     string    `json:"input_mode"`
	MotionMode    string    `json:"motion_mode"`
	Profiles      []Profile `json:"profiles"`
	Version       int64     `json:"version"`
	CreatedAt     time.Time `json:"created_at"`
	UpdatedAt     time.Time `json:"updated_at"`
}
