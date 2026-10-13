package main

import (
	"context"
	"log/slog"
	"os"
	"time"
	"vms.local/platform/camera/internal/app"
	"vms.local/platform/camera/internal/storage"
	"vms.local/platform/internal/httpapi"
)

func run() int {
	var store *storage.Store
	defer func() {
		if store != nil {
			store.Close()
		}
	}()
	return httpapi.Main(func(token string, logger *slog.Logger) (*httpapi.API, error) {
		dsn, present, configErr := storage.DatabaseURL()
		if configErr != nil {
			return nil, configErr
		}
		if !present {
			return app.New(token, logger)
		}
		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		var err error
		store, err = storage.Open(ctx, dsn)
		if err != nil {
			return nil, err
		}
		if err = store.CheckReady(ctx); err != nil {
			return nil, err
		}
		return app.NewWithStore(token, logger, store)
	})
}
func main() { os.Exit(run()) }
