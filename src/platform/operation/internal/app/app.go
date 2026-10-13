package app

import (
	"log/slog"

	"vms.local/platform/internal/httpapi"
	"vms.local/platform/operation/api"
)

func New(token string, logger *slog.Logger) (*httpapi.API, error) {
	a, err := httpapi.New(httpapi.Manifest{Platform: "operation", Capabilities: map[string]string{"platform_orchestration": "planned", "operator_ui": "planned", "notifications": "planned"}}, token, api.OpenAPI, logger)
	if err != nil {
		return nil, err
	}

	return a, nil
}
