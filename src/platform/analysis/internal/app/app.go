package app

import (
	"log/slog"
	"net/http"
	"vms.local/platform/analysis/api"
	"vms.local/platform/analysis/internal/contracts"
	"vms.local/platform/internal/httpapi"
)

func New(token string, logger *slog.Logger) (*httpapi.API, error) {
	a, err := httpapi.New(httpapi.Manifest{Platform: "analysis", Capabilities: map[string]string{"job_contract_validation": "implemented", "job_reconciliation": "planned", "worker_leases": "planned", "inference": "planned", "events": "planned"}}, token, api.OpenAPI, logger)
	if err != nil {
		return nil, err
	}

	a.Handle("/api/v1/analysis-jobs/validate", func(w http.ResponseWriter, r *http.Request) {
		if !httpapi.RequireMethod(w, r, http.MethodPost) {
			return
		}
		var input contracts.JobSpec
		if !httpapi.DecodeJSON(w, r, &input) {
			return
		}
		if violations := input.Validate(); len(violations) > 0 {
			httpapi.Fail(w, r, http.StatusUnprocessableEntity, "CONTRACT_INVALID", "Contract validation failed", violations)
			return
		}
		httpapi.WriteJSON(w, http.StatusOK, map[string]any{"valid": true, "validation_scope": "contract_only", "resource_created": false, "references_verified": false, "runtime_verified": false})
	})

	return a, nil
}
