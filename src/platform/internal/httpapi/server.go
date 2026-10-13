// Package httpapi contains transport-only code shared by platform APIs.
package httpapi

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"mime"
	"net"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"sync/atomic"
	"syscall"
	"time"
)

const Version = "0.1.0-p0"
const MaxBodyBytes int64 = 64 << 10

type Manifest struct {
	Platform     string            `json:"platform"`
	Version      string            `json:"version"`
	Stage        string            `json:"stage"`
	Capabilities map[string]string `json:"capabilities"`
}

type Violation struct {
	Field   string `json:"field"`
	Code    string `json:"code"`
	Message string `json:"message"`
}

type Problem struct {
	Code    string      `json:"code"`
	Message string      `json:"message"`
	Details []Violation `json:"details,omitempty"`
}

type Config struct{ Address, Token string }

type API struct {
	manifest       Manifest
	mux            *http.ServeMux
	tokenHash      [32]byte
	logger         *slog.Logger
	draining       atomic.Bool
	readiness      func(context.Context) error
	readinessScope string
}

func New(manifest Manifest, token string, spec []byte, logger *slog.Logger) (*API, error) {
	if len(token) < 24 || strings.HasPrefix(token, "CHANGE_ME") || strings.TrimSpace(token) != token {
		return nil, errors.New("VMS_API_TOKEN must be a non-placeholder token of at least 24 bytes without surrounding whitespace")
	}
	if logger == nil {
		logger = slog.Default()
	}
	if manifest.Version == "" {
		manifest.Version = Version
	}
	if manifest.Stage == "" {
		manifest.Stage = "P0_API_FOUNDATION"
	}
	a := &API{manifest: manifest, mux: http.NewServeMux(), tokenHash: sha256.Sum256([]byte(token)), logger: logger}
	a.mux.HandleFunc("/health/live", func(w http.ResponseWriter, r *http.Request) {
		if !RequireMethod(w, r, http.MethodGet) {
			return
		}
		WriteJSON(w, http.StatusOK, map[string]any{"status": "alive", "platform": manifest.Platform, "scope": "process"})
	})
	a.mux.HandleFunc("/health/ready", func(w http.ResponseWriter, r *http.Request) {
		if !RequireMethod(w, r, http.MethodGet) {
			return
		}
		status := http.StatusOK
		ready := !a.draining.Load()
		scope := "http_api_foundation"
		if a.readiness != nil {
			scope = a.readinessScope
			ctx, cancel := context.WithTimeout(r.Context(), time.Second)
			defer cancel()
			ready = ready && a.readiness(ctx) == nil
		}
		if !ready {
			status = http.StatusServiceUnavailable
		}
		WriteJSON(w, status, map[string]any{"ready": ready, "platform": manifest.Platform, "scope": scope, "business_runtime_ready": false})
	})
	a.mux.HandleFunc("/openapi.json", func(w http.ResponseWriter, r *http.Request) {
		if !RequireMethod(w, r, http.MethodGet) {
			return
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write(spec)
	})
	a.Handle("/api/v1/platform", func(w http.ResponseWriter, r *http.Request) {
		if !RequireMethod(w, r, http.MethodGet) {
			return
		}
		WriteJSON(w, http.StatusOK, a.manifest)
	})
	a.mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		Fail(w, r, http.StatusNotFound, "NOT_FOUND", "Endpoint is not implemented in this foundation", nil)
	})
	return a, nil
}

func (a *API) Handle(path string, fn http.HandlerFunc) {
	a.mux.HandleFunc(path, func(w http.ResponseWriter, r *http.Request) {
		header := r.Header.Get("Authorization")
		if !strings.HasPrefix(header, "Bearer ") {
			w.Header().Set("WWW-Authenticate", "Bearer")
			Fail(w, r, http.StatusUnauthorized, "UNAUTHORIZED", "A valid bearer token is required", nil)
			return
		}
		provided := sha256.Sum256([]byte(strings.TrimPrefix(header, "Bearer ")))
		if subtle.ConstantTimeCompare(provided[:], a.tokenHash[:]) != 1 {
			w.Header().Set("WWW-Authenticate", "Bearer")
			Fail(w, r, http.StatusUnauthorized, "UNAUTHORIZED", "A valid bearer token is required", nil)
			return
		}
		if a.draining.Load() {
			Fail(w, r, http.StatusServiceUnavailable, "DRAINING", "Service is shutting down", nil)
			return
		}
		fn(w, r)
	})
}

func (a *API) BeginDrain() { a.draining.Store(true) }

// SetReadiness must be called before serving; the callback must not mutate data.
func (a *API) SetReadiness(scope string, check func(context.Context) error) {
	a.readinessScope = scope
	a.readiness = check
}

func (a *API) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	start := time.Now()
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		Fail(w, r, 500, "INTERNAL_ERROR", "Cannot assign request ID", nil)
		return
	}
	id := hex.EncodeToString(b[:])
	w.Header().Set("X-Request-ID", id)
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	defer func() {
		if recover() != nil {
			Fail(w, r, 500, "INTERNAL_ERROR", "Unexpected server error", nil)
		}
		// Do not log authorization, payload, query, or an untrusted URL path.
		pattern := r.Pattern
		if pattern == "" {
			pattern = "unmatched"
		}
		a.logger.Info("request", "platform", a.manifest.Platform, "request_id", id, "method", r.Method, "route", pattern, "duration_ms", time.Since(start).Milliseconds())
	}()
	a.mux.ServeHTTP(w, r)
}

func WriteJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}

func Fail(w http.ResponseWriter, r *http.Request, status int, code, message string, details []Violation) {
	WriteJSON(w, status, map[string]any{"error": Problem{Code: code, Message: message, Details: details}, "request_id": w.Header().Get("X-Request-ID")})
}

func RequireMethod(w http.ResponseWriter, r *http.Request, method string) bool {
	if r.Method == method {
		return true
	}
	w.Header().Set("Allow", method)
	Fail(w, r, http.StatusMethodNotAllowed, "METHOD_NOT_ALLOWED", "Method is not supported", nil)
	return false
}

func DecodeJSON(w http.ResponseWriter, r *http.Request, value any) bool {
	media, _, err := mime.ParseMediaType(r.Header.Get("Content-Type"))
	if err != nil || media != "application/json" {
		Fail(w, r, 415, "UNSUPPORTED_MEDIA_TYPE", "Content-Type must be application/json", nil)
		return false
	}
	r.Body = http.MaxBytesReader(w, r.Body, MaxBodyBytes)
	dec := json.NewDecoder(r.Body)
	dec.DisallowUnknownFields()
	if err = dec.Decode(value); err != nil {
		decodeFailure(w, r, err)
		return false
	}
	var extra any
	if err = dec.Decode(&extra); err != io.EOF {
		if err == nil {
			err = errors.New("trailing JSON")
		}
		decodeFailure(w, r, err)
		return false
	}
	return true
}

func decodeFailure(w http.ResponseWriter, r *http.Request, err error) {
	var large *http.MaxBytesError
	if errors.As(err, &large) {
		Fail(w, r, 413, "BODY_TOO_LARGE", "JSON body exceeds the 64 KiB limit", nil)
		return
	}
	Fail(w, r, 400, "INVALID_JSON", "Expected exactly one JSON object with known fields and correct types", nil)
}

func LoadConfig() (Config, error) {
	c := Config{Address: os.Getenv("HTTP_ADDR"), Token: os.Getenv("VMS_API_TOKEN")}
	if c.Address == "" {
		c.Address = ":8080"
	}
	_, port, err := net.SplitHostPort(c.Address)
	n, e := strconv.Atoi(port)
	if err != nil || e != nil || n < 1 || n > 65535 {
		return c, errors.New("HTTP_ADDR must contain a host and port from 1 to 65535, for example :8080")
	}
	return c, nil
}

func Main(build func(string, *slog.Logger) (*API, error)) int {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	c, err := LoadConfig()
	if err != nil {
		logger.Error("configuration_error", "error", err.Error())
		return 2
	}
	if len(os.Args) == 2 && os.Args[1] == "--healthcheck" {
		host, port, _ := net.SplitHostPort(c.Address)
		if host == "" || host == "0.0.0.0" || host == "::" {
			host = "127.0.0.1"
		}
		client := http.Client{Timeout: 2 * time.Second}
		r, e := client.Get("http://" + net.JoinHostPort(host, port) + "/health/ready")
		if e != nil {
			return 1
		}
		defer r.Body.Close()
		if r.StatusCode != 200 {
			return 1
		}
		return 0
	}
	if len(os.Args) != 1 {
		logger.Error("unsupported_arguments")
		return 2
	}
	api, err := build(c.Token, logger)
	if err != nil {
		logger.Error("configuration_error", "error", err.Error())
		return 2
	}
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	listener, err := net.Listen("tcp", c.Address)
	if err != nil {
		logger.Error("listen_error", "error", err.Error())
		return 1
	}
	srv := &http.Server{Handler: api, ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 10 * time.Second, WriteTimeout: 15 * time.Second, IdleTimeout: 60 * time.Second, MaxHeaderBytes: 16 << 10}
	done := make(chan error, 1)
	go func() { done <- srv.Serve(listener) }()
	logger.Info("api_started", "address", listener.Addr().String(), "stage", api.manifest.Stage)
	select {
	case err = <-done:
		if !errors.Is(err, http.ErrServerClosed) {
			logger.Error("serve_error", "error", err.Error())
			return 1
		}
		return 0
	case <-ctx.Done():
		api.BeginDrain()
		shutdown, stop := context.WithTimeout(context.Background(), 5*time.Second)
		defer stop()
		if err = srv.Shutdown(shutdown); err != nil {
			_ = srv.Close()
			logger.Error("shutdown_error", "error", err.Error())
			return 1
		}
		logger.Info("api_stopped")
		return 0
	}
}
