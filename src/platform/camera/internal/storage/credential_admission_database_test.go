package storage

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"strings"
	"testing"
)

func admissionDatabaseFixture(t *testing.T) CredentialAdmissionDatabase {
	t.Helper()
	hash, err := CredentialAdmissionMigrationsSHA256()
	if err != nil {
		t.Fatal(err)
	}
	return CredentialAdmissionDatabase{
		DeploymentID: "11111111-1111-4111-8111-111111111111", Generation: 1,
		OperationID:  "22222222-2222-4222-8222-222222222222",
		DatabaseID:   "33333333-3333-4333-8333-333333333333",
		DatabaseName: "vms_camera_test", SchemaVersion: 9, MigrationSetSHA256: hash,
	}
}

func TestAdmissionMigrationHashAndLegacyTarget(t *testing.T) {
	old, err := loadMigrations(migrationFiles)
	if err != nil || len(old) != 8 {
		t.Fatal("legacy target changed")
	}
	ms, err := loadAdmissionMigrations()
	if err != nil || len(ms) != 9 || ms[8].name != admissionMigrationName {
		t.Fatal("admission target invalid")
	}
	for i := range old {
		if ms[i] != old[i] {
			t.Fatal("legacy SQL changed")
		}
	}
	// Independent literal proves field order, version representation and no newline.
	raw := `[{"version":1,"name":"migrations/0001_test.sql","checksum":"` + strings.Repeat("a", 64) + `"}]`
	sum := sha256.Sum256([]byte(raw))
	sample := []migration{{name: "migrations/0001_test.sql", checksum: strings.Repeat("a", 64)}}
	if admissionMigrationsHash(sample) != hex.EncodeToString(sum[:]) {
		t.Fatal("canonical hash differs")
	}
	first := admissionMigrationsHash(ms)
	ms[8].checksum = strings.Repeat("f", 64)
	if first == admissionMigrationsHash(ms) {
		t.Fatal("SQL change not bound")
	}
	ms, _ = loadAdmissionMigrations()
	ms[0], ms[1] = ms[1], ms[0]
	if first == admissionMigrationsHash(ms) {
		t.Fatal("migration order not bound")
	}
}

func TestAdmissionDatabaseExpectedValidationAndSafeErrors(t *testing.T) {
	expected := admissionDatabaseFixture(t)
	hash := expected.MigrationSetSHA256
	if !expected.valid(hash) {
		t.Fatal("fixture invalid")
	}
	cases := map[string]func(*CredentialAdmissionDatabase){
		"deployment":  func(e *CredentialAdmissionDatabase) { e.DeploymentID = "secret://bad" },
		"generation":  func(e *CredentialAdmissionDatabase) { e.Generation = 0 },
		"operation":   func(e *CredentialAdmissionDatabase) { e.OperationID = strings.ToUpper(e.OperationID) + "A" },
		"incarnation": func(e *CredentialAdmissionDatabase) { e.DatabaseID = "33333333-3333-1333-8333-333333333333" },
		"name":        func(e *CredentialAdmissionDatabase) { e.DatabaseName = "name/password" },
		"schema":      func(e *CredentialAdmissionDatabase) { e.SchemaVersion = 8 },
		"hash":        func(e *CredentialAdmissionDatabase) { e.MigrationSetSHA256 = strings.Repeat("0", 64) },
	}
	for name, change := range cases {
		t.Run(name, func(t *testing.T) {
			e := expected
			change(&e)
			if e.valid(hash) {
				t.Fatal("invalid expected binding accepted")
			}
		})
	}
	var empty *Store
	err := empty.CheckCredentialAdmissionDatabase(t.Context(), expected, "camera_credential_writer")
	safe, ok := err.(*Error)
	if !ok || safe.Code != "ADMISSION_DATABASE_UNAVAILABLE" || safe.cause != nil || safe.SQLState != "" || strings.Contains(fmt.Sprintf("%+v", err), "secret") {
		t.Fatal("unsafe error")
	}
	if (&Store{}).CheckCredentialAdmissionDatabase(t.Context(), expected, "secret-role") == nil {
		t.Fatal("untrusted role accepted")
	}
}
