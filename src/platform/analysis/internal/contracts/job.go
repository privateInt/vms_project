package contracts

import (
	"fmt"
	"regexp"
	"vms.local/platform/internal/httpapi"
)

var identifier = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`)

type DeploymentRef struct {
	Role           string `json:"role"`
	DeploymentID   string `json:"deployment_id"`
	ModelVersionID string `json:"model_version_id"`
}
type JobSpec struct {
	SchemaVersion     string          `json:"schema_version"`
	JobID             string          `json:"analysis_job_id"`
	SourceID          string          `json:"source_id"`
	ProfileID         string          `json:"stream_profile_id"`
	TemplateVersionID string          `json:"template_version_id"`
	DeploymentRefs    []DeploymentRef `json:"deployment_refs"`
	TargetFPS         float64         `json:"target_fps"`
	DesiredState      string          `json:"desired_state"`
	Generation        uint64          `json:"generation"`
}

func (s JobSpec) Validate() []httpapi.Violation {
	var v []httpapi.Violation
	add := func(f, c, m string) { v = append(v, httpapi.Violation{Field: f, Code: c, Message: m}) }
	if s.SchemaVersion != "v1" {
		add("schema_version", "VERSION", "Must be v1")
	}
	for _, f := range []struct{ name, value string }{{"analysis_job_id", s.JobID}, {"source_id", s.SourceID}, {"stream_profile_id", s.ProfileID}, {"template_version_id", s.TemplateVersionID}} {
		if !identifier.MatchString(f.value) {
			add(f.name, "IDENTIFIER", "A valid stable ID is required")
		}
	}
	if s.DesiredState != "RUNNING" && s.DesiredState != "STOPPED" {
		add("desired_state", "ENUM", "Must be RUNNING or STOPPED")
	}
	if s.Generation == 0 {
		add("generation", "RANGE", "Generation starts at 1")
	}
	if s.TargetFPS <= 0 || s.TargetFPS > 240 {
		add("target_fps", "RANGE", "Target FPS must be greater than 0 and at most 240")
	}
	if len(s.DeploymentRefs) < 1 || len(s.DeploymentRefs) > 8 {
		add("deployment_refs", "LENGTH", "Provide 1 to 8 deployment references")
	}
	seen := map[string]bool{}
	for i, d := range s.DeploymentRefs {
		f := fmt.Sprintf("deployment_refs[%d]", i)
		if !identifier.MatchString(d.Role) || !identifier.MatchString(d.DeploymentID) || !identifier.MatchString(d.ModelVersionID) {
			add(f, "IDENTIFIER", "Role, deployment ID and pinned model version ID are required")
		}
		if seen[d.Role] {
			add(f+".role", "DUPLICATE", "Each inference role must have exactly one reference")
		}
		seen[d.Role] = true
	}
	return v
}
