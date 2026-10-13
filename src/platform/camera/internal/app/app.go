package app

import (
	"log/slog"
	"net/http"
	"vms.local/platform/camera/api"
	"vms.local/platform/camera/internal/contracts"
	"vms.local/platform/camera/internal/storage"
	"vms.local/platform/internal/httpapi"
)

func New(token string, logger *slog.Logger) (*httpapi.API, error) {
	return NewWithStore(token, logger, nil)
}

func NewWithStore(token string, logger *slog.Logger, store *storage.Store) (*httpapi.API, error) {
	registry := "disabled"
	if store != nil {
		registry = "implemented"
	}
	capabilities := cameraCapabilities(registry)
	// This release installs metadata routes only. There is no session, consumer
	// or media adapter creator. Introducing one requires atomic usage admission.
	sourceGuard := registryOnlySourceDeleteGuard("registry-only-v1", capabilities)
	deviceGuard := registryOnlyDeviceDeleteGuard("registry-only-v1", capabilities)
	a, err := httpapi.New(httpapi.Manifest{Platform: "camera", Version: "0.7.0-device-delete", Stage: "P1_DEVICE_DELETE", Capabilities: capabilities}, token, api.OpenAPI, logger)
	if err != nil {
		return nil, err
	}

	a.Handle("/api/v1/sources/validate", func(w http.ResponseWriter, r *http.Request) {
		if !httpapi.RequireMethod(w, r, http.MethodPost) {
			return
		}
		var input contracts.SourceSpec
		if !httpapi.DecodeJSON(w, r, &input) {
			return
		}
		if violations := input.Validate(); len(violations) > 0 {
			httpapi.Fail(w, r, http.StatusUnprocessableEntity, "CONTRACT_INVALID", "Contract validation failed", violations)
			return
		}
		httpapi.WriteJSON(w, http.StatusOK, map[string]any{"valid": true, "validation_scope": "contract_only", "resource_created": false, "references_verified": false, "runtime_verified": false})
	})

	registerDevices(a, store, deviceGuard)
	registerSources(a, store, sourceGuard)
	if store != nil {
		a.SetReadiness("camera_registry", store.CheckReady)
	}
	return a, nil
}
