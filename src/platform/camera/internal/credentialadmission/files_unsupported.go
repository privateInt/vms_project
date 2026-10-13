//go:build !linux

package credentialadmission

import "context"

type MaintenanceLease struct{}
type ReadLease struct{}

func bootstrap(context.Context, Policy, Record) (LockIdentity, error) {
	return LockIdentity{}, ErrUnavailable
}
func acquireMaintenance(context.Context, Policy) (*MaintenanceLease, error) {
	return nil, ErrUnavailable
}
func acquireRead(context.Context, Policy, Record, bool) (*ReadLease, error) {
	return nil, ErrUnavailable
}
func (*MaintenanceLease) Snapshot() (Record, error)   { return Record{}, ErrUnavailable }
func (*MaintenanceLease) Commit(Record, Record) error { return ErrUnavailable }
func (*MaintenanceLease) Close() error                { return nil }
func (*ReadLease) Check() error                       { return ErrUnavailable }
func (*ReadLease) Close() error                       { return nil }
