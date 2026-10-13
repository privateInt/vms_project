package storage

import (
	"context"
	"encoding/json"
	"regexp"
	"time"

	"github.com/jackc/pgx/v5"
	"vms.local/platform/camera/internal/contracts"
	"vms.local/platform/camera/internal/credentialcrypto"
)

var credentialKeyID = regexp.MustCompile(`^enc-[0-9a-f]{16}$`)

// CredentialIdentity is supplied by trusted authentication, never the body.
type CredentialIdentity struct{ ScopeID, PrincipalID, IdempotencyKey string }

func (i CredentialIdentity) valid(mutation bool) bool {
	return contracts.ValidDeviceID(i.ScopeID) && contracts.ValidDeviceID(i.PrincipalID) &&
		(!mutation || contracts.ValidIdempotencyKey(i.IdempotencyKey))
}

// Target is private policy, not authorization to perform a network call.
// Matching preserves exact host spelling; no implicit widening/normalization.
type CredentialTarget struct {
	Protocol string `json:"protocol"`
	Host     string `json:"host"`
	Port     int    `json:"port"`
}

func (p CredentialTarget) valid() bool {
	return contracts.ValidCredentialTarget(p.Protocol, p.Host, int64(p.Port))
}
func (p CredentialTarget) digest() string { b, _ := json.Marshal(p); return hashText(b) }

type CredentialWrite struct {
	CredentialID    string
	DeviceID        string
	ExpectedVersion int64 // 0 creates the resource; positive appends a new version.
	Target          CredentialTarget
	Secret          credentialcrypto.Secret
}

func (w CredentialWrite) valid() bool {
	_, err := credentialcrypto.NewSecret(w.Secret.Username(), w.Secret.Password())
	return contracts.ValidDeviceID(w.CredentialID) && contracts.ValidDeviceID(w.DeviceID) && w.ExpectedVersion >= 0 && w.Target.valid() && err == nil
}

type CredentialReference struct {
	CredentialID, DeviceID string
	Version                int64
}

func (r CredentialReference) valid() bool {
	return contracts.ValidDeviceID(r.CredentialID) && contracts.ValidDeviceID(r.DeviceID) && r.Version > 0
}

// Safe metadata and success receipts contain no address, username or password.
type CredentialMetadata struct {
	CredentialID string     `json:"credential_id"`
	DeviceID     string     `json:"device_id"`
	Version      int64      `json:"credential_version"`
	CreatedAt    time.Time  `json:"created_at"`
	RevokedAt    *time.Time `json:"revoked_at,omitempty"`
}

type CredentialAccess struct {
	ScopeID, PrincipalID, DeviceID, CredentialID, Operation string
	Version                                                 int64
}

// Authorizers must verify device scope AND distinct secret-management/reference
// rights using tx. Nil/unknown/failure denies access, including success replay.
// They must not commit, change credential/parent state or emit private values.
type CredentialAuthorizer func(context.Context, pgx.Tx, CredentialAccess) (bool, error)

type CredentialUsage uint8

const (
	CredentialUsageUnknown CredentialUsage = iota
	CredentialUsageUnused
	CredentialUsageInUse
)

// A future managed-reference/usage guard shares device -> credential locks.
// There is no default "unused" implementation in the production package.
type CredentialRevokeGuard func(context.Context, pgx.Tx, CredentialReference) (CredentialUsage, error)

func accessFor(i CredentialIdentity, r CredentialReference, operation string) CredentialAccess {
	return CredentialAccess{i.ScopeID, i.PrincipalID, r.DeviceID, r.CredentialID, operation, r.Version}
}
func authorizeCredential(ctx context.Context, tx pgx.Tx, guard CredentialAuthorizer, access CredentialAccess) error {
	if guard == nil {
		return failure("CREDENTIAL_AUTHORIZATION_UNAVAILABLE", nil)
	}
	allowed, err := guard(ctx, tx, access)
	if err != nil {
		return failure("CREDENTIAL_AUTHORIZATION_UNAVAILABLE", nil)
	}
	if !allowed {
		return failure("CREDENTIAL_UNAVAILABLE", nil)
	}
	return nil
}

// Canonical private DTO bytes are transient. Only their keyed fingerprint persists.
func canonicalCredentialWrite(i CredentialIdentity, w CredentialWrite) []byte {
	b, _ := json.Marshal(struct {
		ScopeID         string           `json:"scope_id"`
		CredentialID    string           `json:"credential_id"`
		DeviceID        string           `json:"device_id"`
		ExpectedVersion int64            `json:"expected_version"`
		Target          CredentialTarget `json:"target"`
		Username        string           `json:"username"`
		Password        string           `json:"password"`
	}{i.ScopeID, w.CredentialID, w.DeviceID, w.ExpectedVersion, w.Target, w.Secret.Username(), w.Secret.Password()})
	return b
}
