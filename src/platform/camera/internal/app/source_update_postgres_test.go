package app

import (
	"fmt"
	"net/http"
	"net/url"
	"reflect"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
)

// Reuse the isolated database and real API process; restart rotates the token.
func verifySourceUpdateHTTP(t *testing.T, call func(string, string, string, string, int) (map[string]any, http.Header), sql func(string), restart func(), wasm bool, role string) {
	t.Helper()
	parentPath := "/api/v1/devices/source-update-parent"
	path := "/api/v1/sources/source-update-a"
	parentBody := strings.Replace(testDevice, `"d1"`, `"source-update-parent"`, 1)
	call("POST", "/api/v1/devices", parentBody, "source-update-parent", 201)
	create := strings.NewReplacer(`"s1"`, `"source-update-a"`, `"d1"`, `"source-update-parent"`).Replace(testSource)
	created, _ := call("POST", "/api/v1/sources", create, "source-update-shared", 201)
	original := created["source"].(map[string]any)
	siblingBody := strings.NewReplacer(`"source-update-a"`, `"source-update-b"`, `"ch1"`, `"ch2"`).Replace(create)
	sibling, _ := call("POST", "/api/v1/sources", siblingBody, "source-update-sibling", 201)
	body := func(version int, name string) string {
		return fmt.Sprintf(`{"schema_version":"v1","expected_version":%d,"display_name":%q}`, version, name)
	}
	// The parent's version and each request scope are independent of the source.
	parent, _ := call("PATCH", parentPath, body(1, "parent renamed"), "source-update-shared", 200)
	page, _ := call("GET", "/api/v1/sources?device_id=source-update-parent&limit=1", "", "", 200)
	cursor := url.QueryEscape(page["next_cursor"].(string))
	if page["items"].([]any)[0].(map[string]any)["source_id"] != "source-update-a" {
		t.Fatal("fixture ID order")
	}
	checkError := func(value map[string]any, h http.Header, code string) {
		t.Helper()
		if value["error"].(map[string]any)["code"] != code || value["request_id"] != h.Get("X-Request-ID") || h.Get("Location") != "" || h.Get("Idempotency-Replayed") != "" {
			t.Fatal("wrong source error envelope", value)
		}
	}
	checkSuccess := func(value map[string]any, h http.Header, replay string) {
		t.Helper()
		if h.Get("Idempotency-Replayed") != replay || h.Get("Location") != "" || value["request_id"] != h.Get("X-Request-ID") || h.Get("Cache-Control") != "no-store" || value["registration_state"] != "REGISTERED" || value["runtime_verified"] != false {
			t.Fatal("wrong source PATCH metadata", value)
		}
	}
	patch := func(input, key string, status int) (map[string]any, http.Header) {
		return call("PATCH", path, input, key, status)
	}
	first, h := patch(body(1, "  renamed  "), "source-update-shared", 200)
	checkSuccess(first, h, "false")
	firstSource := first["source"].(map[string]any)
	if firstSource["version"] != float64(2) || firstSource["display_name"] != "  renamed  " {
		t.Fatal("rename fields", firstSource)
	}
	for field, value := range original {
		if field != "display_name" && field != "version" && field != "updated_at" && !reflect.DeepEqual(firstSource[field], value) {
			t.Fatal("immutable source/profile changed", field)
		}
	}
	before, _ := time.Parse(time.RFC3339Nano, original["updated_at"].(string))
	after, e := time.Parse(time.RFC3339Nano, firstSource["updated_at"].(string))
	if e != nil || after.Before(before) || !strings.HasSuffix(firstSource["updated_at"].(string), "Z") {
		t.Fatal("update timestamp")
	}
	canonical := `{"display_name":"  \u0072enamed  ","expected_version":1,"schema_version":"v1"}`
	replay, h := call("PATCH", "/api/v1/sources/source%2dupdate-a", canonical, "source-update-shared", 200)
	checkSuccess(replay, h, "true")
	if !reflect.DeepEqual(replay["source"], firstSource) || replay["request_id"] == first["request_id"] {
		t.Fatal("canonical/path replay")
	}
	for _, input := range []string{body(1, "different"), body(2, "  renamed  ")} {
		value, h := patch(input, "source-update-shared", 409)
		checkError(value, h, "IDEMPOTENCY_CONFLICT")
	}
	value, h := patch(body(1, "stale"), "source-stale", 409)
	checkError(value, h, "SOURCE_VERSION_CONFLICT")
	value, h = call("PATCH", "/api/v1/sources/absent", body(1, "missing"), "source-missing", 404)
	checkError(value, h, "SOURCE_NOT_FOUND")
	second, h := patch(body(2, "newest"), "source-second", 200)
	checkSuccess(second, h, "false")
	restart()
	manifest, _ := call("GET", "/api/v1/platform", "", "", 200)
	if manifest["version"] != "0.7.0-device-delete" || manifest["stage"] != "P1_DEVICE_DELETE" || manifest["capabilities"].(map[string]any)["source_update"] != "implemented" || manifest["capabilities"].(map[string]any)["device_update"] != "implemented" {
		t.Fatal("source update manifest")
	}
	replay, h = patch(canonical, "source-update-shared", 200)
	checkSuccess(replay, h, "true")
	if !reflect.DeepEqual(replay["source"], firstSource) || replay["request_id"] == first["request_id"] {
		t.Fatal("historical replay lost after restart/token rotation")
	}
	current, _ := call("GET", path, "", "", 200)
	if !reflect.DeepEqual(current["source"], second["source"]) {
		t.Fatal("replay reverted current source")
	}
	listed, _ := call("GET", "/api/v1/sources?device_id=source-update-parent&limit=1", "", "", 200)
	if !reflect.DeepEqual(listed["items"].([]any)[0], second["source"]) {
		t.Fatal("list did not reflect rename")
	}
	last, _ := call("GET", "/api/v1/sources?device_id=source-update-parent&cursor="+cursor, "", "", 200)
	if len(last["items"].([]any)) != 1 || !reflect.DeepEqual(last["items"].([]any)[0], sibling["source"]) || last["next_cursor"] != nil {
		t.Fatal("cursor/parent filter or sibling changed")
	}
	call("GET", "/api/v1/sources?device_id=d1&cursor="+cursor, "", "", 400)
	postReplay, h := call("POST", "/api/v1/sources", create, "source-update-shared", 201)
	if !reflect.DeepEqual(postReplay["source"], original) || h.Get("Idempotency-Replayed") != "true" {
		t.Fatal("source PATCH changed POST snapshot")
	}
	currentParent, _ := call("GET", parentPath, "", "", 200)
	if !reflect.DeepEqual(currentParent["device"], parent["device"]) {
		t.Fatal("source rename changed parent")
	}
	parentReplay, h := call("PATCH", parentPath, body(1, "parent renamed"), "source-update-shared", 200)
	if !reflect.DeepEqual(parentReplay["device"], parent["device"]) || h.Get("Idempotency-Replayed") != "true" {
		t.Fatal("device PATCH replay regressed")
	}
	other, h := call("PATCH", "/api/v1/sources/source-update-b", body(1, "other"), "source-update-shared", 200)
	checkSuccess(other, h, "false")
	if other["source"].(map[string]any)["source_id"] != "source-update-b" {
		t.Fatal("source path scope collision")
	}
	same, h := patch(body(3, "newest"), "source-same-name", 200)
	checkSuccess(same, h, "false")
	if same["source"].(map[string]any)["version"] != float64(4) {
		t.Fatal("same-name version increment")
	}
	sql(`ALTER TABLE camera.source_update_requests ADD CONSTRAINT injected_source_http_failure CHECK(response_body->>'display_name' <> 'atomic-after')`)
	value, h = patch(body(4, "atomic-after"), "source-atomic", 503)
	checkError(value, h, "DATABASE_UNAVAILABLE")
	current, _ = call("GET", path, "", "", 200)
	if !reflect.DeepEqual(current["source"], same["source"]) {
		t.Fatal("partial source rename after journal failure")
	}
	sql("ALTER TABLE camera.source_update_requests DROP CONSTRAINT injected_source_http_failure")
	latest, h := patch(body(4, "atomic-after"), "source-atomic", 200)
	checkSuccess(latest, h, "false")
	if latest["source"].(map[string]any)["version"] != float64(5) {
		t.Fatal("retry version")
	}
	if !wasm {
		quoted := pgx.Identifier{role}.Sanitize()
		for _, privilege := range []string{"INSERT ON camera.source_update_requests", "SELECT ON camera.source_update_requests", "UPDATE (display_name) ON camera.video_sources", "UPDATE (version) ON camera.video_sources", "UPDATE (updated_at) ON camera.video_sources"} {
			sql("REVOKE " + privilege + " FROM " + quoted)
			call("GET", "/health/ready", "", "", 503)
			value, h = patch(body(5, "after-grants"), "source-permission", 503)
			checkError(value, h, "DATABASE_UNAVAILABLE")
			current, _ = call("GET", path, "", "", 200)
			if !reflect.DeepEqual(current["source"], latest["source"]) {
				t.Fatal("partial source rename after privilege loss")
			}
			sql("GRANT " + privilege + " TO " + quoted)
		}
		latest, h = patch(body(5, "after-grants"), "source-permission", 200)
		checkSuccess(latest, h, "false")
		if latest["source"].(map[string]any)["version"] != float64(6) {
			t.Fatal("privilege recovery version")
		}
		call("GET", "/health/ready", "", "", 200)
		t.Log("source PATCH privilege loss returned 503; readiness, atomic rollback and same-key recovery passed")
	}
	sql("UPDATE camera.video_sources SET version=9223372036854775807 WHERE source_id='source-update-b'")
	value, h = call("PATCH", "/api/v1/sources/source-update-b", `{"schema_version":"v1","expected_version":9223372036854775807,"display_name":"full"}`, "source-exhausted", 409)
	checkError(value, h, "SOURCE_VERSION_EXHAUSTED")
	value, h = call("PATCH", "/api/v1/sources/source-update-b", body(1, "stale"), "source-stale-max", 409)
	checkError(value, h, "SOURCE_VERSION_CONFLICT")
	sql("UPDATE camera.video_sources SET deleted_at=clock_timestamp() WHERE source_id='source-update-a'")
	value, h = patch(body(1, "deleted"), "source-deleted", 404)
	checkError(value, h, "SOURCE_NOT_FOUND")
	replay, h = patch(canonical, "source-update-shared", 200)
	checkSuccess(replay, h, "true")
	if !reflect.DeepEqual(replay["source"], firstSource) {
		t.Fatal("historical source replay after tombstone")
	}
	call("GET", path, "", "", 404)
	for _, reserved := range []string{"/api/v1/sources/validate", "/api/v1/sources/%76alidate"} {
		value, h = call("PATCH", reserved, body(1, "reserved"), "source-reserved", 405)
		checkError(value, h, "METHOD_NOT_ALLOWED")
		if h.Get("Allow") != "POST" {
			t.Fatal("validation route method changed")
		}
	}
	value, h = call("PUT", "/api/v1/sources/source-update-b", "", "", 405)
	checkError(value, h, "METHOD_NOT_ALLOWED")
	if h.Get("Allow") != "GET, PATCH, DELETE" {
		t.Fatal("source method list")
	}
	t.Log("source PATCH/full profiles, canonical/path/history replay, parent/sibling and POST/device PATCH preservation, cursor/filter, restart/token rotation, conflicts, atomic failure/retry, tombstone and exhaustion passed")
}
