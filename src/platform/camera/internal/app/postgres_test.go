package app

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"vms.local/platform/camera/internal/storage"
)

// A real API subprocess and PostgreSQL connection verify process restart,
// transport behavior and least-privilege access. Run packages serially (-p 1):
// storage integration tests also reset this dedicated disposable schema.
func TestRegistryAPIWithPostgres(t *testing.T) {
	dsn := os.Getenv("CAMERA_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("CAMERA_TEST_DATABASE_URL absent: API/DB integration not executed")
	}
	if os.Getenv("CAMERA_TEST_ALLOW_SCHEMA_RESET") != "1" {
		t.Fatal("disposable DB reset opt-in required")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 180*time.Second)
	defer cancel()
	admin, err := pgx.Connect(ctx, dsn)
	if err != nil {
		t.Fatal("test DB connection failed")
	}
	defer admin.Close(context.Background())
	var database, engine string
	if err = admin.QueryRow(ctx, "SELECT current_database(),version()").Scan(&database, &engine); err != nil {
		t.Fatal(err)
	}
	wasm := os.Getenv("CAMERA_TEST_ENGINE") == "pglite" && strings.Contains(engine, "(PGlite ")
	if database != "vms_camera_test" && !wasm {
		t.Fatal("refusing to reset non-test database")
	}
	t.Log("database engine:", engine)
	sql := func(statement string) {
		t.Helper()
		if _, e := admin.Exec(ctx, statement); e != nil {
			t.Fatal(e)
		}
	}
	sql("DROP SCHEMA IF EXISTS camera CASCADE")
	defer func() { _, _ = admin.Exec(context.Background(), "DROP SCHEMA IF EXISTS camera CASCADE") }()
	migrator, err := storage.Open(ctx, dsn)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = migrator.Migrate(ctx); err != nil {
		migrator.Close()
		t.Fatal(err)
	}
	migrator.Close()
	runtimeDSN := dsn
	role := ""
	if !wasm {
		var random [16]byte
		if _, err = rand.Read(random[:]); err != nil {
			t.Fatal(err)
		}
		role = "camera_test_" + hex.EncodeToString(random[:6])
		password := hex.EncodeToString(random[:])
		quoted := pgx.Identifier{role}.Sanitize()
		sql("CREATE ROLE " + quoted + " LOGIN PASSWORD '" + password + "'")
		defer func() {
			_, _ = admin.Exec(context.Background(), "DROP OWNED BY "+quoted)
			_, _ = admin.Exec(context.Background(), "DROP ROLE "+quoted)
		}()
		sql("GRANT USAGE ON SCHEMA camera TO " + quoted)
		sql("GRANT SELECT ON camera.schema_migrations TO " + quoted)
		sql("GRANT SELECT,INSERT ON camera.devices,camera.device_create_requests,camera.video_sources,camera.stream_profiles,camera.source_create_requests,camera.device_update_requests,camera.source_update_requests,camera.source_delete_requests,camera.device_delete_requests TO " + quoted)
		sql("GRANT UPDATE (display_name,version,updated_at,deleted_at) ON camera.devices TO " + quoted)
		sql("GRANT UPDATE (display_name,version,updated_at,deleted_at) ON camera.video_sources TO " + quoted)
		sql("GRANT EXECUTE ON FUNCTION camera.device_has_active_credentials(text) TO " + quoted)
		u, e := url.Parse(dsn)
		if e != nil {
			t.Fatal(e)
		}
		u.User = url.UserPassword(role, password)
		runtimeDSN = u.String()
	}
	t.Run("runtime_permissions", func(t *testing.T) {
		if wasm {
			t.Skip("PGlite socket cannot verify native role authentication")
		}
		conn, e := pgx.Connect(ctx, runtimeDSN)
		if e != nil {
			t.Fatal("runtime connection failed")
		}
		defer conn.Close(context.Background())
		var user string
		if e = conn.QueryRow(ctx, "SELECT current_user").Scan(&user); e != nil || user != role {
			t.Fatal("runtime identity incorrect", e)
		}
		for _, query := range []string{"CREATE TABLE camera.forbidden(id int)", "DELETE FROM camera.devices", "UPDATE camera.devices SET device_kind='TEST'", "UPDATE camera.video_sources SET transport=transport", "DELETE FROM camera.stream_profiles", "ALTER TABLE camera.devices ADD COLUMN forbidden integer"} {
			_, e = conn.Exec(ctx, query)
			var denied *pgconn.PgError
			if !errors.As(e, &denied) || denied.Code != "42501" {
				t.Fatal("expected insufficient privilege SQLSTATE 42501")
			}
		}
	})
	binary := filepath.Join(t.TempDir(), "camera-api")
	build := exec.CommandContext(ctx, filepath.Join(runtime.GOROOT(), "bin", "go"), "build", "-buildvcs=false", "-race", "-o", binary, "./camera/cmd/camera-api")
	build.Dir = filepath.Join("..", "..", "..")
	if output, e := build.CombinedOutput(); e != nil {
		t.Fatalf("API build failed: %v %s", e, output)
	}
	client := &http.Client{Timeout: 3 * time.Second}
	activeToken := testToken
	dsnFile := filepath.Join(t.TempDir(), "runtime-dsn")
	if err = os.WriteFile(dsnFile, []byte(runtimeDSN+"\n"), 0600); err != nil {
		t.Fatal(err)
	}
	start := func() (string, func()) {
		t.Helper()
		listener, e := net.Listen("tcp", "127.0.0.1:0")
		if e != nil {
			t.Fatal(e)
		}
		address := listener.Addr().String()
		listener.Close()
		command := exec.Command(binary)
		for _, entry := range os.Environ() {
			if !strings.HasPrefix(entry, "CAMERA_DATABASE_URL=") && !strings.HasPrefix(entry, "CAMERA_DATABASE_URL_FILE=") && !strings.HasPrefix(entry, "HTTP_ADDR=") && !strings.HasPrefix(entry, "VMS_API_TOKEN=") {
				command.Env = append(command.Env, entry)
			}
		}
		command.Env = append(command.Env, "CAMERA_DATABASE_URL_FILE="+dsnFile, "HTTP_ADDR="+address, "VMS_API_TOKEN="+activeToken)
		var logs bytes.Buffer
		command.Stdout = &logs
		command.Stderr = &logs
		if e = command.Start(); e != nil {
			t.Fatal(e)
		}
		done := make(chan error, 1)
		go func() { done <- command.Wait() }()
		stopped := false
		stop := func() {
			t.Helper()
			if stopped {
				return
			}
			stopped = true
			client.CloseIdleConnections()
			_ = command.Process.Signal(os.Interrupt)
			select {
			case e := <-done:
				if e != nil {
					t.Errorf("API exited unsuccessfully: %v; diagnostic=%s", e, logs.String())
				}
			case <-time.After(8 * time.Second):
				_ = command.Process.Kill()
				<-done
				t.Error("API shutdown timeout")
			}
			if strings.Contains(logs.String(), testToken) || strings.Contains(logs.String(), activeToken) || strings.Contains(logs.String(), runtimeDSN) || strings.Contains(logs.String(), "입구") {
				t.Error("API log exposed secret or request data")
			}
		}
		t.Cleanup(stop)
		base := "http://" + address
		deadline := time.Now().Add(15 * time.Second)
		for time.Now().Before(deadline) {
			select {
			case e := <-done:
				stopped = true
				t.Fatalf("API startup failed: %v %s", e, logs.String())
			default:
			}
			response, e := client.Get(base + "/health/ready")
			if e == nil {
				_, _ = io.Copy(io.Discard, response.Body)
				response.Body.Close()
				if response.StatusCode == 200 {
					return base, stop
				}
			}
			time.Sleep(40 * time.Millisecond)
		}
		t.Fatal("API readiness timeout")
		return "", stop
	}
	base, stop := start()
	defer stop()
	call := func(method, path, body, key string, status int) (map[string]any, http.Header) {
		t.Helper()
		request, e := http.NewRequest(method, base+path, strings.NewReader(body))
		if e != nil {
			t.Fatal(e)
		}
		request.Header.Set("Authorization", "Bearer "+activeToken)
		request.Header.Set("Content-Type", "application/json")
		if key != "" {
			request.Header.Set("Idempotency-Key", key)
		}
		response, e := client.Do(request)
		if e != nil {
			t.Fatal(e)
		}
		defer response.Body.Close()
		data, e := io.ReadAll(response.Body)
		if e != nil {
			t.Fatal(e)
		}
		var value map[string]any
		if e = json.Unmarshal(data, &value); e != nil {
			t.Fatal("invalid API response")
		}
		if response.StatusCode != status {
			t.Fatalf("%s %s: want %d got %d (%s)", method, path, status, response.StatusCode, data)
		}
		if response.Header.Get("X-Request-ID") == "" {
			t.Fatal("missing request ID")
		}
		return value, response.Header
	}
	value, _ := call("GET", "/api/v1/devices", "", "", 200)
	if len(value["items"].([]any)) != 0 || value["next_cursor"] != nil {
		t.Fatal("empty list shape")
	}
	created, headers := call("POST", "/api/v1/devices", testDevice, "create-1", 201)
	original, _ := json.Marshal(created["device"])
	if headers.Get("Location") != "/api/v1/devices/d1" || headers.Get("Idempotency-Replayed") != "false" {
		t.Fatal("create headers")
	}
	if created["device"].(map[string]any)["version"] != float64(1) {
		t.Fatal("version")
	}
	reordered := `{"device_kind":"CCTV","display_name":"입구","device_id":"d1","schema_version":"v1"}`
	replay, replayHeaders := call("POST", "/api/v1/devices", reordered, "create-1", 201)
	replayed, _ := json.Marshal(replay["device"])
	if !bytes.Equal(original, replayed) || replayHeaders.Get("Idempotency-Replayed") != "true" || created["request_id"] == replay["request_id"] {
		t.Fatal("replay semantics")
	}
	call("POST", "/api/v1/devices", strings.Replace(testDevice, "입구", " 입구 ", 1), "create-1", 409)
	call("POST", "/api/v1/devices", testDevice, "different-key", 409)
	call("GET", "/api/v1/devices/missing", "", "", 404)
	for _, id := range []string{"d2", "d3"} {
		call("POST", "/api/v1/devices", strings.Replace(testDevice, "d1", id, 1), id, 201)
	}
	first, _ := call("GET", "/api/v1/devices?limit=2", "", "", 200)
	items := first["items"].([]any)
	if len(items) != 2 || items[0].(map[string]any)["device_id"] != "d1" || items[1].(map[string]any)["device_id"] != "d2" {
		t.Fatal("first page order")
	}
	second, _ := call("GET", "/api/v1/devices?limit=2&cursor="+url.QueryEscape(first["next_cursor"].(string)), "", "", 200)
	items = second["items"].([]any)
	if len(items) != 1 || items[0].(map[string]any)["device_id"] != "d3" || second["next_cursor"] != nil {
		t.Fatal("second page")
	}
	emptySources, _ := call("GET", "/api/v1/sources", "", "", 200)
	if len(emptySources["items"].([]any)) != 0 || emptySources["next_cursor"] != nil {
		t.Fatal("empty source list shape")
	}
	// The same key used for Device POST belongs to a distinct Source POST scope.
	sourceCreated, sourceHeaders := call("POST", "/api/v1/sources", testSource, "create-1", 201)
	sourceOriginal, _ := json.Marshal(sourceCreated["source"])
	if sourceHeaders.Get("Location") != "/api/v1/sources/s1" || sourceHeaders.Get("Idempotency-Replayed") != "false" || sourceCreated["registration_state"] != "REGISTERED" || sourceCreated["runtime_verified"] != false {
		t.Fatal("source registration response")
	}
	var reorderedSource map[string]any
	_ = json.Unmarshal([]byte(testSource), &reorderedSource)
	canonicalSource, _ := json.Marshal(reorderedSource)
	sourceReplay, sourceReplayHeaders := call("POST", "/api/v1/sources", string(canonicalSource), "create-1", 201)
	sourceReplayed, _ := json.Marshal(sourceReplay["source"])
	if !bytes.Equal(sourceOriginal, sourceReplayed) || sourceReplayHeaders.Get("Idempotency-Replayed") != "true" || sourceCreated["request_id"] == sourceReplay["request_id"] {
		t.Fatal("source canonical replay")
	}
	call("POST", "/api/v1/sources", strings.Replace(testSource, "입구 영상", "changed", 1), "create-1", 409)
	conflict, _ := call("POST", "/api/v1/sources", strings.Replace(testSource, `"s1"`, `"s2"`, 1), "channel-conflict", 409)
	if conflict["error"].(map[string]any)["code"] != "SOURCE_CHANNEL_EXISTS" {
		t.Fatal("channel conflict code")
	}
	call("POST", "/api/v1/sources", testSource, "other-key", 409)
	missing, _ := call("POST", "/api/v1/sources", strings.Replace(testSource, `"d1"`, `"absent"`, 1), "missing-parent", 409)
	if missing["error"].(map[string]any)["code"] != "DEVICE_UNAVAILABLE" {
		t.Fatal("parent error code")
	}
	xrSource := strings.NewReplacer(`"s1"`, `"xr"`, `"ch1"`, `"ch2"`, `"RTSP"`, `"WEBRTC"`, `"PULL"`, `"PUSH"`).Replace(testSource)
	call("POST", "/api/v1/sources", xrSource, "xr", 201)
	call("GET", "/api/v1/sources/absent", "", "", 404)
	call("POST", "/api/v1/sources", strings.NewReplacer(`"s1"`, `"s0"`, `"d1"`, `"d2"`).Replace(testSource), "second-device-source", 201)
	sourcePage, _ := call("GET", "/api/v1/sources?limit=2", "", "", 200)
	sourceItems := sourcePage["items"].([]any)
	if len(sourceItems) != 2 || sourceItems[0].(map[string]any)["source_id"] != "s0" {
		t.Fatal("source page order")
	}
	listedOriginal, _ := json.Marshal(sourceItems[1])
	if !bytes.Equal(sourceOriginal, listedOriginal) {
		t.Fatal("listed source/profile fields differ from single response")
	}
	sourceLast, _ := call("GET", "/api/v1/sources?limit=2&cursor="+url.QueryEscape(sourcePage["next_cursor"].(string)), "", "", 200)
	if len(sourceLast["items"].([]any)) != 1 || sourceLast["items"].([]any)[0].(map[string]any)["source_id"] != "xr" || sourceLast["next_cursor"] != nil {
		t.Fatal("last source page")
	}
	filtered, _ := call("GET", "/api/v1/sources?device_id=d1&limit=1", "", "", 200)
	if filtered["items"].([]any)[0].(map[string]any)["source_id"] != "s1" {
		t.Fatal("device source filter")
	}
	sourcePageCursor := url.QueryEscape(filtered["next_cursor"].(string))
	filteredLast, _ := call("GET", "/api/v1/sources?device_id=d1&limit=200&cursor="+sourcePageCursor, "", "", 200)
	if len(filteredLast["items"].([]any)) != 1 || filteredLast["items"].([]any)[0].(map[string]any)["source_id"] != "xr" || filteredLast["next_cursor"] != nil {
		t.Fatal("filtered cursor with changed limit")
	}
	call("GET", "/api/v1/sources?device_id=d2&cursor="+sourcePageCursor, "", "", 400)
	call("GET", "/api/v1/sources?cursor="+sourcePageCursor, "", "", 400)
	missingSources, _ := call("GET", "/api/v1/sources?device_id=absent", "", "", 200)
	if len(missingSources["items"].([]any)) != 0 || missingSources["next_cursor"] != nil {
		t.Fatal("missing device filter")
	}
	t.Log("source empty/list/profile shape, ID order, pagination, filter and cursor isolation passed")
	call("POST", "/api/v1/sources", strings.Replace(testSource, `"s1"`, `"validate"`, 1), "reserved", 422)
	manifest, _ := call("GET", "/api/v1/platform", "", "", 200)
	if manifest["capabilities"].(map[string]any)["source_registry"] != "implemented" || manifest["capabilities"].(map[string]any)["source_list"] != "implemented" {
		t.Fatal("source capability scope")
	}
	t.Log("Device and Source create/get, canonical replay, channel/parent conflicts, multi-channel and XR passed")
	stop()
	activeToken = "rotated-device-test-token-1234567890"
	base, stop = start()
	defer stop()
	afterRestart, _ := call("GET", "/api/v1/devices/d1", "", "", 200)
	afterBytes, _ := json.Marshal(afterRestart["device"])
	if !bytes.Equal(original, afterBytes) {
		t.Fatal("device changed after process restart")
	}
	replay, replayHeaders = call("POST", "/api/v1/devices", testDevice, "create-1", 201)
	replayed, _ = json.Marshal(replay["device"])
	if !bytes.Equal(original, replayed) || replayHeaders.Get("Idempotency-Replayed") != "true" {
		t.Fatal("replay lost after restart")
	}
	afterSource, _ := call("GET", "/api/v1/sources/s1", "", "", 200)
	afterSourceBytes, _ := json.Marshal(afterSource["source"])
	if !bytes.Equal(sourceOriginal, afterSourceBytes) {
		t.Fatal("source/profiles changed after process restart")
	}
	sourceReplay, sourceReplayHeaders = call("POST", "/api/v1/sources", testSource, "create-1", 201)
	sourceReplayed, _ = json.Marshal(sourceReplay["source"])
	if !bytes.Equal(sourceOriginal, sourceReplayed) || sourceReplayHeaders.Get("Idempotency-Replayed") != "true" {
		t.Fatal("source replay lost after restart/token rotation")
	}
	afterListRestart, _ := call("GET", "/api/v1/sources?device_id=d1&cursor="+sourcePageCursor, "", "", 200)
	if len(afterListRestart["items"].([]any)) != 1 || afterListRestart["items"].([]any)[0].(map[string]any)["source_id"] != "xr" {
		t.Fatal("source cursor failed after restart/token rotation")
	}
	t.Log("real API process restart and token rotation preserved device, source/profiles and both idempotent responses")
	var checksum string
	if err = admin.QueryRow(ctx, "SELECT checksum FROM camera.schema_migrations WHERE version=2").Scan(&checksum); err != nil {
		t.Fatal(err)
	}
	sql("UPDATE camera.schema_migrations SET checksum=repeat('0',64) WHERE version=2")
	call("GET", "/health/ready", "", "", 503)
	sql(fmt.Sprintf("UPDATE camera.schema_migrations SET checksum='%s' WHERE version=2", checksum))
	ready, _ := call("GET", "/health/ready", "", "", 200)
	if ready["scope"] != "camera_registry" || ready["business_runtime_ready"] != false {
		t.Fatal("readiness scope")
	}
	if !wasm {
		sql("REVOKE INSERT ON camera.device_create_requests FROM " + pgx.Identifier{role}.Sanitize())
		call("POST", "/api/v1/devices", strings.Replace(testDevice, "d1", "failed", 1), "retry-503", 503)
		call("GET", "/api/v1/devices/failed", "", "", 404)
		call("GET", "/health/ready", "", "", 503)
		sql("GRANT INSERT ON camera.device_create_requests TO " + pgx.Identifier{role}.Sanitize())
		call("POST", "/api/v1/devices", strings.Replace(testDevice, "d1", "failed", 1), "retry-503", 201)
		call("GET", "/health/ready", "", "", 200)
		for _, table := range []string{"stream_profiles", "source_create_requests"} {
			sql("REVOKE INSERT ON camera." + table + " FROM " + pgx.Identifier{role}.Sanitize())
			failedSource := strings.NewReplacer(`"s1"`, `"failed-`+table+`"`, `"ch1"`, `"retry-`+table+`"`).Replace(testSource)
			call("POST", "/api/v1/sources", failedSource, "retry-"+table, 503)
			call("GET", "/api/v1/sources/failed-"+table, "", "", 404)
			call("GET", "/health/ready", "", "", 503)
			sql("GRANT INSERT ON camera." + table + " TO " + pgx.Identifier{role}.Sanitize())
			call("POST", "/api/v1/sources", failedSource, "retry-"+table, 201)
			call("GET", "/health/ready", "", "", 200)
		}
		sql("REVOKE SELECT ON camera.stream_profiles FROM " + pgx.Identifier{role}.Sanitize())
		call("GET", "/api/v1/sources", "", "", 503)
		sql("GRANT SELECT ON camera.stream_profiles TO " + pgx.Identifier{role}.Sanitize())
		call("GET", "/api/v1/sources", "", "", 200)
		t.Log("source list permission failure returned 503 and recovered after grant restoration")
		t.Log("device, profile and source response permission failures returned 503, rolled back and recovered on same-key retry")
	}
	// Bulk fixture in this disposable DB tests default/max page bounds.
	sql(`BEGIN;
INSERT INTO camera.video_sources(source_id,device_id,channel_key,display_name,transport,input_mode,motion_mode,primary_profile_id)
SELECT 'list-bulk-'||lpad(n::text,3,'0'),'d3','bulk-'||n,'Bulk','RTSP','PULL','FIXED','main' FROM generate_series(1,51) n;
INSERT INTO camera.stream_profiles(source_id,profile_id,position,codec,width,height,fps)
SELECT 'list-bulk-'||lpad(n::text,3,'0'),'main',1,'H264',1920,1080,30 FROM generate_series(1,51) n;
COMMIT;`)
	defaultPage, _ := call("GET", "/api/v1/sources?device_id=d3", "", "", 200)
	if len(defaultPage["items"].([]any)) != 50 || defaultPage["next_cursor"] == nil {
		t.Fatal("source default page limit")
	}
	defaultLast, _ := call("GET", "/api/v1/sources?device_id=d3&cursor="+url.QueryEscape(defaultPage["next_cursor"].(string)), "", "", 200)
	if len(defaultLast["items"].([]any)) != 1 || defaultLast["next_cursor"] != nil {
		t.Fatal("source default last page")
	}
	maxPage, _ := call("GET", "/api/v1/sources?device_id=d3&limit=200", "", "", 200)
	if len(maxPage["items"].([]any)) != 51 || maxPage["next_cursor"] != nil {
		t.Fatal("source max page limit")
	}
	t.Log("source default 50/max 200 and full final page behavior passed")
	verifyDeviceUpdateHTTP(t, call, sql, func() {
		stop()
		activeToken = "rotated-update-test-token-1234567890"
		base, stop = start()
	}, wasm, role)
	verifySourceUpdateHTTP(t, call, sql, func() {
		stop()
		activeToken = "rotated-source-update-token-1234567890"
		base, stop = start()
	}, wasm, role)
	verifySourceDeleteHTTP(t, call, sql, func() {
		stop()
		activeToken = "rotated-source-delete-token-1234567890"
		base, stop = start()
	}, wasm, role)
	verifyDeviceDeleteHTTP(t, call, sql, func() {
		stop()
		activeToken = "rotated-device-delete-token-1234567890"
		base, stop = start()
	}, wasm, role)
	stop()
}
