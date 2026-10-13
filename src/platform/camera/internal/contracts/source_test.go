package contracts

import "testing"

func validXR() SourceSpec {
	return SourceSpec{SchemaVersion: "v1", SourceID: "glass-01.video", DeviceID: "glass-01", DisplayName: "스마트글래스", DeviceKind: "SMART_GLASSES", Transport: "WEBRTC", InputMode: "PUSH", MotionMode: "MOVING", Profiles: []Profile{{ProfileID: "main", Codec: "H264", Width: 1280, Height: 720, FPS: 30}}, Capabilities: &Capabilities{}}
}

func TestXRDoesNotRequireONVIFOrPTZ(t *testing.T) {
	s := validXR()
	if v := s.Validate(); len(v) != 0 {
		t.Fatal(v)
	}
}
func TestTransportModeAndProfileIdentity(t *testing.T) {
	s := validXR()
	s.InputMode = "PULL"
	if len(s.Validate()) == 0 {
		t.Fatal("invalid transport/mode accepted")
	}
	s = validXR()
	s.Profiles = append(s.Profiles, s.Profiles[0])
	if len(s.Validate()) == 0 {
		t.Fatal("duplicate profile accepted")
	}
}
func TestCapabilitiesAreExplicitAndNamesAllowKorean(t *testing.T) {
	s := validXR()
	s.Capabilities = nil
	if len(s.Validate()) == 0 {
		t.Fatal("missing capabilities accepted")
	}
	s = validXR()
	s.DisplayName = "   "
	if len(s.Validate()) == 0 {
		t.Fatal("blank display name accepted")
	}
}
