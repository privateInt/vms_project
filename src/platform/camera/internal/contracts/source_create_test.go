package contracts

import (
	"encoding/json"
	"math"
	"strings"
	"testing"
)

const sourceJSON = `{"schema_version":"v1","source_id":"s1","device_id":"d1","channel_key":"ch1","display_name":"입구 영상","transport":"RTSP","input_mode":"PULL","motion_mode":"UNKNOWN","profiles":[{"profile_id":"main","codec":"H264","width":1920,"height":1080,"fps":30}]}`

func TestSourceCreateStrictJSON(t *testing.T) {
	var input SourceCreate
	if err := json.Unmarshal([]byte(sourceJSON), &input); err != nil || len(input.Validate()) != 0 {
		t.Fatal(input, err)
	}
	for _, body := range []string{
		`null`, `[]`, strings.Replace(sourceJSON, `"source_id":"s1"`, `"source_id":"s1","source_id":"s2"`, 1),
		strings.Replace(sourceJSON, `"source_id"`, `"Source_ID"`, 1), strings.Replace(sourceJSON, `"s1"`, `null`, 1),
		strings.Replace(sourceJSON, `"fps":30`, `"fps":30,"fps":24`, 1), strings.Replace(sourceJSON, `"width":1920`, `"width":1920.5`, 1),
		strings.Replace(sourceJSON, `"fps":30`, `"fps":"30"`, 1), strings.Replace(sourceJSON, `"fps":30`, `"fps":null`, 1),
		strings.Replace(sourceJSON, `"codec":"H264"`, `"codec":"H264","password":"secret"`, 1),
		strings.Replace(sourceJSON, `"profiles":[{`, `"profiles":[null,{`, 1),
		strings.Replace(sourceJSON, `"schema_version":"v1"`, `"schema_version":"v1","credential_ref":"secret"`, 1),
		strings.Replace(sourceJSON, `"schema_version":"v1"`, `"schema_version":"v1","device_kind":"CCTV"`, 1),
	} {
		if json.Unmarshal([]byte(body), &input) == nil {
			t.Fatalf("ambiguous input accepted: %s", body)
		}
	}
	if json.Unmarshal(append([]byte(sourceJSON[:len(sourceJSON)-1]), 0xff, '}'), &input) == nil {
		t.Fatal("invalid UTF-8 accepted")
	}
}

func TestSourceCreateSemanticsAndCanonicalRequest(t *testing.T) {
	var input SourceCreate
	_ = json.Unmarshal([]byte(sourceJSON), &input)
	canonical, _ := json.Marshal(input)
	var equivalent SourceCreate
	_ = json.Unmarshal([]byte(strings.Replace(sourceJSON, `"fps":30`, `"fps":3e1`, 1)), &equivalent)
	numeric, _ := json.Marshal(equivalent)
	if string(canonical) != string(numeric) {
		t.Fatal("numeric spelling changes canonical request")
	}
	cases := []func(*SourceCreate){
		func(s *SourceCreate) { s.SourceID = "validate" }, func(s *SourceCreate) { s.ChannelKey = "" }, func(s *SourceCreate) { s.DisplayName = "\x00" }, func(s *SourceCreate) { s.DisplayName = "   " },
		func(s *SourceCreate) { s.Profiles = nil }, func(s *SourceCreate) { s.Profiles = append(s.Profiles, s.Profiles[0]) },
		func(s *SourceCreate) { s.Profiles[0].FPS = math.NaN() }, func(s *SourceCreate) { s.Profiles[0].Width = 0 },
		func(s *SourceCreate) { s.InputMode = "PUSH" }, func(s *SourceCreate) { s.MotionMode = "bad" },
	}
	for i, change := range cases {
		_ = json.Unmarshal([]byte(sourceJSON), &input)
		change(&input)
		if len(input.Validate()) == 0 {
			t.Fatalf("invalid case %d accepted", i)
		}
	}
	_ = json.Unmarshal([]byte(sourceJSON), &input)
	input.Transport = "WEBRTC"
	input.InputMode = "PUSH"
	if len(input.Validate()) != 0 {
		t.Fatal("XR without ONVIF fields rejected")
	}
}
