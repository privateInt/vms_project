package contracts

import "testing"

func validJob() JobSpec {
	return JobSpec{SchemaVersion: "v1", JobID: "job-01", SourceID: "glass-01.video", ProfileID: "main", TemplateVersionID: "object-detection-v1", DeploymentRefs: []DeploymentRef{{Role: "detector", DeploymentID: "deployment-01", ModelVersionID: "model-version-01"}}, TargetFPS: 5, DesiredState: "RUNNING", Generation: 1}
}
func TestJobRequiresPinnedModelVersion(t *testing.T) {
	s := validJob()
	if v := s.Validate(); len(v) != 0 {
		t.Fatal(v)
	}
	s.DeploymentRefs[0].ModelVersionID = ""
	if len(s.Validate()) == 0 {
		t.Fatal("unpinned reference accepted")
	}
}
func TestDuplicateInferenceRoleRejected(t *testing.T) {
	s := validJob()
	s.DeploymentRefs = append(s.DeploymentRefs, s.DeploymentRefs[0])
	if len(s.Validate()) == 0 {
		t.Fatal("duplicate role accepted")
	}
}
func TestInvalidGenerationAndDesiredState(t *testing.T) {
	s := validJob()
	s.Generation = 0
	s.DesiredState = "RETRY_WAIT"
	if len(s.Validate()) < 2 {
		t.Fatal("execution state confused with desired state")
	}
}
