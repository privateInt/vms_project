package storage

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestDatabaseURLSources(t *testing.T) {
	t.Setenv("CAMERA_DATABASE_URL", "")
	t.Setenv("CAMERA_DATABASE_URL_FILE", "")
	os.Unsetenv("CAMERA_DATABASE_URL")
	os.Unsetenv("CAMERA_DATABASE_URL_FILE")
	if _, present, err := DatabaseURL(); present || err != nil {
		t.Fatal("absent configuration changed")
	}
	os.Setenv("CAMERA_DATABASE_URL", "postgres://user:test-secret@db/database")
	if value, present, err := DatabaseURL(); value == "" || !present || err != nil {
		t.Fatal("direct configuration failed")
	}
	os.Setenv("CAMERA_DATABASE_URL_FILE", "/missing-test-secret")
	if _, _, err := DatabaseURL(); err == nil || err.Error() != "DATABASE_CONFIG_AMBIGUOUS" {
		t.Fatal("ambiguous configuration accepted")
	}
	os.Unsetenv("CAMERA_DATABASE_URL")
	if _, _, err := DatabaseURL(); err == nil || strings.Contains(err.Error(), "/missing") {
		t.Fatal("missing file diagnostic unsafe")
	}
	path := filepath.Join(t.TempDir(), "dsn")
	os.Setenv("CAMERA_DATABASE_URL_FILE", path)
	value := "postgres://user:test-secret@db/database"
	if err := os.WriteFile(path, []byte(value+"\n"), 0600); err != nil {
		t.Fatal(err)
	}
	if got, present, err := DatabaseURL(); got != value || !present || err != nil {
		t.Fatal("file configuration failed")
	}
	for _, invalid := range []string{"", value + "\nextra", strings.Repeat("x", 8193)} {
		if err := os.WriteFile(path, []byte(invalid), 0600); err != nil {
			t.Fatal(err)
		}
		if _, _, err := DatabaseURL(); err == nil || strings.Contains(err.Error(), "test-secret") {
			t.Fatal("invalid secret accepted or exposed")
		}
	}
	os.Setenv("CAMERA_DATABASE_URL_FILE", filepath.Dir(path))
	if _, _, err := DatabaseURL(); err == nil {
		t.Fatal("directory accepted")
	}
}
