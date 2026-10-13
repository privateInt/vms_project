package app

import (
	"fmt"
	"net/http"
	"reflect"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
)

// Reuse the existing disposable DB and real API process fixture. The call
// closure follows the new endpoint and token after restart.
func verifyDeviceUpdateHTTP(t *testing.T, call func(string, string, string, string, int) (map[string]any, http.Header), sql func(string), restart func(), wasm bool, role string) {
	t.Helper()
	path := "/api/v1/devices/update-parent"
	create := strings.Replace(testDevice, `"d1"`, `"update-parent"`, 1)
	created, _ := call("POST", "/api/v1/devices", create, "update-create", 201)
	original := created["device"].(map[string]any)
	sourceBody := strings.NewReplacer(`"s1"`, `"update-child"`, `"d1"`, `"update-parent"`).Replace(testSource)
	source, _ := call("POST", "/api/v1/sources", sourceBody, "update-source", 201)
	body := func(version int, name string) string {
		return fmt.Sprintf(`{"schema_version":"v1","expected_version":%d,"display_name":%q}`, version, name)
	}
	checkError := func(value map[string]any, h http.Header, code string) {
		t.Helper()
		if value["error"].(map[string]any)["code"] != code || value["request_id"] != h.Get("X-Request-ID") || h.Get("Location") != "" || h.Get("Idempotency-Replayed") != "" {
			t.Fatal("wrong error envelope", value)
		}
	}
	patch := func(body, key string, status int) (map[string]any, http.Header) {
		return call("PATCH", path, body, key, status)
	}
	checkSuccess := func(value map[string]any, h http.Header, replay string) {
		t.Helper()
		if h.Get("Idempotency-Replayed") != replay || h.Get("Location") != "" || value["request_id"] != h.Get("X-Request-ID") || h.Get("Cache-Control") != "no-store" {
			t.Fatal("wrong PATCH response metadata")
		}
	}
	first, headers := patch(body(1, "  renamed  "), "update-create", 200)
	checkSuccess(first, headers, "false")
	firstDevice := first["device"].(map[string]any)
	if firstDevice["version"] != float64(2) || firstDevice["display_name"] != "  renamed  " || firstDevice["created_at"] != original["created_at"] || firstDevice["device_id"] != original["device_id"] || firstDevice["device_kind"] != original["device_kind"] {
		t.Fatal("unexpected rename fields", firstDevice)
	}
	before, _ := time.Parse(time.RFC3339Nano, original["updated_at"].(string))
	after, e := time.Parse(time.RFC3339Nano, firstDevice["updated_at"].(string))
	if e != nil || after.Before(before) || !strings.HasSuffix(firstDevice["updated_at"].(string), "Z") {
		t.Fatal("update timestamp")
	}
	canonical := `{"display_name":"  \u0072enamed  ","expected_version":1,"schema_version":"v1"}`
	replay, h := call("PATCH", "/api/v1/devices/update%2dparent", canonical, "update-create", 200)
	checkSuccess(replay, h, "true")
	if !reflect.DeepEqual(replay["device"], firstDevice) || replay["request_id"] == first["request_id"] {
		t.Fatal("canonical replay or fresh request ID")
	}
	for _, input := range []string{body(1, "different"), body(2, "  renamed  ")} {
		value, h := patch(input, "update-create", 409)
		checkError(value, h, "IDEMPOTENCY_CONFLICT")
	}
	value, h := patch(body(1, "stale"), "stale-key", 409)
	checkError(value, h, "DEVICE_VERSION_CONFLICT")
	value, h = call("PATCH", "/api/v1/devices/absent", body(1, "new"), "missing", 404)
	checkError(value, h, "DEVICE_NOT_FOUND")
	second, h := patch(body(2, "newest"), "second-update", 200)
	checkSuccess(second, h, "false")
	restart()
	manifest, _ := call("GET", "/api/v1/platform", "", "", 200)
	if manifest["version"] != "0.7.0-device-delete" || manifest["stage"] != "P1_DEVICE_DELETE" || manifest["capabilities"].(map[string]any)["device_update"] != "implemented" {
		t.Fatal("device update manifest")
	}
	replay, h = patch(canonical, "update-create", 200)
	checkSuccess(replay, h, "true")
	if !reflect.DeepEqual(replay["device"], firstDevice) || replay["request_id"] == first["request_id"] {
		t.Fatal("historical replay lost across restart/token rotation")
	}
	current, _ := call("GET", path, "", "", 200)
	if !reflect.DeepEqual(current["device"], second["device"]) {
		t.Fatal("replay reverted current device")
	}
	page, _ := call("GET", "/api/v1/devices?limit=200", "", "", 200)
	found := false
	for _, item := range page["items"].([]any) {
		if item.(map[string]any)["device_id"] == "update-parent" {
			found = true
			if !reflect.DeepEqual(item, second["device"]) {
				t.Fatal("device list did not reflect rename")
			}
		}
	}
	if !found {
		t.Fatal("renamed device missing in list")
	}
	postReplay, _ := call("POST", "/api/v1/devices", create, "update-create", 201)
	if !reflect.DeepEqual(postReplay["device"], original) {
		t.Fatal("PATCH changed POST snapshot")
	}
	child, _ := call("GET", "/api/v1/sources/update-child", "", "", 200)
	if !reflect.DeepEqual(child["source"], source["source"]) {
		t.Fatal("rename changed source/profile")
	}
	otherCreate := strings.Replace(create, "update-parent", "update-other", 1)
	call("POST", "/api/v1/devices", otherCreate, "other-create", 201)
	other, h := call("PATCH", "/api/v1/devices/update-other", body(1, "other"), "update-create", 200)
	checkSuccess(other, h, "false")
	if other["device"].(map[string]any)["device_id"] != "update-other" {
		t.Fatal("path scope collision")
	}
	same, h := patch(body(3, "newest"), "same-name", 200)
	checkSuccess(same, h, "false")
	if same["device"].(map[string]any)["version"] != float64(4) {
		t.Fatal("same-name command did not increment")
	}
	// Force a success-journal write failure after the device UPDATE in every
	// engine; verify the public 503 response and atomic same-key recovery.
	sql(`ALTER TABLE camera.device_update_requests ADD CONSTRAINT injected_http_failure CHECK(response_body->>'display_name' <> 'atomic-after')`)
	value, h = patch(body(4, "atomic-after"), "atomic-retry", 503)
	checkError(value, h, "DATABASE_UNAVAILABLE")
	current, _ = call("GET", path, "", "", 200)
	if !reflect.DeepEqual(current["device"], same["device"]) {
		t.Fatal("partial rename survived journal failure")
	}
	sql("ALTER TABLE camera.device_update_requests DROP CONSTRAINT injected_http_failure")
	latest, h := patch(body(4, "atomic-after"), "atomic-retry", 200)
	checkSuccess(latest, h, "false")
	if latest["device"].(map[string]any)["version"] != float64(5) {
		t.Fatal("retry version")
	}
	if !wasm {
		quoted := pgx.Identifier{role}.Sanitize()
		for _, privilege := range []string{"INSERT ON camera.device_update_requests", "UPDATE (display_name) ON camera.devices"} {
			sql("REVOKE " + privilege + " FROM " + quoted)
			call("GET", "/health/ready", "", "", 503)
			value, h = patch(body(5, "after-grants"), "permission-retry", 503)
			checkError(value, h, "DATABASE_UNAVAILABLE")
			current, _ = call("GET", path, "", "", 200)
			if !reflect.DeepEqual(current["device"], latest["device"]) {
				t.Fatal("partial rename after privilege loss")
			}
			sql("GRANT " + privilege + " TO " + quoted)
		}
		latest, h = patch(body(5, "after-grants"), "permission-retry", 200)
		checkSuccess(latest, h, "false")
		call("GET", "/health/ready", "", "", 200)
		t.Log("PATCH privilege loss returned 503, readiness failed, rename rolled back and same-key retry recovered")
	}
	sql("UPDATE camera.devices SET version=9223372036854775807 WHERE device_id='update-other'")
	value, h = call("PATCH", "/api/v1/devices/update-other", `{"schema_version":"v1","expected_version":9223372036854775807,"display_name":"full"}`, "exhausted", 409)
	checkError(value, h, "DEVICE_VERSION_EXHAUSTED")
	sql("UPDATE camera.devices SET deleted_at=clock_timestamp() WHERE device_id='update-parent'")
	value, h = patch(body(1, "deleted"), "deleted", 404)
	checkError(value, h, "DEVICE_NOT_FOUND")
	replay, h = patch(canonical, "update-create", 200)
	checkSuccess(replay, h, "true")
	if !reflect.DeepEqual(replay["device"], firstDevice) {
		t.Fatal("past success replay after tombstone")
	}
	t.Log("PATCH rename, canonical/path replay, conflicts, same-name version, GET/list, child and POST preservation, restart/token rotation, journal rollback, tombstone and version exhaustion passed")
}
