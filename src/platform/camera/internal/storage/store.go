// Package storage owns camera persistence infrastructure. It has no HTTP routes.
package storage

import (
	"context"
	"errors"
	"net/url"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgxpool"
)

// Error is safe to log: driver diagnostics can contain credentials or row data.
type Error struct {
	Code     string
	SQLState string
	cause    error
}

func (e *Error) Error() string { return e.Code }
func (e *Error) Unwrap() error { return e.cause }
func failure(code string, err error) error {
	e := &Error{Code: code, cause: err}
	var pg *pgconn.PgError
	if errors.As(err, &pg) {
		e.SQLState = pg.Code
	}
	return e
}

type Store struct {
	pool              *pgxpool.Pool
	admissionEndpoint *CredentialEndpoint
}

// Open checks the connection but never runs DDL or changes registration data.
// Callers supply an explicit DSN and deadline; no default database is selected.
func Open(ctx context.Context, dsn string) (*Store, error) {
	if strings.TrimSpace(dsn) == "" {
		return nil, failure("DATABASE_URL_REQUIRED", nil)
	}
	u, err := url.Parse(dsn)
	if err != nil || (u.Scheme != "postgres" && u.Scheme != "postgresql") || u.User == nil || u.User.Username() == "" || u.Path == "" || u.Path == "/" || (u.Hostname() == "" && u.Query().Get("host") == "") || u.Fragment != "" {
		return nil, failure("DATABASE_CONFIG_INVALID", nil)
	}
	cfg, err := pgxpool.ParseConfig(dsn)
	if err != nil {
		return nil, failure("DATABASE_CONFIG_INVALID", err)
	}
	cfg.MaxConns = 4
	cfg.MinConns = 0
	cfg.ConnConfig.ConnectTimeout = 5 * time.Second
	cfg.ConnConfig.RuntimeParams["application_name"] = "vms-camera-storage"
	cfg.ConnConfig.RuntimeParams["timezone"] = "UTC"
	cfg.ConnConfig.RuntimeParams["statement_timeout"] = "15000"
	cfg.ConnConfig.RuntimeParams["lock_timeout"] = "5000"
	cfg.ConnConfig.RuntimeParams["idle_in_transaction_session_timeout"] = "30000"
	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		return nil, failure("DATABASE_CONFIG_INVALID", err)
	}
	ping, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	if err = pool.Ping(ping); err != nil {
		pool.Close()
		return nil, failure("DATABASE_UNAVAILABLE", err)
	}
	return &Store{pool: pool}, nil
}

func (s *Store) Close() { s.pool.Close() }

// WithTx uses READ COMMITTED so post-lock reads see preceding commits even
// when the connection default is stronger. It rolls back on error or panic.
// The caller must use the supplied tx for every statement and must not commit it.
func (s *Store) WithTx(ctx context.Context, fn func(pgx.Tx) error) error {
	tx, err := s.pool.BeginTx(ctx, pgx.TxOptions{IsoLevel: pgx.ReadCommitted})
	if err != nil {
		return failure("TRANSACTION_BEGIN_FAILED", err)
	}
	defer func() {
		cleanup, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = tx.Rollback(cleanup)
	}()
	if err = fn(tx); err != nil {
		var safe *Error
		if errors.As(err, &safe) {
			return safe
		}
		return failure("TRANSACTION_BODY_FAILED", err)
	}
	if err = tx.Commit(ctx); err != nil {
		return failure("TRANSACTION_COMMIT_FAILED", err)
	}
	return nil
}
