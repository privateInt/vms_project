package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"os"
	"time"

	"vms.local/platform/camera/internal/storage"
)

func run() int {
	apply := flag.Bool("apply", false, "Apply camera schema migrations to the explicitly configured database")
	grant := flag.Bool("grant-runtime", false, "Grant camera_runtime the current device/source API privileges after migration")
	flag.Parse()
	if !*apply || flag.NArg() != 0 {
		_ = json.NewEncoder(os.Stderr).Encode(map[string]string{"status": "error", "code": "EXPLICIT_APPLY_REQUIRED"})
		return 2
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	dsn, _, err := storage.DatabaseURL()
	var s *storage.Store
	if err == nil {
		s, err = storage.Open(ctx, dsn)
	}
	if err == nil {
		defer s.Close()
		var result storage.MigrationResult
		result, err = s.Migrate(ctx)
		if err == nil && *grant {
			err = s.ProvisionRegistryRuntime(ctx)
		}
		if err == nil {
			_ = json.NewEncoder(os.Stdout).Encode(result)
			return 0
		}
	}
	code, sqlstate := "DATABASE_OPERATION_FAILED", ""
	var dbErr *storage.Error
	if errors.As(err, &dbErr) {
		code, sqlstate = dbErr.Code, dbErr.SQLState
	}
	_ = json.NewEncoder(os.Stderr).Encode(map[string]string{"status": "error", "code": code, "sqlstate": sqlstate})
	return 1
}

func main() { os.Exit(run()) }
