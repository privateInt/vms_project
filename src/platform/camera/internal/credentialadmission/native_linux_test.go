//go:build linux

package credentialadmission

import (
	"encoding/json"
	"fmt"
	"os"
	"testing"
	"time"
)

// Only the disposable Compose runner enables these phases. This tests real
// local Linux ownership/mounts, never a DB, key bundle or production authority.
func TestNativeReadOnlyMount(t *testing.T) {
	phase := os.Getenv("VMS_ADMISSION_NATIVE_PHASE")
	if phase == "" {
		return
	}
	switch phase {
	case "prepare":
		if os.Geteuid() != 0 {
			t.Fatal("isolated fixture owner required")
		}
		p := Policy{Directory: "/authority/control", OwnerUID: 0, RuntimeGID: 10001}
		r := initial(t)
		identity, err := Bootstrap(deadline(t, time.Second), p, r)
		if err != nil {
			t.Fatal(err)
		}
		p.LockIdentity = identity
		l, err := AcquireMaintenance(deadline(t, time.Second), p)
		if err != nil {
			t.Fatal(err)
		}
		defer l.Close()
		prepared, _ := NextPrepare(r, candidate(), timestamp)
		if err = l.Commit(r, prepared); err != nil {
			t.Fatal(err)
		}
		op, _ := NextOpen(prepared, timestamp)
		if err = l.Commit(prepared, op); err != nil {
			t.Fatal(err)
		}
		body, err := json.Marshal(p)
		if err != nil {
			t.Fatal(err)
		}
		if err = os.WriteFile("/exchange/admission-policy.json", body, 0644); err != nil {
			t.Fatal(err)
		}
		if err = os.Chmod("/exchange/admission-policy.json", 0644); err != nil {
			t.Fatal(err)
		}
		fmt.Println("ADMISSION_NATIVE_PHASE_OK:prepare")
	case "read":
		if os.Geteuid() != 10001 || os.Getegid() != 10001 {
			t.Fatal("isolated runtime UID/GID required")
		}
		body, err := os.ReadFile("/exchange/admission-policy.json")
		if err != nil {
			t.Fatal(err)
		}
		var p Policy
		if json.Unmarshal(body, &p) != nil || p.Directory != "/authority/control" || p.OwnerUID != 0 || p.RuntimeGID != 10001 {
			t.Fatal("fixture policy")
		}
		one, err := AcquireReadOnly(deadline(t, time.Second), p, openRecord(t))
		if err != nil {
			t.Fatal(err)
		}
		defer one.Close()
		two, err := AcquireReadOnly(deadline(t, time.Second), p, openRecord(t))
		if err != nil {
			t.Fatal(err)
		}
		defer two.Close()
		one.Close()
		if err = two.Check(); err != nil {
			t.Fatal(err)
		}
		if l, err := AcquireMaintenance(deadline(t, time.Second), p); err != ErrUnavailable {
			if l != nil {
				l.Close()
			}
			t.Fatal("runtime maintenance admitted", err)
		}
		if err = os.WriteFile(p.Directory+"/runtime-write", []byte("synthetic"), 0640); err == nil {
			t.Fatal("read-only control writable")
		}
		fmt.Println("ADMISSION_NATIVE_PHASE_OK:read")
	default:
		t.Fatal("unrecognized native phase")
	}
}
