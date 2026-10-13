// Package credentialadmission implements local control records and cooperative
// leases. OPEN is an intent, not proof of DB/key readiness. Storage compares
// records under whole-operation leases; operational restore orchestration is separate.
package credentialadmission

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"math"
	"reflect"
	"regexp"
	"strconv"
	"time"
	"unicode/utf8"
)

const MaxBytes = 32768
const MaxSeen = 512

var (
	ErrInvalid     = errors.New("ADMISSION_INVALID")
	ErrConflict    = errors.New("ADMISSION_CONFLICT")
	ErrUnavailable = errors.New("ADMISSION_UNAVAILABLE")
	// A write may have reached rename before an IO failure. Never use the old
	// OPEN or proceed with restore on this error; a fresh lease must inspect it.
	ErrUncertain = errors.New("ADMISSION_COMMIT_UNCERTAIN")
	ErrDeadline  = errors.New("ADMISSION_LEASE_DEADLINE")
)

type State string

const (
	Fenced   State = "FENCED"
	Prepared State = "PREPARED"
	Open     State = "OPEN"
)

type Binding struct {
	DatabaseID             string `json:"database_id"`
	DatabaseName           string `json:"database_name"`
	SchemaVersion          int64  `json:"schema_version"`
	MigrationSetSHA256     string `json:"migration_set_sha256"`
	EndpointProfileSHA256  string `json:"endpoint_profile_sha256"`
	KeyBundleSHA256        string `json:"key_bundle_sha256"`
	ActiveEncryptionKeyID  string `json:"active_encryption_key_id"`
	ActiveIdempotencyKeyID string `json:"active_idempotency_key_id"`
	WriterRole             string `json:"writer_role"`
	BudgetRole             string `json:"budget_role"`
}

type Record struct {
	SchemaVersion        string   `json:"schema_version"`
	DeploymentID         string   `json:"deployment_id"`
	Generation           int64    `json:"generation"`
	OperationID          string   `json:"operation_id"`
	State                State    `json:"state"`
	WrittenAt            string   `json:"written_at"`
	CounterPolicy        string   `json:"counter_policy"`
	SeenEncryptionKeyIDs []string `json:"seen_encryption_key_ids"`
	Binding              *Binding `json:"binding"`
}

var (
	uuid4   = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`)
	hash    = regexp.MustCompile(`^[0-9a-f]{64}$`)
	encID   = regexp.MustCompile(`^enc-[0-9a-f]{16}$`)
	idemID  = regexp.MustCompile(`^idem-[0-9a-f]{16}$`)
	dbName  = regexp.MustCompile(`^[A-Za-z_][A-Za-z0-9_]{0,62}$`)
	utc     = regexp.MustCompile(`^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,9})?Z$`)
	integer = regexp.MustCompile(`^(0|[1-9][0-9]*)$`)
)

func validTime(s string) bool {
	if !utc.MatchString(s) {
		return false
	}
	t, err := time.Parse(time.RFC3339Nano, s)
	return err == nil && t.Year() >= 1
}

func (b Binding) validate() bool {
	return uuid4.MatchString(b.DatabaseID) && dbName.MatchString(b.DatabaseName) && b.SchemaVersion == 9 &&
		hash.MatchString(b.MigrationSetSHA256) && hash.MatchString(b.EndpointProfileSHA256) && hash.MatchString(b.KeyBundleSHA256) &&
		encID.MatchString(b.ActiveEncryptionKeyID) && idemID.MatchString(b.ActiveIdempotencyKeyID) &&
		b.WriterRole == "camera_credential_writer" && b.BudgetRole == "camera_credential_budget"
}

func Validate(r Record) error {
	if r.SchemaVersion != "v1" || !uuid4.MatchString(r.DeploymentID) || !uuid4.MatchString(r.OperationID) || r.Generation < 1 ||
		!validTime(r.WrittenAt) || r.CounterPolicy != "new-key-after-fence-v1" || r.SeenEncryptionKeyIDs == nil || len(r.SeenEncryptionKeyIDs) > MaxSeen {
		return ErrInvalid
	}
	if r.State != Fenced && r.State != Prepared && r.State != Open {
		return ErrInvalid
	}
	seen := make(map[string]bool, len(r.SeenEncryptionKeyIDs))
	for _, id := range r.SeenEncryptionKeyIDs {
		if !encID.MatchString(id) || seen[id] {
			return ErrInvalid
		}
		seen[id] = true
	}
	if r.Binding == nil {
		if r.State != Fenced {
			return ErrInvalid
		}
	} else if !r.Binding.validate() || !seen[r.Binding.ActiveEncryptionKeyID] {
		return ErrInvalid
	}
	return nil
}

// Scan the raw token stream before decoding: encoding/json otherwise accepts
// duplicate fields, escaped field aliases and 1.0 into schema integer values.
func scan(d *json.Decoder, raw []byte, depth int) error {
	if depth > 4 {
		return ErrInvalid
	}
	token, err := d.Token()
	if err != nil {
		return ErrInvalid
	}
	if delim, ok := token.(json.Delim); ok {
		switch delim {
		case '{':
			seen := map[string]bool{}
			for d.More() {
				start := d.InputOffset()
				key, err := d.Token()
				name, ok := key.(string)
				if err != nil || !ok || seen[name] || bytes.Contains(raw[start:d.InputOffset()], []byte{'\\'}) {
					return ErrInvalid
				}
				seen[name] = true
				if err := scan(d, raw, depth+1); err != nil {
					return err
				}
			}
			end, err := d.Token()
			if err != nil || end != json.Delim('}') {
				return ErrInvalid
			}
		case '[':
			for d.More() {
				if err := scan(d, raw, depth+1); err != nil {
					return err
				}
			}
			end, err := d.Token()
			if err != nil || end != json.Delim(']') {
				return ErrInvalid
			}
		default:
			return ErrInvalid
		}
	} else if n, ok := token.(json.Number); ok {
		if !integer.MatchString(string(n)) {
			return ErrInvalid
		}
		if _, err := strconv.ParseInt(string(n), 10, 64); err != nil {
			return ErrInvalid
		}
	}
	return nil
}

func exactFields(raw json.RawMessage, names ...string) bool {
	var obj map[string]json.RawMessage
	if json.Unmarshal(raw, &obj) != nil || len(obj) != len(names) {
		return false
	}
	for _, n := range names {
		if _, ok := obj[n]; !ok {
			return false
		}
	}
	return true
}

func Parse(raw []byte) (Record, error) {
	var r Record
	if len(raw) == 0 || len(raw) > MaxBytes || !utf8.Valid(raw) {
		return r, ErrInvalid
	}
	d := json.NewDecoder(bytes.NewReader(raw))
	d.UseNumber()
	if scan(d, raw, 0) != nil {
		return r, ErrInvalid
	}
	if _, err := d.Token(); err != io.EOF {
		return r, ErrInvalid
	}
	if !exactFields(raw, "schema_version", "deployment_id", "generation", "operation_id", "state", "written_at", "counter_policy", "seen_encryption_key_ids", "binding") {
		return r, ErrInvalid
	}
	var obj map[string]json.RawMessage
	if json.Unmarshal(raw, &obj) != nil {
		return r, ErrInvalid
	}
	if !bytes.Equal(bytes.TrimSpace(obj["binding"]), []byte("null")) && !exactFields(obj["binding"], "database_id", "database_name", "schema_version", "migration_set_sha256", "endpoint_profile_sha256", "key_bundle_sha256", "active_encryption_key_id", "active_idempotency_key_id", "writer_role", "budget_role") {
		return r, ErrInvalid
	}
	d = json.NewDecoder(bytes.NewReader(raw))
	d.DisallowUnknownFields()
	if d.Decode(&r) != nil || Validate(r) != nil {
		return Record{}, ErrInvalid
	}
	return r, nil
}

func Encode(r Record) ([]byte, error) {
	if err := Validate(r); err != nil {
		return nil, err
	}
	b, err := json.Marshal(r)
	if err != nil || len(b)+1 > MaxBytes {
		return nil, ErrInvalid
	}
	return append(b, '\n'), nil
}

func clone(r Record) Record {
	r.SeenEncryptionKeyIDs = append([]string{}, r.SeenEncryptionKeyIDs...)
	if r.Binding != nil {
		b := *r.Binding
		r.Binding = &b
	}
	return r
}

// NewFenced is only for explicit first-deployment bootstrap. The caller must
// independently establish no credential history/budget use/prior authority.
func NewFenced(deploymentID, operationID, writtenAt string) (Record, error) {
	r := Record{"v1", deploymentID, 1, operationID, Fenced, writtenAt, "new-key-after-fence-v1", []string{}, nil}
	return r, Validate(r)
}

func NextFence(current Record, operationID, writtenAt string) (Record, error) {
	if Validate(current) != nil || !uuid4.MatchString(operationID) || operationID == current.OperationID || !validTime(writtenAt) || current.Generation == math.MaxInt64 {
		return Record{}, ErrConflict
	}
	next := clone(current)
	next.Generation++
	next.OperationID = operationID
	next.State = Fenced
	next.WrittenAt = writtenAt
	return next, nil
}

func NextPrepare(current Record, binding Binding, writtenAt string) (Record, error) {
	if Validate(current) != nil || !binding.validate() || !validTime(writtenAt) {
		return Record{}, ErrConflict
	}
	if current.State == Prepared && *current.Binding == binding {
		return clone(current), nil
	}
	if current.State != Fenced || len(current.SeenEncryptionKeyIDs) == MaxSeen {
		return Record{}, ErrConflict
	}
	for _, id := range current.SeenEncryptionKeyIDs {
		if id == binding.ActiveEncryptionKeyID {
			return Record{}, ErrConflict
		}
	}
	if current.Binding != nil && current.Binding.DatabaseID == binding.DatabaseID {
		return Record{}, ErrConflict
	}
	next := clone(current)
	next.State = Prepared
	next.WrittenAt = writtenAt
	next.Binding = &binding
	next.SeenEncryptionKeyIDs = append(next.SeenEncryptionKeyIDs, binding.ActiveEncryptionKeyID)
	return next, nil
}

func NextOpen(current Record, writtenAt string) (Record, error) {
	if Validate(current) != nil || current.Generation == math.MaxInt64 || len(current.SeenEncryptionKeyIDs) == MaxSeen || !validTime(writtenAt) || (current.State != Prepared && current.State != Open) {
		return Record{}, ErrConflict
	}
	if current.State == Open {
		return clone(current), nil
	}
	next := clone(current)
	next.State = Open
	next.WrittenAt = writtenAt
	return next, nil
}

func allowed(current, next Record) bool {
	if Validate(current) != nil || Validate(next) != nil {
		return false
	}
	if reflect.DeepEqual(current, next) {
		return true
	}
	var expected Record
	var err error
	switch {
	case next.State == Fenced:
		expected, err = NextFence(current, next.OperationID, next.WrittenAt)
	case next.State == Prepared && next.Binding != nil:
		expected, err = NextPrepare(current, *next.Binding, next.WrittenAt)
	case next.State == Open:
		expected, err = NextOpen(current, next.WrittenAt)
	default:
		return false
	}
	return err == nil && reflect.DeepEqual(expected, next)
}
