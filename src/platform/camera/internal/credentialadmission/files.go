package credentialadmission

import "context"

// LockIdentity is a bootstrap receipt pinned in reviewed host configuration,
// outside DB/key snapshots. Never rediscover it automatically after loss.
type LockIdentity struct {
	Device uint64
	Inode  uint64
}

// Policy is trusted configuration, never HTTP input. Provision Directory as
// OwnerUID:RuntimeGID 0750 outside project/DB/key backups before use. This
// foundation cannot discover every backup destination or authorize bootstrap.
type Policy struct {
	Directory    string
	OwnerUID     int
	RuntimeGID   int
	LockIdentity LockIdentity
}

// Bootstrap requires an explicit empty first-deployment authority. It creates
// only FENCED generation 1, never repairs a missing record or replaces a lock.
// Pin the returned identity before issuing any future leases. An interrupted
// bootstrap requires separate audited recovery, never automatic rediscovery.
func Bootstrap(ctx context.Context, p Policy, initial Record) (LockIdentity, error) {
	return bootstrap(ctx, p, initial)
}

// AcquireMaintenance obtains an exclusive lease with a mandatory deadline.
func AcquireMaintenance(ctx context.Context, p Policy) (*MaintenanceLease, error) {
	return acquireMaintenance(ctx, p)
}

// AcquireReadOnly checks an actual read-only local mount, distinct runtime UID,
// OPEN and the complete pinned expected record. Caller still must verify actual
// DB/key receipts while holding the lease for the entire business operation.
func AcquireReadOnly(ctx context.Context, p Policy, expected Record) (*ReadLease, error) {
	return acquireRead(ctx, p, expected, true)
}
