package app

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"math"
	"net/http"
	"sync"
	"time"

	"github.com/jackc/pgx/v5"
	"vms.local/platform/camera/internal/contracts"
	"vms.local/platform/camera/internal/storage"
	"vms.local/platform/internal/httpapi"
)

// CredentialManagementGrant is trusted local service-client configuration.
// Exact DER certificate hashes identify peers; names, headers and bearer alone
// never manufacture a principal. Device permission covers MANAGE only.
type CredentialManagementGrant struct {
	CertificateSHA256 string
	ScopeID           string
	PrincipalID       string
	DeviceIDs         []string
}
type managementGrant struct {
	scope, principal string
	devices          map[string]struct{}
}
type CredentialManagementPolicy struct {
	mu       sync.RWMutex
	grants   map[string]managementGrant
	revision uint64
}
type managementPeer struct {
	policy                 *CredentialManagementPolicy
	hash, scope, principal string
	revision               uint64
	expires                time.Time
}
type managementContextKey struct{}

func managementConfigurationError() error {
	return errors.New("credential management configuration unavailable")
}
func managementGrants(input []CredentialManagementGrant) (map[string]managementGrant, error) {
	if len(input) > 1024 {
		return nil, managementConfigurationError()
	}
	result := make(map[string]managementGrant, len(input))
	for _, g := range input {
		raw, err := hex.DecodeString(g.CertificateSHA256)
		if err != nil || len(raw) != 32 || hex.EncodeToString(raw) != g.CertificateSHA256 || !contracts.ValidDeviceID(g.ScopeID) || !contracts.ValidDeviceID(g.PrincipalID) || len(g.DeviceIDs) == 0 || len(g.DeviceIDs) > 1024 {
			return nil, managementConfigurationError()
		}
		if _, exists := result[g.CertificateSHA256]; exists {
			return nil, managementConfigurationError()
		}
		row := managementGrant{g.ScopeID, g.PrincipalID, make(map[string]struct{}, len(g.DeviceIDs))}
		for _, id := range g.DeviceIDs {
			if !contracts.ValidDeviceID(id) {
				return nil, managementConfigurationError()
			}
			if _, exists := row.devices[id]; exists {
				return nil, managementConfigurationError()
			}
			row.devices[id] = struct{}{}
		}
		result[g.CertificateSHA256] = row
	}
	return result, nil
}
func NewCredentialManagementPolicy(input []CredentialManagementGrant) (*CredentialManagementPolicy, error) {
	grants, err := managementGrants(input)
	if err != nil {
		return nil, err
	}
	return &CredentialManagementPolicy{grants: grants, revision: 1}, nil
}

// Replace is an explicit trusted administrative action, never an HTTP route.
// Every policy replacement invalidates in-flight principal snapshots. Invalid
// input keeps the old policy; no wildcard or implicit development fallback.
func (p *CredentialManagementPolicy) Replace(input []CredentialManagementGrant) error {
	grants, err := managementGrants(input)
	if err != nil || p == nil {
		return managementConfigurationError()
	}
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.grants == nil || p.revision == 0 || p.revision == math.MaxUint64 {
		return managementConfigurationError()
	}
	p.grants = grants
	p.revision++
	return nil
}
func (p *CredentialManagementPolicy) peer(r *http.Request) managementPeer {
	if p == nil || r.TLS == nil || !r.TLS.HandshakeComplete || len(r.TLS.PeerCertificates) == 0 || len(r.TLS.VerifiedChains) == 0 || len(r.TLS.VerifiedChains[0]) == 0 {
		return managementPeer{}
	}
	leaf := r.TLS.PeerCertificates[0]
	verified := r.TLS.VerifiedChains[0][0]
	if leaf == nil || verified == nil || leaf.IsCA || !leaf.Equal(verified) || time.Now().Before(leaf.NotBefore) || !time.Now().Before(leaf.NotAfter) {
		return managementPeer{}
	}
	sum := sha256.Sum256(leaf.Raw)
	hash := hex.EncodeToString(sum[:])
	p.mu.RLock()
	defer p.mu.RUnlock()
	g, ok := p.grants[hash]
	if !ok {
		return managementPeer{}
	}
	return managementPeer{p, hash, g.scope, g.principal, p.revision, leaf.NotAfter}
}
func (p *CredentialManagementPolicy) current(ctx context.Context) (managementPeer, managementGrant, bool) {
	if p == nil || ctx == nil || ctx.Err() != nil {
		return managementPeer{}, managementGrant{}, false
	}
	peer, ok := ctx.Value(managementContextKey{}).(managementPeer)
	if !ok || peer.policy != p || !time.Now().Before(peer.expires) {
		return managementPeer{}, managementGrant{}, false
	}
	g, ok := p.grants[peer.hash]
	return peer, g, ok && peer.revision == p.revision && g.scope == peer.scope && g.principal == peer.principal
}
func (p *CredentialManagementPolicy) resolve(ctx context.Context) (string, string, bool, error) {
	if p == nil {
		return "", "", false, managementConfigurationError()
	}
	p.mu.RLock()
	defer p.mu.RUnlock()
	peer, _, ok := p.current(ctx)
	if !ok {
		return "untrusted", "untrusted", false, nil
	}
	return peer.scope, peer.principal, true, nil
}
func (p *CredentialManagementPolicy) authorize(ctx context.Context, tx pgx.Tx, a storage.CredentialAccess) (bool, error) {
	if p == nil || tx == nil {
		return false, managementConfigurationError()
	}
	p.mu.RLock()
	defer p.mu.RUnlock()
	peer, g, ok := p.current(ctx)
	if !ok || a.Operation != "MANAGE" || a.Version < 0 || !contracts.ValidDeviceID(a.CredentialID) || a.ScopeID != peer.scope || a.PrincipalID != peer.principal {
		return false, nil
	}
	_, allowed := g.devices[a.DeviceID]
	return allowed, nil
}

// Registration is explicit and does not start a listener, change main, discover
// IAM, load secrets, bootstrap authority or provide a default unused guard.
// Serve the returned handler with trusted direct TLS client verification.
func RegisterCredentialManagement(a *httpapi.API, store *storage.CredentialStore, p *CredentialManagementPolicy, guard storage.CredentialRevokeGuard) (http.Handler, error) {
	if a == nil || store == nil || p == nil || guard == nil {
		return nil, managementConfigurationError()
	}
	p.mu.RLock()
	valid := p.grants != nil && p.revision > 0
	p.mu.RUnlock()
	if !valid {
		return nil, managementConfigurationError()
	}
	registerCredentialWrites(a, store, p.resolve, p.authorize)
	registerCredentialVersions(a, store, p.resolve, p.authorize, guard)
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Overwrite any inherited context identity, including reused request contexts.
		ctx := context.WithValue(r.Context(), managementContextKey{}, p.peer(r))
		a.ServeHTTP(w, r.WithContext(ctx))
	}), nil
}
