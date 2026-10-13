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

// Runs only in the shared disposable DB fixture, against a real API process.
func verifySourceDeleteHTTP(t *testing.T, call func(string, string, string, string, int) (map[string]any, http.Header), sql func(string), restart func(), wasm bool, role string) {
	t.Helper()
	path := "/api/v1/sources/source-delete-a"
	parent, _ := call("POST", "/api/v1/devices", strings.Replace(testDevice, `"d1"`, `"source-delete-parent"`, 1), "source-delete-parent", 201)
	create := strings.NewReplacer(`"s1"`, `"source-delete-a"`, `"d1"`, `"source-delete-parent"`).Replace(testSource)
	original, _ := call("POST", "/api/v1/sources", create, "source-delete-shared", 201)
	siblingBody := strings.NewReplacer(`"source-delete-a"`, `"source-delete-b"`, `"ch1"`, `"ch2"`).Replace(create)
	sibling, _ := call("POST", "/api/v1/sources", siblingBody, "source-delete-sibling", 201)
	renamed, _ := call("PATCH", path, testSourceUpdate, "source-delete-shared", 200)
	page, _ := call("GET", "/api/v1/sources?device_id=source-delete-parent&limit=1", "", "", 200)
	cursor := url.QueryEscape(page["next_cursor"].(string))
	body := `{"schema_version":"v1","expected_version":2}`
	checkError := func(value map[string]any, h http.Header, code string) {
		t.Helper()
		if value["error"].(map[string]any)["code"] != code || value["request_id"] != h.Get("X-Request-ID") || h.Get("Location") != "" || h.Get("Idempotency-Replayed") != "" || h.Get("Cache-Control") != "no-store" {
			t.Fatal("delete error envelope", value, h)
		}
	}
	checkSuccess := func(value map[string]any, h http.Header, replay string) {
		t.Helper()
		if len(value) != 4 || value["registration_state"] != "DELETED" || value["runtime_verified"] != false || value["request_id"] == "" || value["request_id"] != h.Get("X-Request-ID") || h.Get("Idempotency-Replayed") != replay || h.Get("Location") != "" || h.Get("Cache-Control") != "no-store" {
			t.Fatal("delete response metadata", value, h)
		}
		receipt, ok := value["deletion"].(map[string]any)
		if !ok || len(receipt) != 4 || receipt["schema_version"] != "v1" {
			t.Fatal("minimal deletion receipt", value)
		}
	}
	value, h := call("DELETE", path, testSourceDelete, "source-delete-stale", 409)
	checkError(value, h, "SOURCE_VERSION_CONFLICT")
	value, h = call("DELETE", "/api/v1/sources/absent", testSourceDelete, "source-delete-missing", 404)
	checkError(value, h, "SOURCE_NOT_FOUND")
	// A failed journal write must roll back the tombstone as well as its version.
	sql(`ALTER TABLE camera.source_delete_requests ADD CONSTRAINT injected_delete_http_failure CHECK(response_body->>'source_id' <> 'source-delete-a')`)
	value, h = call("DELETE", path, body, "source-delete-shared", 503)
	checkError(value, h, "DATABASE_UNAVAILABLE")
	current, _ := call("GET", path, "", "", 200)
	if !reflect.DeepEqual(current["source"], renamed["source"]) {
		t.Fatal("partial delete after journal failure")
	}
	sql("ALTER TABLE camera.source_delete_requests DROP CONSTRAINT injected_delete_http_failure")
	// Snapshot retained declaration/profile rows through the fixture's admin only.
	sql(`CREATE TABLE camera.http_delete_before AS SELECT
 (to_jsonb(s)-'version'-'updated_at'-'deleted_at') AS declaration,
 (SELECT jsonb_agg(to_jsonb(p) ORDER BY position) FROM camera.stream_profiles p WHERE p.source_id=s.source_id) AS profiles
 FROM camera.video_sources s WHERE s.source_id='source-delete-a'`)
	first, h := call("DELETE", path, body, "source-delete-shared", 200)
	checkSuccess(first, h, "false")
	receipt := first["deletion"].(map[string]any)
	if receipt["source_id"] != "source-delete-a" || receipt["version"] != float64(3) {
		t.Fatal("deletion version/identity", receipt)
	}
	before, _ := time.Parse(time.RFC3339Nano, renamed["source"].(map[string]any)["updated_at"].(string))
	deleted, err := time.Parse(time.RFC3339Nano, receipt["deleted_at"].(string))
	if err != nil || deleted.Before(before) || !strings.HasSuffix(receipt["deleted_at"].(string), "Z") {
		t.Fatal("deletion time", receipt)
	}
	sql(`DO $$BEGIN
 IF NOT EXISTS (SELECT 1 FROM camera.video_sources s CROSS JOIN camera.http_delete_before b
 WHERE source_id='source-delete-a' AND version=3 AND deleted_at=updated_at AND deleted_at IS NOT NULL
 AND (to_jsonb(s)-'version'-'updated_at'-'deleted_at')=b.declaration
 AND (SELECT jsonb_agg(to_jsonb(p) ORDER BY position) FROM camera.stream_profiles p WHERE p.source_id=s.source_id)=b.profiles)
 THEN RAISE EXCEPTION 'source declaration/profiles/tombstone changed'; END IF;
 END$$`)
	canonical := `{"expected_version":2,"schema_version":"\u00761"}`
	replay, h := call("DELETE", "/api/v1/sources/source%2ddelete-a", canonical, "source-delete-shared", 200)
	checkSuccess(replay, h, "true")
	if !reflect.DeepEqual(replay["deletion"], receipt) || replay["request_id"] == first["request_id"] {
		t.Fatal("canonical/path replay")
	}
	value, h = call("DELETE", path, testSourceDelete, "source-delete-shared", 409)
	checkError(value, h, "IDEMPOTENCY_CONFLICT")
	value, h = call("DELETE", path, body, "source-delete-new", 404)
	checkError(value, h, "SOURCE_NOT_FOUND")
	value, h = call("PATCH", path, testSourceUpdate, "source-delete-new-patch", 404)
	checkError(value, h, "SOURCE_NOT_FOUND")
	call("GET", path, "", "", 404)
	listed, _ := call("GET", "/api/v1/sources?device_id=source-delete-parent", "", "", 200)
	last, _ := call("GET", "/api/v1/sources?device_id=source-delete-parent&cursor="+cursor, "", "", 200)
	for _, result := range []map[string]any{listed, last} {
		if len(result["items"].([]any)) != 1 || !reflect.DeepEqual(result["items"].([]any)[0], sibling["source"]) || result["next_cursor"] != nil {
			t.Fatal("list/cursor after delete", result)
		}
	}
	currentParent, _ := call("GET", "/api/v1/devices/source-delete-parent", "", "", 200)
	if !reflect.DeepEqual(currentParent["device"], parent["device"]) {
		t.Fatal("parent changed")
	}
	call("POST", "/api/v1/sources", create, "source-delete-recreate", 409)
	call("POST", "/api/v1/sources", strings.Replace(create, `"source-delete-a"`, `"source-delete-new"`, 1), "source-delete-reuse-channel", 409)
	restart()
	manifest, _ := call("GET", "/api/v1/platform", "", "", 200)
	caps := manifest["capabilities"].(map[string]any)
	if manifest["version"] != "0.7.0-device-delete" || manifest["stage"] != "P1_DEVICE_DELETE" || caps["source_delete"] != "implemented" || caps["source_sessions"] != "planned" || caps["source_consumers"] != "planned" {
		t.Fatal("delete manifest", manifest)
	}
	replay, h = call("DELETE", path, canonical, "source-delete-shared", 200)
	checkSuccess(replay, h, "true")
	if !reflect.DeepEqual(replay["deletion"], receipt) || replay["request_id"] == first["request_id"] {
		t.Fatal("delete replay after restart/token rotation")
	}
	for _, old := range []struct {
		method, path, body string
		status             int
		expected           any
	}{
		{"POST", "/api/v1/sources", create, 201, original["source"]},
		{"PATCH", path, testSourceUpdate, 200, renamed["source"]},
	} {
		historical, headers := call(old.method, old.path, old.body, "source-delete-shared", old.status)
		if !reflect.DeepEqual(historical["source"], old.expected) || headers.Get("Idempotency-Replayed") != "true" {
			t.Fatal("old success replay lost", old.method)
		}
	}
	call("GET", path, "", "", 404)
	if !wasm {
		quoted := pgx.Identifier{role}.Sanitize()
		for _, privilege := range []string{"INSERT ON camera.source_delete_requests", "SELECT ON camera.source_delete_requests", "UPDATE (deleted_at) ON camera.video_sources", "UPDATE (version) ON camera.video_sources", "UPDATE (updated_at) ON camera.video_sources"} {
			sql("REVOKE " + privilege + " FROM " + quoted)
			call("GET", "/health/ready", "", "", 503)
			value, h = call("DELETE", "/api/v1/sources/source-delete-b", testSourceDelete, "source-delete-permission", 503)
			checkError(value, h, "DATABASE_UNAVAILABLE")
			current, _ = call("GET", "/api/v1/sources/source-delete-b", "", "", 200)
			if !reflect.DeepEqual(current["source"], sibling["source"]) {
				t.Fatal("partial delete after privilege loss")
			}
			sql("GRANT " + privilege + " TO " + quoted)
		}
		recovered, headers := call("DELETE", "/api/v1/sources/source-delete-b", testSourceDelete, "source-delete-permission", 200)
		checkSuccess(recovered, headers, "false")
		call("GET", "/health/ready", "", "", 200)
		t.Log("source DELETE privilege loss returned 503; readiness, atomic rollback and same-key recovery passed")
	}
	exhaustedBody := strings.NewReplacer(`"source-delete-a"`, `"source-delete-max"`, `"ch1"`, `"ch-max"`).Replace(create)
	call("POST", "/api/v1/sources", exhaustedBody, "source-delete-max", 201)
	sql("UPDATE camera.video_sources SET version=9223372036854775807 WHERE source_id='source-delete-max'")
	value, h = call("DELETE", "/api/v1/sources/source-delete-max", `{"schema_version":"v1","expected_version":9223372036854775807}`, "source-delete-exhausted", 409)
	checkError(value, h, "SOURCE_VERSION_EXHAUSTED")
	for _, id := range []string{"Validate", "validate-1"} {
		normalBody := strings.NewReplacer(`"source-delete-a"`, fmt.Sprintf("%q", id), `"ch1"`, fmt.Sprintf("%q", id)).Replace(create)
		call("POST", "/api/v1/sources", normalBody, "source-delete-"+id, 201)
		normal, headers := call("DELETE", "/api/v1/sources/"+id, testSourceDelete, "source-delete-shared", 200)
		checkSuccess(normal, headers, "false")
	}
	for _, reserved := range []string{"validate", "%76alidate", "val%69date"} {
		value, h = call("DELETE", "/api/v1/sources/"+reserved, testSourceDelete, "source-delete-reserved", 405)
		checkError(value, h, "METHOD_NOT_ALLOWED")
		if h.Get("Allow") != "POST" {
			t.Fatal("reserved route")
		}
	}
	sql("DROP TABLE camera.http_delete_before")
	t.Log("source DELETE receipt, rollback/retry, exact version, canonical/path/history replay, profile/parent/sibling preservation, list/cursor exclusion, ID/channel retention, restart/token rotation, conflicts and reserved routes passed")
}
