package app

import (
	"log/slog"

	"vms.local/platform/internal/httpapi"
	"vms.local/platform/model/api"
)

func New(token string, logger *slog.Logger) (*httpapi.API, error) {
	a, err := httpapi.New(httpapi.Manifest{Platform: "model", Capabilities: map[string]string{"model_registry": "planned", "deployment_runtime": "planned", "training": "planned"}}, token, api.OpenAPI, logger)
	if err != nil {
		return nil, err
	}

	return a, nil
}
