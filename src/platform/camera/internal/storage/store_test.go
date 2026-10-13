package storage

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"testing"
	"testing/fstest"

	"github.com/jackc/pgx/v5/pgconn"
)

func TestOpenRequiresExplicitConfig(t *testing.T) {
	for _, dsn := range []string{"", "postgres://user:secret@%xx/database", "postgres://user:secret@localhost/", "postgres://localhost/database", "host=localhost dbname=other"} {
		_, err := Open(context.Background(), dsn)
		if err == nil || strings.Contains(fmt.Sprintf("%+v", err), "secret") {
			t.Fatal("invalid config was accepted or exposed")
		}
	}
}

func TestSafeDatabaseError(t *testing.T) {
	input := &pgconn.PgError{Code: "23505", Message: "sensitive row", Detail: "secret"}
	err := failure("DATABASE_ERROR", input)
	if strings.Contains(fmt.Sprintf("%+v", err), "secret") || err.Error() != "DATABASE_ERROR" {
		t.Fatal("diagnostics exposed")
	}
	if !errors.Is(err, input) {
		t.Fatal("error identity lost")
	}
	var safe *Error
	if !errors.As(err, &safe) || safe.SQLState != "23505" {
		t.Fatal("SQLSTATE missing")
	}
}

func TestMigrationsAreContiguous(t *testing.T) {
	for _, name := range []string{"migrations/0002_gap.sql", "migrations/a.sql"} {
		_, err := loadMigrations(fstest.MapFS{name: &fstest.MapFile{Data: []byte("SELECT 1;")}})
		if err == nil {
			t.Fatal("invalid order accepted")
		}
	}
	m, err := loadMigrations(migrationFiles)
	if err != nil || len(m) != 8 || len(m[0].checksum) != 64 {
		t.Fatalf("embedded migrations invalid: %v", err)
	}
}
