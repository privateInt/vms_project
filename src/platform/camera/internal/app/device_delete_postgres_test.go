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
	"vms.local/platform/camera/internal/contracts"
)

// The shared fixture uses a real HTTP subprocess and a disposable DB. Native
// role/grant checks run only with PostgreSQL; PGlite verifies the serial flow.
func verifyDeviceDeleteHTTP(t *testing.T, call func(string, string, string, string, int) (map[string]any, http.Header), sql func(string), restart func(), wasm bool, role string) {
	t.Helper()
	path := "/api/v1/devices/device-delete-a"
	create := strings.Replace(testDevice, `"d1"`, `"device-delete-a"`, 1)
	original, _ := call("POST", "/api/v1/devices", create, "device-delete-shared", 201)
	otherBody := strings.Replace(create, `"device-delete-a"`, `"device-delete-b"`, 1)
	other, _ := call("POST", "/api/v1/devices", otherBody, "device-delete-other", 201)
	renamed, _ := call("PATCH", path, testDeviceUpdate, "device-delete-shared", 200)
	sourceBody := strings.NewReplacer(`"d1"`, `"device-delete-a"`, `"s1"`, `"device-delete-child-a"`).Replace(testSource)
	sourceOriginal, _ := call("POST", "/api/v1/sources", sourceBody, "device-delete-shared", 201)
	sourceRenamed, _ := call("PATCH", "/api/v1/sources/device-delete-child-a", testSourceUpdate, "device-delete-shared", 200)
	secondBody := strings.NewReplacer(`"device-delete-child-a"`, `"device-delete-child-b"`, `"ch1"`, `"ch2"`).Replace(sourceBody)
	call("POST", "/api/v1/sources", secondBody, "device-delete-second", 201)
	body := `{"schema_version":"v1","expected_version":2}`
	checkError := func(value map[string]any, h http.Header, code string) {
		t.Helper()
		if value["error"].(map[string]any)["code"] != code || value["request_id"] != h.Get("X-Request-ID") || h.Get("Location") != "" || h.Get("Idempotency-Replayed") != "" || h.Get("Cache-Control") != "no-store" {
			t.Fatal("device deletion error envelope", value, h)
		}
	}
	checkSuccess := func(value map[string]any, h http.Header, replay string) {
		t.Helper()
		if len(value) != 4 || value["registration_state"] != "DELETED" || value["runtime_verified"] != false || value["request_id"] == "" || value["request_id"] != h.Get("X-Request-ID") || h.Get("Idempotency-Replayed") != replay || h.Get("Location") != "" || h.Get("Cache-Control") != "no-store" {
			t.Fatal("device deletion metadata", value, h)
		}
		receipt, ok := value["deletion"].(map[string]any)
		if !ok || len(receipt) != 4 || receipt["schema_version"] != "v1" {
			t.Fatal("minimal device receipt", value)
		}
	}
	value, h := call("DELETE", path, testDeviceDelete, "device-delete-stale", 409)
	checkError(value, h, "DEVICE_VERSION_CONFLICT") // before the active child check
	value, h = call("DELETE", "/api/v1/devices/absent", testDeviceDelete, "device-delete-absent", 404)
	checkError(value, h, "DEVICE_NOT_FOUND")
	value, h = call("DELETE", path, body, "device-delete-shared", 409)
	checkError(value, h, "DEVICE_HAS_ACTIVE_SOURCES")
	sourceDeleted, _ := call("DELETE", "/api/v1/sources/device-delete-child-a", body, "device-delete-shared", 200)
	value, h = call("DELETE", path, body, "device-delete-shared", 409)
	checkError(value, h, "DEVICE_HAS_ACTIVE_SOURCES")
	secondDeleted, _ := call("DELETE", "/api/v1/sources/device-delete-child-b", testDeviceDelete, "device-delete-shared", 200)
	current, _ := call("GET", path, "", "", 200)
	if !reflect.DeepEqual(current["device"], renamed["device"]) {
		t.Fatal("source deletion changed parent version")
	}
	// Obtain a real page cursor naming the soon-to-be-deleted device.
	page, _ := call("GET", "/api/v1/devices?limit=1&cursor="+url.QueryEscape(contracts.EncodeDeviceCursor("device-delete-")), "", "", 200)
	if page["items"].([]any)[0].(map[string]any)["device_id"] != "device-delete-a" || page["next_cursor"] == nil {
		t.Fatal("device page fixture", page)
	}
	cursor := url.QueryEscape(page["next_cursor"].(string))
	sql(`CREATE TABLE camera.http_device_delete_before AS SELECT
 (to_jsonb(d)-'version'-'updated_at'-'deleted_at') AS declaration,
 (SELECT jsonb_agg(to_jsonb(s) ORDER BY source_id) FROM camera.video_sources s WHERE s.device_id=d.device_id) AS children,
 (SELECT jsonb_agg(to_jsonb(p) ORDER BY p.source_id,p.position) FROM camera.stream_profiles p JOIN camera.video_sources s USING(source_id) WHERE s.device_id=d.device_id) AS profiles,
 jsonb_build_object(
 'device_create',(SELECT jsonb_agg(to_jsonb(j) ORDER BY path,key_hash) FROM camera.device_create_requests j),
 'device_update',(SELECT jsonb_agg(to_jsonb(j) ORDER BY path,key_hash) FROM camera.device_update_requests j),
 'source_create',(SELECT jsonb_agg(to_jsonb(j) ORDER BY path,key_hash) FROM camera.source_create_requests j),
 'source_update',(SELECT jsonb_agg(to_jsonb(j) ORDER BY path,key_hash) FROM camera.source_update_requests j),
 'source_delete',(SELECT jsonb_agg(to_jsonb(j) ORDER BY path,key_hash) FROM camera.source_delete_requests j)) AS histories
 FROM camera.devices d WHERE d.device_id='device-delete-a'`)
	sql(`ALTER TABLE camera.device_delete_requests ADD CONSTRAINT injected_device_delete_http_failure CHECK(response_body->>'device_id' <> 'device-delete-a')`)
	value, h = call("DELETE", path, body, "device-delete-shared", 503)
	checkError(value, h, "DATABASE_UNAVAILABLE")
	current, _ = call("GET", path, "", "", 200)
	if !reflect.DeepEqual(current["device"], renamed["device"]) {
		t.Fatal("partial device deletion after receipt failure")
	}
	sql("ALTER TABLE camera.device_delete_requests DROP CONSTRAINT injected_device_delete_http_failure")
	first, h := call("DELETE", path, body, "device-delete-shared", 200)
	checkSuccess(first, h, "false") // failed child/journal checks did not reserve the key
	receipt := first["deletion"].(map[string]any)
	if receipt["device_id"] != "device-delete-a" || receipt["version"] != float64(3) {
		t.Fatal("device deletion version/identity", receipt)
	}
	before, _ := time.Parse(time.RFC3339Nano, renamed["device"].(map[string]any)["updated_at"].(string))
	deleted, err := time.Parse(time.RFC3339Nano, receipt["deleted_at"].(string))
	if err != nil || deleted.Before(before) || !strings.HasSuffix(receipt["deleted_at"].(string), "Z") {
		t.Fatal("device deletion time", receipt)
	}
	sql(`DO $$BEGIN
 IF NOT EXISTS (SELECT 1 FROM camera.devices d CROSS JOIN camera.http_device_delete_before b
 WHERE device_id='device-delete-a' AND version=3 AND deleted_at=updated_at AND deleted_at IS NOT NULL
 AND (to_jsonb(d)-'version'-'updated_at'-'deleted_at')=b.declaration
 AND (SELECT jsonb_agg(to_jsonb(s) ORDER BY source_id) FROM camera.video_sources s WHERE s.device_id=d.device_id)=b.children
 AND (SELECT jsonb_agg(to_jsonb(p) ORDER BY p.source_id,p.position) FROM camera.stream_profiles p JOIN camera.video_sources s USING(source_id) WHERE s.device_id=d.device_id)=b.profiles
 AND jsonb_build_object(
 'device_create',(SELECT jsonb_agg(to_jsonb(j) ORDER BY path,key_hash) FROM camera.device_create_requests j),
 'device_update',(SELECT jsonb_agg(to_jsonb(j) ORDER BY path,key_hash) FROM camera.device_update_requests j),
 'source_create',(SELECT jsonb_agg(to_jsonb(j) ORDER BY path,key_hash) FROM camera.source_create_requests j),
 'source_update',(SELECT jsonb_agg(to_jsonb(j) ORDER BY path,key_hash) FROM camera.source_update_requests j),
 'source_delete',(SELECT jsonb_agg(to_jsonb(j) ORDER BY path,key_hash) FROM camera.source_delete_requests j))=b.histories)
 THEN RAISE EXCEPTION 'device/children/profiles/histories changed'; END IF;
 END$$`)
	canonical := `{"expected_version":2,"schema_version":"\u00761"}`
	replay, h := call("DELETE", "/api/v1/devices/device%2ddelete-a", canonical, "device-delete-shared", 200)
	checkSuccess(replay, h, "true")
	if !reflect.DeepEqual(replay["deletion"], receipt) || replay["request_id"] == first["request_id"] {
		t.Fatal("device canonical/path replay")
	}
	value, h = call("DELETE", path, testDeviceDelete, "device-delete-shared", 409)
	checkError(value, h, "IDEMPOTENCY_CONFLICT")
	value, h = call("DELETE", path, body, "device-delete-new", 404)
	checkError(value, h, "DEVICE_NOT_FOUND")
	value, h = call("PATCH", path, testDeviceUpdate, "device-delete-new", 404)
	checkError(value, h, "DEVICE_NOT_FOUND")
	call("GET", path, "", "", 404)
	listed, _ := call("GET", "/api/v1/devices?limit=200", "", "", 200)
	for _, item := range listed["items"].([]any) {
		if item.(map[string]any)["device_id"] == "device-delete-a" {
			t.Fatal("deleted device listed")
		}
	}
	last, _ := call("GET", "/api/v1/devices?limit=1&cursor="+cursor, "", "", 200)
	if !reflect.DeepEqual(last["items"].([]any)[0], other["device"]) {
		t.Fatal("cursor failed after device deletion")
	}
	sources, _ := call("GET", "/api/v1/sources?device_id=device-delete-a", "", "", 200)
	if len(sources["items"].([]any)) != 0 || sources["next_cursor"] != nil {
		t.Fatal("deleted parent source filter")
	}
	value, h = call("POST", "/api/v1/devices", create, "device-delete-recreate", 409)
	checkError(value, h, "DEVICE_EXISTS")
	newSource := strings.NewReplacer(`"device-delete-child-a"`, `"device-delete-new-child"`, `"ch1"`, `"ch-new"`).Replace(sourceBody)
	value, h = call("POST", "/api/v1/sources", newSource, "device-delete-new-source", 409)
	checkError(value, h, "DEVICE_UNAVAILABLE")
	sql(`DO $$BEGIN
 IF EXISTS(SELECT 1 FROM camera.video_sources WHERE source_id='device-delete-new-child')
 OR EXISTS(SELECT 1 FROM camera.stream_profiles WHERE source_id='device-delete-new-child')
 OR EXISTS(SELECT 1 FROM camera.source_create_requests WHERE response_body->>'source_id'='device-delete-new-child')
 THEN RAISE EXCEPTION 'source creation after deletion persisted data'; END IF;
 END$$`)
	restart()
	manifest, _ := call("GET", "/api/v1/platform", "", "", 200)
	caps := manifest["capabilities"].(map[string]any)
	if manifest["version"] != "0.7.0-device-delete" || manifest["stage"] != "P1_DEVICE_DELETE" || caps["device_delete"] != "implemented" || caps["source_delete"] != "implemented" || caps["source_sessions"] != "planned" || caps["onvif_ptz"] != "planned" {
		t.Fatal("device deletion manifest", manifest)
	}
	replay, h = call("DELETE", path, canonical, "device-delete-shared", 200)
	checkSuccess(replay, h, "true")
	if !reflect.DeepEqual(replay["deletion"], receipt) || replay["request_id"] == first["request_id"] {
		t.Fatal("device receipt lost after restart/token rotation")
	}
	for _, old := range []struct {
		method, path, body, field string
		status                    int
		expected                  any
	}{
		{"POST", "/api/v1/devices", create, "device", 201, original["device"]},
		{"PATCH", path, testDeviceUpdate, "device", 200, renamed["device"]},
		{"POST", "/api/v1/sources", sourceBody, "source", 201, sourceOriginal["source"]},
		{"PATCH", "/api/v1/sources/device-delete-child-a", testSourceUpdate, "source", 200, sourceRenamed["source"]},
		{"DELETE", "/api/v1/sources/device-delete-child-a", body, "deletion", 200, sourceDeleted["deletion"]},
		{"DELETE", "/api/v1/sources/device-delete-child-b", testDeviceDelete, "deletion", 200, secondDeleted["deletion"]},
	} {
		historical, headers := call(old.method, old.path, old.body, "device-delete-shared", old.status)
		if !reflect.DeepEqual(historical[old.field], old.expected) || headers.Get("Idempotency-Replayed") != "true" {
			t.Fatal("history lost after parent deletion", old.method, old.path)
		}
	}
	call("GET", path, "", "", 404)
	call("GET", "/api/v1/sources/device-delete-child-a", "", "", 404)
	if !wasm {
		quoted := pgx.Identifier{role}.Sanitize()
		for _, privilege := range []string{"INSERT ON camera.device_delete_requests", "SELECT ON camera.device_delete_requests", "UPDATE (deleted_at) ON camera.devices", "UPDATE (version) ON camera.devices", "UPDATE (updated_at) ON camera.devices"} {
			sql("REVOKE " + privilege + " FROM " + quoted)
			call("GET", "/health/ready", "", "", 503)
			value, h = call("DELETE", "/api/v1/devices/device-delete-b", testDeviceDelete, "device-delete-permission", 503)
			checkError(value, h, "DATABASE_UNAVAILABLE")
			current, _ = call("GET", "/api/v1/devices/device-delete-b", "", "", 200)
			if !reflect.DeepEqual(current["device"], other["device"]) {
				t.Fatal("partial device deletion after grant loss")
			}
			sql("GRANT " + privilege + " TO " + quoted)
		}
		recovered, headers := call("DELETE", "/api/v1/devices/device-delete-b", testDeviceDelete, "device-delete-permission", 200)
		checkSuccess(recovered, headers, "false")
		call("GET", "/health/ready", "", "", 200)
		t.Log("device DELETE native grant loss: HTTP 503/readiness failure, atomic rollback and same-key recovery passed")
	}
	for _, id := range []string{"validate", "Validate", "validate-1", "device-delete-max"} {
		call("POST", "/api/v1/devices", strings.Replace(create, `"device-delete-a"`, fmt.Sprintf("%q", id), 1), "device-delete-"+id, 201)
		if id == "device-delete-max" {
			sql("UPDATE camera.devices SET version=9223372036854775807 WHERE device_id='device-delete-max'")
			value, h = call("DELETE", "/api/v1/devices/"+id, `{"schema_version":"v1","expected_version":9223372036854775807}`, "device-delete-shared", 409)
			checkError(value, h, "DEVICE_VERSION_EXHAUSTED")
			continue
		}
		normal, headers := call("DELETE", "/api/v1/devices/"+id, testDeviceDelete, "device-delete-shared", 200)
		checkSuccess(normal, headers, "false")
		if id == "validate" {
			for _, escaped := range []string{"%76alidate", "val%69date"} {
				alias, aliasHeaders := call("DELETE", "/api/v1/devices/"+escaped, testDeviceDelete, "device-delete-shared", 200)
				checkSuccess(alias, aliasHeaders, "true")
				if !reflect.DeepEqual(alias["deletion"], normal["deletion"]) {
					t.Fatal("validate device replay mismatch")
				}
			}
		}
	}
	sql("DROP TABLE camera.http_device_delete_before")
	t.Log("device DELETE real HTTP: child rejection/retry, source DELETE regression, receipt/rollback, canonical/path/history replay, tombstone/cursor/ID reservation, preservation, restart/token rotation, conflicts, exhaustion and validate device passed")
}
