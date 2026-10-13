package contracts

import (
	"fmt"
	"regexp"
	"strings"
	"unicode/utf8"
	"vms.local/platform/internal/httpapi"
)

var identifier = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`)

type Profile struct {
	ProfileID string  `json:"profile_id"`
	Codec     string  `json:"codec"`
	Width     int     `json:"width"`
	Height    int     `json:"height"`
	FPS       float64 `json:"fps"`
}
type Capabilities struct {
	SupportsONVIF bool `json:"supports_onvif"`
	SupportsPTZ   bool `json:"supports_ptz"`
}
type SourceSpec struct {
	SchemaVersion string        `json:"schema_version"`
	SourceID      string        `json:"source_id"`
	DeviceID      string        `json:"device_id"`
	DisplayName   string        `json:"display_name"`
	DeviceKind    string        `json:"device_kind"`
	Transport     string        `json:"transport"`
	InputMode     string        `json:"input_mode"`
	MotionMode    string        `json:"motion_mode"`
	Profiles      []Profile     `json:"profiles"`
	Capabilities  *Capabilities `json:"capabilities"`
}

func (s SourceSpec) Validate() []httpapi.Violation {
	var v []httpapi.Violation
	add := func(f, c, m string) { v = append(v, httpapi.Violation{Field: f, Code: c, Message: m}) }
	if s.SchemaVersion != "v1" {
		add("schema_version", "VERSION", "Must be v1")
	}
	if !identifier.MatchString(s.SourceID) {
		add("source_id", "IDENTIFIER", "Use 1 to 64 ASCII letters, digits, dots, underscores or hyphens, starting with a letter or digit")
	}
	if !identifier.MatchString(s.DeviceID) {
		add("device_id", "IDENTIFIER", "A stable device ID is required")
	}
	if strings.TrimSpace(s.DisplayName) == "" || utf8.RuneCountInString(s.DisplayName) > 128 {
		add("display_name", "LENGTH", "Provide a nonblank name of at most 128 characters")
	}
	if !oneOf(s.DeviceKind, "CCTV", "SMART_GLASSES", "TEST") {
		add("device_kind", "ENUM", "Unsupported device kind")
	}
	if !oneOf(s.Transport, "RTSP", "WEBRTC") {
		add("transport", "ENUM", "Must be RTSP or WEBRTC")
	}
	if (s.Transport == "RTSP" && s.InputMode != "PULL") || (s.Transport == "WEBRTC" && s.InputMode != "PUSH") {
		add("input_mode", "TRANSPORT_MODE", "This v1 contract supports RTSP/PULL and WEBRTC/PUSH")
	}
	if !oneOf(s.MotionMode, "FIXED", "MOVING", "UNKNOWN") {
		add("motion_mode", "ENUM", "Unsupported motion mode")
	}
	if s.Capabilities == nil {
		add("capabilities", "REQUIRED", "Explicit declared capabilities are required")
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
		if p.FPS <= 0 || p.FPS > 240 {
			add(f+".fps", "RANGE", "Declared FPS must be greater than 0 and at most 240")
		}
	}
	return v
}
func oneOf(value string, values ...string) bool {
	for _, v := range values {
		if value == v {
			return true
		}
	}
	return false
}
