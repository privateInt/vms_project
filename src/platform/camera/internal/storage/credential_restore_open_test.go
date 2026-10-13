package storage

import (
	"bytes"
	"context"
	"testing"
	"time"
	"vms.local/platform/camera/internal/credentialadmission"
)

func TestCredentialRestoredRuntimeHBA(t *testing.T) {
	expected := "# camera maintenance boundary v1; complete file\nlocal all all reject\nhostssl \"all\",postgres camera_maintenance 192.0.2.1/32 scram-sha-256 clientcert=verify-full\nhostssl \"all\" camera_credential_writer,camera_credential_budget 192.0.2.2/32 scram-sha-256\nhost all all 0.0.0.0/0 reject\nhost all all ::/0 reject\n"
	got, e := CredentialRestoredRuntimeHBA("all", "192.0.2.1", "192.0.2.2")
	if e != nil || !bytes.Equal(got, []byte(expected)) {
		t.Fatal("source-pinned complete policy mismatch")
	}
	got, e = CredentialRestoredRuntimeHBA("camera", "2001:db8::1", "2001:db8::2")
	if e != nil || !bytes.Contains(got, []byte("2001:db8::2/128 scram-sha-256")) {
		t.Fatal("exact IPv6 source required")
	}
	for _, v := range [][3]string{{"postgres", "192.0.2.1", "192.0.2.2"}, {"camera\nall", "192.0.2.1", "192.0.2.2"}, {"camera", "192.0.2.1", "192.0.2.1"}, {"camera", "192.0.2.1", "192.0.2.0/24"}, {"camera", "192.0.2.1", "0.0.0.0"}, {"camera", "192.0.2.1", "::ffff:192.0.2.2"}, {"camera", "192.0.2.1", "224.0.0.1"}} {
		if _, e = CredentialRestoredRuntimeHBA(v[0], v[1], v[2]); e == nil {
			t.Fatal("ambiguous or unsafe source/database accepted")
		}
	}
}
func TestCredentialRestoreOpenRejectsMissingAuthority(t *testing.T) {
	var s *Store
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	for _, c := range []context.Context{nil, context.Background(), ctx} {
		if s.AuthorizeRestoredCredentialOpen(c, nil, credentialadmission.Record{}, credentialadmission.Record{}, nil, "", nil, nil, nil, nil, CredentialAdmissionDatabase{}) == nil {
			t.Fatal("missing authority accepted")
		}
	}
}
