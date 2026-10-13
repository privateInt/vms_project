package storage

import (
	"context"
	"crypto/sha256"
	"encoding/binary"
	"encoding/json"
	"errors"
	"math"
	"strconv"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"vms.local/platform/camera/internal/credentialcrypto"
)

// CredentialStore is private camera storage. It exposes no plaintext resolve or
// network API. Budget and data pools MUST be distinct connections to the same DB.
type CredentialStore struct {
	data, budget *Store
	keys         *credentialcrypto.Keyring
	admission    credentialOperationGuard
}

func (c CredentialStore) String() string               { return "storage.CredentialStore([redacted])" }
func (c CredentialStore) GoString() string             { return c.String() }
func (c CredentialStore) MarshalJSON() ([]byte, error) { return nil, credentialcrypto.ErrDisclosure }

// NewCredentialStore builds an inspection-only foundation. Business methods
// require NewAdmittedCredentialStore; a missing operation guard always denies IO.
func NewCredentialStore(data, budget *Store, keys *credentialcrypto.Keyring) (*CredentialStore, error) {
	if data == nil || budget == nil || data.pool == nil || budget.pool == nil || data.pool == budget.pool || keys == nil || keys.ActiveEncryptionID() == "" || keys.ActiveIdempotencyID() == "" {
		return nil, failure("CREDENTIAL_STORE_CONFIG_INVALID", nil)
	}
	a, b := data.pool.Config().ConnConfig, budget.pool.Config().ConnConfig
	if a.Host != b.Host || a.Port != b.Port || a.Database != b.Database {
		return nil, failure("CREDENTIAL_STORE_CONFIG_INVALID", nil)
	}
	// Multiple server targets need a separate cluster/restore admission design.
	for _, connection := range []*pgx.ConnConfig{a, b} {
		for _, fallback := range connection.Fallbacks {
			if fallback.Host != connection.Host || fallback.Port != connection.Port {
				return nil, failure("CREDENTIAL_STORE_CONFIG_INVALID", nil)
			}
		}
	}
	return &CredentialStore{data: data, budget: budget, keys: keys}, nil
}
func stateCode(err error) string {
	var pg *pgconn.PgError
	if errors.As(err, &pg) {
		return pg.Code
	}
	return ""
}

func credentialRequestScope(i CredentialIdentity, r CredentialReference, method string) credentialcrypto.RequestScope {
	path := "/api/v1/credentials/" + r.CredentialID + "/versions"
	if method == "DELETE" {
		path += "/" + strconv.FormatInt(r.Version, 10)
	}
	return credentialcrypto.RequestScope{PrincipalID: i.PrincipalID, Method: method, Path: path, IdempotencyKeySHA256: hashText([]byte(i.IdempotencyKey))}
}
func credentialRequestLock(ctx context.Context, tx pgx.Tx, i CredentialIdentity, scope credentialcrypto.RequestScope) error {
	b, _ := json.Marshal(struct {
		Scope   string
		Request credentialcrypto.RequestScope
	}{i.ScopeID, scope})
	sum := sha256.Sum256(b)
	_, err := tx.Exec(ctx, "SELECT pg_advisory_xact_lock($1)", int64(binary.BigEndian.Uint64(sum[:8])))
	if err != nil {
		return failure("CREDENTIAL_STORE_UNAVAILABLE", err)
	}
	return nil
}
func credentialDeviceLock(ctx context.Context, tx pgx.Tx, id string) error {
	_, err := tx.Exec(ctx, "SELECT pg_advisory_xact_lock(1447908164,hashtext($1))", id)
	if err != nil {
		return failure("CREDENTIAL_STORE_UNAVAILABLE", err)
	}
	var active bool
	if err = tx.QueryRow(ctx, "SELECT EXISTS(SELECT 1 FROM camera.devices WHERE device_id=$1 AND deleted_at IS NULL)", id).Scan(&active); err != nil {
		return failure("CREDENTIAL_STORE_UNAVAILABLE", err)
	}
	if !active {
		return failure("DEVICE_UNAVAILABLE", nil)
	}
	return nil
}
func scanCredentialMetadata(row pgx.Row) (CredentialMetadata, error) {
	var m CredentialMetadata
	err := row.Scan(&m.CredentialID, &m.DeviceID, &m.Version, &m.CreatedAt, &m.RevokedAt)
	if err != nil {
		return CredentialMetadata{}, err
	}
	m.CreatedAt = m.CreatedAt.UTC()
	if m.RevokedAt != nil {
		at := m.RevokedAt.UTC()
		m.RevokedAt = &at
	}
	return m, nil
}

func (c *CredentialStore) replay(ctx context.Context, tx pgx.Tx, i CredentialIdentity, scope credentialcrypto.RequestScope, canonical []byte) (CredentialMetadata, bool, error) {
	var f credentialcrypto.Fingerprint
	var m CredentialMetadata
	err := tx.QueryRow(ctx, `SELECT fingerprint_format,fingerprint_algorithm,fingerprint_key_id,fingerprint_digest,
credential_id,device_id,version,version_created_at,revoked_at FROM camera.credential_requests
WHERE scope_id=$1 AND principal=$2 AND method=$3 AND path=$4 AND key_hash=$5`, i.ScopeID, scope.PrincipalID, scope.Method, scope.Path, scope.IdempotencyKeySHA256).
		Scan(&f.FormatVersion, &f.Algorithm, &f.KeyID, &f.Digest, &m.CredentialID, &m.DeviceID, &m.Version, &m.CreatedAt, &m.RevokedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return CredentialMetadata{}, false, nil
	}
	if err != nil {
		return CredentialMetadata{}, false, failure("CREDENTIAL_STORE_UNAVAILABLE", err)
	}
	matched, err := c.keys.Match(scope, canonical, f)
	if err != nil {
		return CredentialMetadata{}, false, failure("CREDENTIAL_KEY_UNAVAILABLE", nil)
	}
	if !matched {
		return CredentialMetadata{}, false, failure("IDEMPOTENCY_CONFLICT", nil)
	}
	if !contractsCredentialMetadata(m) {
		return CredentialMetadata{}, false, failure("CREDENTIAL_STORE_UNAVAILABLE", nil)
	}
	m.CreatedAt = m.CreatedAt.UTC()
	if m.RevokedAt != nil {
		at := m.RevokedAt.UTC()
		m.RevokedAt = &at
	}
	return m, true, nil
}
func contractsCredentialMetadata(m CredentialMetadata) bool {
	return (CredentialReference{m.CredentialID, m.DeviceID, m.Version}).valid() && !m.CreatedAt.IsZero() && (m.RevokedAt == nil || !m.RevokedAt.Before(m.CreatedAt))
}
func (c *CredentialStore) journal(ctx context.Context, tx pgx.Tx, i CredentialIdentity, scope credentialcrypto.RequestScope, canonical []byte, m CredentialMetadata) error {
	f, err := c.keys.Fingerprint(scope, canonical)
	if err != nil {
		return failure("CREDENTIAL_KEY_UNAVAILABLE", nil)
	}
	_, err = tx.Exec(ctx, `INSERT INTO camera.credential_requests(scope_id,principal,method,path,key_hash,
fingerprint_format,fingerprint_algorithm,fingerprint_key_id,fingerprint_digest,credential_id,device_id,version,version_created_at,revoked_at)
VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)`, i.ScopeID, scope.PrincipalID, scope.Method, scope.Path, scope.IdempotencyKeySHA256,
		f.FormatVersion, f.Algorithm, f.KeyID, f.Digest, m.CredentialID, m.DeviceID, m.Version, m.CreatedAt, m.RevokedAt)
	if err != nil {
		return failure("CREDENTIAL_STORE_UNAVAILABLE", err)
	}
	return nil
}

func credentialWriteHead(ctx context.Context, tx pgx.Tx, i CredentialIdentity, w CredentialWrite) (int64, error) {
	if err := credentialDeviceLock(ctx, tx, w.DeviceID); err != nil {
		return 0, err
	}
	var storedScope, device string
	var head int64
	err := tx.QueryRow(ctx, "SELECT scope_id,device_id,head_version FROM camera.credentials WHERE credential_id=$1 FOR UPDATE", w.CredentialID).Scan(&storedScope, &device, &head)
	if errors.Is(err, pgx.ErrNoRows) {
		if w.ExpectedVersion == 0 {
			return 0, nil
		}
		return 0, failure("CREDENTIAL_UNAVAILABLE", nil)
	}
	if err != nil {
		return 0, failure("CREDENTIAL_STORE_UNAVAILABLE", err)
	}
	if storedScope != i.ScopeID || device != w.DeviceID {
		return 0, failure("CREDENTIAL_UNAVAILABLE", nil)
	}
	if w.ExpectedVersion == 0 {
		return 0, failure("CREDENTIAL_EXISTS", nil)
	}
	if head != w.ExpectedVersion {
		return 0, failure("CREDENTIAL_VERSION_CONFLICT", nil)
	}
	if head == math.MaxInt64 {
		return 0, failure("CREDENTIAL_VERSION_EXHAUSTED", nil)
	}
	return head, nil
}

// WriteVersion creates version 1 or appends an immutable exact version after
// checking the head. Raw private DTO bytes are never archived. A failed mutation
// rolls back data/journal while its separately committed encryption use remains.
func (c *CredentialStore) WriteVersion(ctx context.Context, i CredentialIdentity, w CredentialWrite, authorize CredentialAuthorizer) (CredentialMetadata, bool, error) {
	if !i.valid(true) || !w.valid() {
		return CredentialMetadata{}, false, failure("CONTRACT_INVALID", nil)
	}
	lease, err := c.beginCredentialOperation(ctx)
	if err != nil {
		return CredentialMetadata{}, false, err
	}
	defer lease.Close()
	r := CredentialReference{w.CredentialID, w.DeviceID, w.ExpectedVersion}
	scope := credentialRequestScope(i, r, "POST")
	canonical := canonicalCredentialWrite(i, w)
	defer clear(canonical)
	var result CredentialMetadata
	replayed := false
	err = c.withCredentialTx(ctx, lease, c.data, "camera_credential_writer", func(tx pgx.Tx) error {
		if err := authorizeCredential(ctx, tx, authorize, accessFor(i, r, "MANAGE")); err != nil {
			return err
		}
		if err := credentialRequestLock(ctx, tx, i, scope); err != nil {
			return err
		}
		previous, ok, err := c.replay(ctx, tx, i, scope, canonical)
		if err != nil {
			return err
		}
		if ok {
			if previous.CredentialID != w.CredentialID || previous.DeviceID != w.DeviceID || w.ExpectedVersion == math.MaxInt64 || previous.Version != w.ExpectedVersion+1 || previous.RevokedAt != nil {
				return failure("CREDENTIAL_STORE_UNAVAILABLE", nil)
			}
			result = previous
			replayed = true
			return nil
		}
		_, err = credentialWriteHead(ctx, tx, i, w)
		return err
	})
	if err != nil {
		return CredentialMetadata{}, false, err
	}
	if replayed {
		if err = lease.Check(ctx); err != nil {
			return CredentialMetadata{}, false, err
		}
		return result, true, nil
	}
	// Commit the budget before opening the mutation transaction. The same external
	// lease spans both commits. Contention may burn an unused reservation, never reuse it.
	reservation, err := c.reserveCredentialUse(ctx, lease)
	if err != nil {
		return CredentialMetadata{}, false, err
	}
	err = c.withCredentialTx(ctx, lease, c.data, "camera_credential_writer", func(tx pgx.Tx) error {
		if err := authorizeCredential(ctx, tx, authorize, accessFor(i, r, "MANAGE")); err != nil {
			return err
		}
		if err := credentialRequestLock(ctx, tx, i, scope); err != nil {
			return err
		}
		previous, ok, err := c.replay(ctx, tx, i, scope, canonical)
		if err != nil {
			return err
		}
		if ok {
			if previous.CredentialID != w.CredentialID || previous.DeviceID != w.DeviceID || w.ExpectedVersion == math.MaxInt64 || previous.Version != w.ExpectedVersion+1 || previous.RevokedAt != nil {
				return failure("CREDENTIAL_STORE_UNAVAILABLE", nil)
			}
			result = previous
			replayed = true
			return nil
		}
		head, err := credentialWriteHead(ctx, tx, i, w)
		if err != nil {
			return err
		}
		if head == 0 {
			if _, err = tx.Exec(ctx, "INSERT INTO camera.credentials(credential_id,scope_id,device_id,head_version) VALUES ($1,$2,$3,1)", w.CredentialID, i.ScopeID, w.DeviceID); err != nil {
				if stateCode(err) == "23505" {
					return failure("CREDENTIAL_UNAVAILABLE", nil)
				}
				return failure("CREDENTIAL_STORE_UNAVAILABLE", err)
			}
		}
		version := head + 1
		cryptoContext := credentialcrypto.Context{ScopeID: i.ScopeID, DeviceID: w.DeviceID, CredentialID: w.CredentialID, CredentialVersion: version, TargetPolicySHA256: w.Target.digest()}
		envelope, err := c.keys.Seal(cryptoContext, w.Secret, reservation)
		if err != nil {
			return failure("CREDENTIAL_ENCRYPTION_FAILED", nil)
		}
		if _, err = tx.Exec(ctx, `INSERT INTO camera.credential_versions(credential_id,version,protocol,host,port,target_policy_sha256,
encryption_format,encryption_algorithm,encryption_key_id,encryption_use,ciphertext) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)`,
			w.CredentialID, version, w.Target.Protocol, w.Target.Host, w.Target.Port, w.Target.digest(), envelope.FormatVersion, envelope.Algorithm, envelope.KeyID, int64(envelope.EncryptionUse), envelope.Ciphertext); err != nil {
			return failure("CREDENTIAL_STORE_UNAVAILABLE", err)
		}
		if head > 0 {
			if _, err = tx.Exec(ctx, "UPDATE camera.credentials SET head_version=$2,updated_at=GREATEST(clock_timestamp(),updated_at) WHERE credential_id=$1", w.CredentialID, version); err != nil {
				return failure("CREDENTIAL_STORE_UNAVAILABLE", err)
			}
		}
		result, err = scanCredentialMetadata(tx.QueryRow(ctx, `SELECT c.credential_id,c.device_id,v.version,v.created_at,v.revoked_at
FROM camera.credentials c JOIN camera.credential_versions v USING (credential_id) WHERE c.credential_id=$1 AND v.version=$2`, w.CredentialID, version))
		if err != nil {
			return failure("CREDENTIAL_STORE_UNAVAILABLE", err)
		}
		return c.journal(ctx, tx, i, scope, canonical, result)
	})
	if err != nil {
		return CredentialMetadata{}, false, err
	}
	if err = lease.Check(ctx); err != nil {
		return CredentialMetadata{}, false, err
	}
	return result, replayed, nil
}

// CheckReference supplies only safe metadata for a fixed, active local version
// and exact target. It does not decrypt, authorize a dial or reserve session use.
func (c *CredentialStore) CheckReference(ctx context.Context, i CredentialIdentity, r CredentialReference, target CredentialTarget, authorize CredentialAuthorizer) (CredentialMetadata, error) {
	if !i.valid(false) || !r.valid() || !target.valid() {
		return CredentialMetadata{}, failure("CONTRACT_INVALID", nil)
	}
	lease, err := c.beginCredentialOperation(ctx)
	if err != nil {
		return CredentialMetadata{}, err
	}
	defer lease.Close()
	var result CredentialMetadata
	err = c.withCredentialTx(ctx, lease, c.data, "camera_credential_writer", func(tx pgx.Tx) error {
		if err := authorizeCredential(ctx, tx, authorize, accessFor(i, r, "REFERENCE")); err != nil {
			return err
		}
		if err := credentialDeviceLock(ctx, tx, r.DeviceID); err != nil {
			return err
		}
		var err error
		result, err = scanCredentialMetadata(tx.QueryRow(ctx, `SELECT c.credential_id,c.device_id,v.version,v.created_at,v.revoked_at
FROM camera.credentials c JOIN camera.credential_versions v USING (credential_id)
WHERE c.scope_id=$1 AND c.device_id=$2 AND c.credential_id=$3 AND v.version=$4 AND v.revoked_at IS NULL
AND v.protocol=$5 AND v.host=$6 AND v.port=$7 AND v.target_policy_sha256=$8`,
			i.ScopeID, r.DeviceID, r.CredentialID, r.Version, target.Protocol, target.Host, target.Port, target.digest()))
		if errors.Is(err, pgx.ErrNoRows) {
			return failure("CREDENTIAL_UNAVAILABLE", nil)
		}
		if err != nil {
			return failure("CREDENTIAL_STORE_UNAVAILABLE", err)
		}
		return nil
	})
	if err != nil {
		return CredentialMetadata{}, err
	}
	if err = lease.Check(ctx); err != nil {
		return CredentialMetadata{}, err
	}
	return result, nil
}

// RevokeVersion retains ciphertext/history, after a trusted reference/usage
// guard proves release under the same device -> credential lock admission.
func (c *CredentialStore) RevokeVersion(ctx context.Context, i CredentialIdentity, r CredentialReference, authorize CredentialAuthorizer, guard CredentialRevokeGuard) (CredentialMetadata, bool, error) {
	if !i.valid(true) || !r.valid() {
		return CredentialMetadata{}, false, failure("CONTRACT_INVALID", nil)
	}
	lease, err := c.beginCredentialOperation(ctx)
	if err != nil {
		return CredentialMetadata{}, false, err
	}
	defer lease.Close()
	scope := credentialRequestScope(i, r, "DELETE")
	canonical, _ := json.Marshal(struct {
		ScopeID   string
		Reference CredentialReference
	}{i.ScopeID, r})
	defer clear(canonical)
	var result CredentialMetadata
	replayed := false
	err = c.withCredentialTx(ctx, lease, c.data, "camera_credential_writer", func(tx pgx.Tx) error {
		if err := authorizeCredential(ctx, tx, authorize, accessFor(i, r, "MANAGE")); err != nil {
			return err
		}
		if err := credentialRequestLock(ctx, tx, i, scope); err != nil {
			return err
		}
		previous, ok, err := c.replay(ctx, tx, i, scope, canonical)
		if err != nil {
			return err
		}
		if ok {
			if previous.CredentialID != r.CredentialID || previous.DeviceID != r.DeviceID || previous.Version != r.Version || previous.RevokedAt == nil {
				return failure("CREDENTIAL_STORE_UNAVAILABLE", nil)
			}
			result = previous
			replayed = true
			return nil
		}
		if err = credentialDeviceLock(ctx, tx, r.DeviceID); err != nil {
			return err
		}
		var lockedID string
		err = tx.QueryRow(ctx, "SELECT credential_id FROM camera.credentials WHERE scope_id=$1 AND device_id=$2 AND credential_id=$3 FOR UPDATE", i.ScopeID, r.DeviceID, r.CredentialID).Scan(&lockedID)
		if errors.Is(err, pgx.ErrNoRows) {
			return failure("CREDENTIAL_UNAVAILABLE", nil)
		}
		if err != nil {
			return failure("CREDENTIAL_STORE_UNAVAILABLE", err)
		}
		var active bool
		if err = tx.QueryRow(ctx, "SELECT EXISTS(SELECT 1 FROM camera.credential_versions WHERE credential_id=$1 AND version=$2 AND revoked_at IS NULL)", r.CredentialID, r.Version).Scan(&active); err != nil {
			return failure("CREDENTIAL_STORE_UNAVAILABLE", err)
		}
		if !active {
			return failure("CREDENTIAL_UNAVAILABLE", nil)
		}
		if guard == nil {
			return failure("CREDENTIAL_USAGE_UNAVAILABLE", nil)
		}
		usage, err := guard(ctx, tx, r)
		if err != nil {
			return failure("CREDENTIAL_USAGE_UNAVAILABLE", nil)
		}
		if usage == CredentialUsageInUse {
			return failure("CREDENTIAL_IN_USE", nil)
		}
		if usage != CredentialUsageUnused {
			return failure("CREDENTIAL_USAGE_UNAVAILABLE", nil)
		}
		if _, err = tx.Exec(ctx, "UPDATE camera.credential_versions SET revoked_at=GREATEST(clock_timestamp(),created_at) WHERE credential_id=$1 AND version=$2 AND revoked_at IS NULL", r.CredentialID, r.Version); err != nil {
			return failure("CREDENTIAL_STORE_UNAVAILABLE", err)
		}
		result, err = scanCredentialMetadata(tx.QueryRow(ctx, `SELECT c.credential_id,c.device_id,v.version,v.created_at,v.revoked_at
FROM camera.credentials c JOIN camera.credential_versions v USING (credential_id) WHERE c.credential_id=$1 AND v.version=$2`, r.CredentialID, r.Version))
		if err != nil {
			return failure("CREDENTIAL_STORE_UNAVAILABLE", err)
		}
		return c.journal(ctx, tx, i, scope, canonical, result)
	})
	if err != nil {
		return CredentialMetadata{}, false, err
	}
	if err = lease.Check(ctx); err != nil {
		return CredentialMetadata{}, false, err
	}
	return result, replayed, nil
}
