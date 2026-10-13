package credentialadmission

import (
	"bytes"
	"encoding/json"
	"fmt"
	"math"
	"os"
	"reflect"
	"strings"
	"testing"
)

const deployment = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
const operation = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
const nextOperation = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
const timestamp = "2026-10-02T06:00:00Z"

func initial(t *testing.T) Record {
	t.Helper()
	r, err := NewFenced(deployment, operation, timestamp)
	if err != nil {
		t.Fatal(err)
	}
	return r
}

func candidate() Binding {
	return Binding{"dddddddd-dddd-4ddd-8ddd-dddddddddddd", "camera", 9, strings.Repeat("a", 64), strings.Repeat("b", 64), strings.Repeat("c", 64), "enc-1111111111111111", "idem-2222222222222222", "camera_credential_writer", "camera_credential_budget"}
}

func openRecord(t *testing.T) Record {
	t.Helper()
	p, err := NextPrepare(initial(t), candidate(), timestamp)
	if err != nil {
		t.Fatal(err)
	}
	r, err := NextOpen(p, timestamp)
	if err != nil {
		t.Fatal(err)
	}
	return r
}

func TestParseContractExamples(t *testing.T) {
	data, err := os.ReadFile("../../api/planned/credential-admission.examples.json")
	if err != nil {
		t.Fatal(err)
	}
	var document map[string]json.RawMessage
	if json.Unmarshal(data, &document) != nil {
		t.Fatal("examples")
	}
	// The examples are lists of named envelopes, not runtime input.
	var walk func(json.RawMessage)
	count := 0
	walk = func(raw json.RawMessage) {
		var obj map[string]json.RawMessage
		if json.Unmarshal(raw, &obj) == nil && obj != nil {
			if _, ok := obj["deployment_id"]; ok {
				var shape Record
				if json.Unmarshal(raw, &shape) != nil {
					t.Fatal("shape")
				}
				r, err := Parse(raw)
				if shape.Binding != nil {
					found := false
					for _, id := range shape.SeenEncryptionKeyIDs {
						if id == shape.Binding.ActiveEncryptionKeyID {
							found = true
						}
					}
					if !found {
						if err != ErrInvalid {
							t.Fatal("missing membership accepted")
						}
						return
					}
				}
				if err != nil {
					t.Fatal(err)
				}
				encoded, err := Encode(r)
				if err != nil {
					t.Fatal(err)
				}
				again, err := Parse(encoded)
				if err != nil || !reflect.DeepEqual(r, again) {
					t.Fatal("round trip")
				}
				count++
				return
			}
			for _, child := range obj {
				walk(child)
			}
			return
		}
		var list []json.RawMessage
		if json.Unmarshal(raw, &list) == nil {
			for _, child := range list {
				walk(child)
			}
		}
	}
	walk(data)
	if count < 6 {
		t.Fatalf("only %d contract records", count)
	}
}

func TestStrictRawParser(t *testing.T) {
	raw, _ := Encode(openRecord(t))
	base := string(raw)
	cases := map[string]string{
		"duplicate":        strings.Replace(base, `"generation":1`, `"generation":1,"generation":1`, 1),
		"escaped alias":    strings.Replace(base, `"generation":1`, `"gener\u0061tion":1`, 1),
		"nested duplicate": strings.Replace(base, `"schema_version":9`, `"schema_version":9,"schema_version":9`, 1),
		"nested alias":     strings.Replace(base, `"database_id"`, `"database\u005fid"`, 1),
		"decimal":          strings.Replace(base, `"generation":1`, `"generation":1.0`, 1),
		"exponent":         strings.Replace(base, `"generation":1`, `"generation":1e0`, 1),
		"nested decimal":   strings.Replace(base, `"schema_version":9`, `"schema_version":9.0`, 1),
		"bool":             strings.Replace(base, `"generation":1`, `"generation":true`, 1),
		"negative":         strings.Replace(base, `"generation":1`, `"generation":-1`, 1),
		"zero":             strings.Replace(base, `"generation":1`, `"generation":0`, 1),
		"overflow":         strings.Replace(base, `"generation":1`, `"generation":9223372036854775808`, 1),
		"trailing":         base + `{}`,
		"unknown":          strings.Replace(base, `"generation":1`, `"generation":1,"force":true`, 1),
		"nested unknown":   strings.Replace(base, `"schema_version":9`, `"schema_version":9,"password":"private"`, 1),
		"missing binding":  strings.Replace(base, `,"binding":`+base[strings.Index(base, `"binding":`)+10:len(base)-2], ``, 1),
		"null list":        strings.Replace(base, `["enc-1111111111111111"]`, `null`, 1),
		"invalid UTF8":     base + string([]byte{255}),
		"over bound":       strings.Repeat(" ", MaxBytes) + base,
		"array root":       `[]`, "empty": "", "depth": `{"x":{"x":{"x":{"x":{"x":1}}}}}`,
	}
	for name, input := range cases {
		t.Run(name, func(t *testing.T) {
			if _, err := Parse([]byte(input)); err != ErrInvalid {
				t.Fatalf("accepted: %v", err)
			}
		})
	}
	var fields map[string]json.RawMessage
	json.Unmarshal(raw, &fields)
	for key := range fields {
		t.Run("missing "+key, func(t *testing.T) {
			copyFields := map[string]json.RawMessage{}
			for k, v := range fields {
				if k != key {
					copyFields[k] = v
				}
			}
			b, _ := json.Marshal(copyFields)
			if _, err := Parse(b); err != ErrInvalid {
				t.Fatal("accepted")
			}
		})
	}
}

func TestSemanticRecordValidation(t *testing.T) {
	cases := map[string]func(*Record){
		"deployment":         func(r *Record) { r.DeploymentID = strings.ToUpper(deployment) },
		"UUID version":       func(r *Record) { r.OperationID = strings.Replace(operation, "4bbb", "3bbb", 1) },
		"UTC":                func(r *Record) { r.WrittenAt = "2026-02-30T00:00:00Z" },
		"year zero":          func(r *Record) { r.WrittenAt = "0000-01-01T00:00:00Z" },
		"fraction":           func(r *Record) { r.WrittenAt = "2026-10-02T00:00:00.1234567890Z" },
		"zone":               func(r *Record) { r.WrittenAt = "2026-10-02T00:00:00+00:00" },
		"nil":                func(r *Record) { r.Binding = nil },
		"duplicate ID":       func(r *Record) { r.SeenEncryptionKeyIDs = append(r.SeenEncryptionKeyIDs, r.SeenEncryptionKeyIDs[0]) },
		"missing membership": func(r *Record) { r.Binding.ActiveEncryptionKeyID = "enc-3333333333333333" },
		"database":           func(r *Record) { r.Binding.DatabaseName = "other/db" },
		"hash":               func(r *Record) { r.Binding.KeyBundleSHA256 = strings.Repeat("C", 64) },
		"role":               func(r *Record) { r.Binding.WriterRole = "camera_registry" },
		"schema":             func(r *Record) { r.Binding.SchemaVersion = 8 },
		"policy":             func(r *Record) { r.CounterPolicy = "reset" },
		"state":              func(r *Record) { r.State = "READY" },
	}
	for name, change := range cases {
		t.Run(name, func(t *testing.T) {
			r := openRecord(t)
			change(&r)
			if Validate(r) != ErrInvalid {
				t.Fatal("accepted")
			}
		})
	}
	r := openRecord(t)
	r.Generation = math.MaxInt64
	r.WrittenAt = "2026-10-02T00:00:00.123456789Z"
	if Validate(r) != nil {
		t.Fatal("valid boundary")
	}
	r.SeenEncryptionKeyIDs = []string{}
	for i := 0; i < MaxSeen; i++ {
		r.SeenEncryptionKeyIDs = append(r.SeenEncryptionKeyIDs, fmt.Sprintf("enc-%016x", i))
	}
	r.Binding.ActiveEncryptionKeyID = r.SeenEncryptionKeyIDs[0]
	if Validate(r) != nil {
		t.Fatal("512 IDs")
	}
	r.SeenEncryptionKeyIDs = append(r.SeenEncryptionKeyIDs, "enc-ffffffffffffffff")
	if Validate(r) != ErrInvalid {
		t.Fatal("513 accepted")
	}
}

func TestMonotonicTransitionsAndRetry(t *testing.T) {
	r := initial(t)
	b := candidate()
	p, err := NextPrepare(r, b, timestamp)
	if err != nil || !allowed(r, p) {
		t.Fatal(err)
	}
	retry, err := NextPrepare(p, b, "2026-10-02T05:00:00Z")
	if err != nil || !reflect.DeepEqual(retry, p) {
		t.Fatal("retry changed candidate")
	}
	changed := b
	changed.KeyBundleSHA256 = strings.Repeat("d", 64)
	if _, err := NextPrepare(p, changed, timestamp); err != ErrConflict {
		t.Fatal("candidate replaced")
	}
	o, err := NextOpen(p, timestamp)
	if err != nil || !allowed(p, o) {
		t.Fatal(err)
	}
	if _, err := NextOpen(r, timestamp); err != ErrConflict {
		t.Fatal("fence bypass")
	}
	retry, err = NextOpen(o, "2026-10-02T05:00:00Z")
	if err != nil || !reflect.DeepEqual(retry, o) {
		t.Fatal("OPEN retry changed")
	}
	f, err := NextFence(o, nextOperation, timestamp)
	if err != nil || !allowed(o, f) || f.Generation != 2 || f.Binding == nil {
		t.Fatal("fence")
	}
	if _, err := NextPrepare(f, b, timestamp); err != ErrConflict {
		t.Fatal("old ID reused")
	}
	fresh := b
	fresh.ActiveEncryptionKeyID = "enc-3333333333333333"
	if _, err := NextPrepare(f, fresh, timestamp); err != ErrConflict {
		t.Fatal("old DB incarnation reused")
	}
	fresh.DatabaseID = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
	next, err := NextPrepare(f, fresh, timestamp)
	if err != nil || !allowed(f, next) || len(next.SeenEncryptionKeyIDs) != 2 {
		t.Fatal(err)
	}
	// Inputs and returned records never share a mutable slice or binding.
	next.SeenEncryptionKeyIDs[0] = "enc-9999999999999999"
	next.Binding.DatabaseName = "changed"
	if f.SeenEncryptionKeyIDs[0] != b.ActiveEncryptionKeyID || f.Binding.DatabaseName != b.DatabaseName {
		t.Fatal("mutated source")
	}
}

func TestCASRejectsHistoryGenerationAndOperationEdits(t *testing.T) {
	o := openRecord(t)
	f, _ := NextFence(o, nextOperation, timestamp)
	for name, change := range map[string]func(*Record){
		"skip": func(r *Record) { r.Generation++ }, "rollback": func(r *Record) { r.Generation = 1 },
		"deployment": func(r *Record) { r.DeploymentID = nextOperation }, "same operation": func(r *Record) { r.OperationID = o.OperationID },
		"drop history":      func(r *Record) { r.SeenEncryptionKeyIDs = []string{}; r.Binding = nil },
		"replace history":   func(r *Record) { r.SeenEncryptionKeyIDs = []string{"enc-9999999999999999"}; r.Binding = nil },
		"different context": func(r *Record) { r.Binding.DatabaseName = "other" },
	} {
		t.Run(name, func(t *testing.T) {
			next := clone(f)
			change(&next)
			if allowed(o, next) {
				t.Fatal("accepted")
			}
		})
	}
	o.Generation = math.MaxInt64
	if _, err := NextFence(o, nextOperation, timestamp); err != ErrConflict {
		t.Fatal("overflow")
	}
	if _, err := NextOpen(o, timestamp); err != ErrConflict {
		t.Fatal("maximum generation opened")
	}
	o = openRecord(t)
	o.State = Prepared
	o.SeenEncryptionKeyIDs = []string{}
	for i := 0; i < MaxSeen; i++ {
		o.SeenEncryptionKeyIDs = append(o.SeenEncryptionKeyIDs, fmt.Sprintf("enc-%016x", i))
	}
	o.Binding.ActiveEncryptionKeyID = o.SeenEncryptionKeyIDs[0]
	if _, err := NextOpen(o, timestamp); err != ErrConflict {
		t.Fatal("maximum history opened")
	}
	if _, err := NextFence(openRecord(t), operation, timestamp); err != ErrConflict {
		t.Fatal("same operation")
	}
}

func TestNoPrivateValuesInErrors(t *testing.T) {
	private := []byte(`{"password":"PRIVATE_SENTINEL","path":"/private/file"}`)
	_, err := Parse(private)
	if err != ErrInvalid || bytes.Contains([]byte(err.Error()), []byte("PRIVATE")) {
		t.Fatal(err)
	}
	for _, err := range []error{ErrInvalid, ErrConflict, ErrUnavailable, ErrUncertain, ErrDeadline} {
		if strings.Contains(err.Error(), "/") {
			t.Fatal("path")
		}
	}
}
