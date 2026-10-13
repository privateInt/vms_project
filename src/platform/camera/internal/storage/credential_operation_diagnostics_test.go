//go:build linux

package storage

import "testing"

func TestCredentialOperationSignalPermissionPreflight(t *testing.T) {
	for _, status := range []string{"CapEff:\t0000000000000020\n", "Name:\tfixture\nCapEff:\t00000000000000e9\n"} {
		if !operationOwnerCanSignal([]byte(status)) {
			t.Fatal("CAP_KILL not detected")
		}
	}
	// Original four capabilities contain CHOWN/FOWNER/SETGID/SETUID, but no KILL.
	for _, status := range []string{"CapEff:\t00000000000000c9\n", "CapEff:\t0000000000000000\n", "CapPrm:\t0000000000000020\n", "CapEff:\tinvalid\n", "CapEff:\t0000000000000020 extra\n", ""} {
		if operationOwnerCanSignal([]byte(status)) {
			t.Fatal("missing or malformed effective permission accepted")
		}
	}
}

func TestCredentialOperationFailureComponentPrivacy(t *testing.T) {
	for _, component := range []string{"owner_signal", "child_database_setup", "child_approved_pools", "child_ready", "child_append", "child_recreated"} {
		if operationSafeComponent(component) != component {
			t.Fatal("reviewed component rejected")
		}
	}
	for _, value := range []string{"postgres://synthetic-private-user:synthetic-private-password@private.invalid/db", "child_ready\nsecret", "child_unknown", ""} {
		if operationSafeComponent(value) != "child_unknown" {
			t.Fatal("unreviewed diagnostic exposed")
		}
	}
}
