package app

import (
	"bytes"
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/sha256"
	"crypto/tls"
	"crypto/x509"
	"encoding/hex"
	"io"
	"log/slog"
	"math/big"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
	"vms.local/platform/camera/internal/storage"
)

type managementTestTx struct{ pgx.Tx }
type managementCertificates struct {
	server, client, other tls.Certificate
	roots                 *x509.CertPool
}

func managementCerts(t *testing.T) managementCertificates {
	t.Helper()
	now := time.Now()
	caKey, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal("fixture CA failed")
	}
	ca := &x509.Certificate{SerialNumber: big.NewInt(1), NotBefore: now.Add(-time.Minute), NotAfter: now.Add(time.Hour), IsCA: true, BasicConstraintsValid: true, KeyUsage: x509.KeyUsageCertSign | x509.KeyUsageDigitalSignature}
	caRaw, err := x509.CreateCertificate(rand.Reader, ca, ca, &caKey.PublicKey, caKey)
	if err != nil {
		t.Fatal("fixture CA failed")
	}
	ca, err = x509.ParseCertificate(caRaw)
	if err != nil {
		t.Fatal("fixture CA failed")
	}
	roots := x509.NewCertPool()
	roots.AddCert(ca)
	issue := func(serial int64, server bool) tls.Certificate {
		key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
		if err != nil {
			t.Fatal("fixture key failed")
		}
		cert := &x509.Certificate{SerialNumber: big.NewInt(serial), NotBefore: now.Add(-time.Minute), NotAfter: now.Add(time.Hour), BasicConstraintsValid: true, KeyUsage: x509.KeyUsageDigitalSignature, ExtKeyUsage: []x509.ExtKeyUsage{x509.ExtKeyUsageClientAuth}}
		if server {
			cert.DNSNames = []string{"credential-http"}
			cert.IPAddresses = []net.IP{net.ParseIP("127.0.0.1")}
			cert.ExtKeyUsage = []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth}
		}
		raw, err := x509.CreateCertificate(rand.Reader, cert, ca, &key.PublicKey, caKey)
		if err != nil {
			t.Fatal("fixture certificate failed")
		}
		leaf, err := x509.ParseCertificate(raw)
		if err != nil {
			t.Fatal("fixture certificate failed")
		}
		return tls.Certificate{Certificate: [][]byte{raw, caRaw}, PrivateKey: key, Leaf: leaf}
	}
	return managementCertificates{issue(2, true), issue(3, false), issue(4, false), roots}
}
func managementGrantFixture(c tls.Certificate) CredentialManagementGrant {
	sum := sha256.Sum256(c.Certificate[0])
	return CredentialManagementGrant{hex.EncodeToString(sum[:]), "scope-1", "subject-1", []string{"camera-1"}}
}
func managementContext(p *CredentialManagementPolicy, c tls.Certificate) context.Context {
	r := credentialVersionRequest("GET", credentialVersionPath, "")
	r.TLS.PeerCertificates = []*x509.Certificate{c.Leaf}
	r.TLS.VerifiedChains = [][]*x509.Certificate{{c.Leaf}}
	return context.WithValue(r.Context(), managementContextKey{}, p.peer(r))
}
func TestCredentialManagementConfiguration(t *testing.T) {
	c := managementCerts(t)
	g := managementGrantFixture(c.client)
	for _, mutate := range []func(*CredentialManagementGrant){
		func(g *CredentialManagementGrant) { g.CertificateSHA256 = strings.Repeat("A", 64) }, func(g *CredentialManagementGrant) { g.CertificateSHA256 = "short" },
		func(g *CredentialManagementGrant) { g.ScopeID = "bad/id" }, func(g *CredentialManagementGrant) { g.PrincipalID = "bad/id" },
		func(g *CredentialManagementGrant) { g.DeviceIDs = nil }, func(g *CredentialManagementGrant) { g.DeviceIDs = []string{"*"} }, func(g *CredentialManagementGrant) { g.DeviceIDs = []string{"camera-1", "camera-1"} },
	} {
		bad := g
		mutate(&bad)
		if p, err := NewCredentialManagementPolicy([]CredentialManagementGrant{bad}); p != nil || err == nil {
			t.Fatal("invalid grant accepted")
		}
	}
	if _, err := NewCredentialManagementPolicy([]CredentialManagementGrant{g, g}); err == nil {
		t.Fatal("duplicate identity accepted")
	}
	p, err := NewCredentialManagementPolicy([]CredentialManagementGrant{g})
	if err != nil {
		t.Fatal(err)
	}
	g.DeviceIDs[0] = "other-device"
	ctx := managementContext(p, c.client)
	access := storage.CredentialAccess{ScopeID: "scope-1", PrincipalID: "subject-1", DeviceID: "camera-1", CredentialID: "credential-1", Operation: "MANAGE", Version: 1}
	if ok, err := p.authorize(ctx, managementTestTx{}, access); !ok || err != nil {
		t.Fatal("configuration slice aliased")
	}
	if (&CredentialManagementPolicy{}).Replace(nil) == nil {
		t.Fatal("uninitialized policy accepted")
	}
}
func TestCredentialManagementVerifiedPeerAndScope(t *testing.T) {
	c := managementCerts(t)
	p, _ := NewCredentialManagementPolicy([]CredentialManagementGrant{managementGrantFixture(c.client)})
	ctx := managementContext(p, c.client)
	if s, u, ok, err := p.resolve(ctx); s != "scope-1" || u != "subject-1" || !ok || err != nil {
		t.Fatal("principal not bound")
	}
	a := storage.CredentialAccess{ScopeID: "scope-1", PrincipalID: "subject-1", DeviceID: "camera-1", CredentialID: "credential-1", Operation: "MANAGE", Version: 1}
	if ok, err := p.authorize(ctx, managementTestTx{}, a); !ok || err != nil {
		t.Fatal("configured access rejected")
	}
	for _, change := range []func(*storage.CredentialAccess){func(a *storage.CredentialAccess) { a.ScopeID = "scope-2" }, func(a *storage.CredentialAccess) { a.PrincipalID = "spoofed" }, func(a *storage.CredentialAccess) { a.DeviceID = "other-device" }, func(a *storage.CredentialAccess) { a.Operation = "REFERENCE" }, func(a *storage.CredentialAccess) { a.Version = -1 }, func(a *storage.CredentialAccess) { a.CredentialID = "bad/id" }} {
		bad := a
		change(&bad)
		if ok, _ := p.authorize(ctx, managementTestTx{}, bad); ok {
			t.Fatal("access widened")
		}
	}
	if ok, err := p.authorize(ctx, nil, a); ok || err == nil {
		t.Fatal("transaction required")
	}
	other, _ := NewCredentialManagementPolicy([]CredentialManagementGrant{managementGrantFixture(c.client)})
	for _, context := range []context.Context{nil, context.Background(), managementContext(p, c.other), managementContext(other, c.client)} {
		if ok, _ := p.authorize(context, managementTestTx{}, a); ok {
			t.Fatal("untrusted context accepted")
		}
	}
}
func TestCredentialManagementRejectsUnverifiedPeer(t *testing.T) {
	c := managementCerts(t)
	p, _ := NewCredentialManagementPolicy([]CredentialManagementGrant{managementGrantFixture(c.client)})
	for _, change := range []func(*http.Request){func(r *http.Request) { r.TLS = nil }, func(r *http.Request) { r.TLS.HandshakeComplete = false }, func(r *http.Request) { r.TLS.VerifiedChains = nil }, func(r *http.Request) { r.TLS.PeerCertificates = nil }, func(r *http.Request) { r.TLS.VerifiedChains[0][0] = c.other.Leaf }, func(r *http.Request) {
		bad := *c.client.Leaf
		bad.NotAfter = time.Now().Add(-time.Second)
		r.TLS.PeerCertificates[0] = &bad
		r.TLS.VerifiedChains[0][0] = &bad
	}} {
		r := credentialVersionRequest("GET", credentialVersionPath, "")
		r.TLS.PeerCertificates = []*x509.Certificate{c.client.Leaf}
		r.TLS.VerifiedChains = [][]*x509.Certificate{{c.client.Leaf}}
		r.Header.Set("X-Client-Certificate", string(c.client.Certificate[0]))
		change(r)
		if peer := p.peer(r); peer.policy != nil {
			t.Fatal("unverified or expired peer accepted")
		}
	}
}
func TestCredentialManagementReplacementAndRecheck(t *testing.T) {
	c := managementCerts(t)
	g := managementGrantFixture(c.client)
	p, _ := NewCredentialManagementPolicy([]CredentialManagementGrant{g})
	ctx := managementContext(p, c.client)
	a := storage.CredentialAccess{ScopeID: "scope-1", PrincipalID: "subject-1", DeviceID: "camera-1", CredentialID: "credential-1", Operation: "MANAGE", Version: 0}
	if err := p.Replace([]CredentialManagementGrant{{CertificateSHA256: "bad"}}); err == nil {
		t.Fatal("invalid replacement accepted")
	}
	if ok, _ := p.authorize(ctx, managementTestTx{}, a); !ok {
		t.Fatal("invalid replacement lost policy")
	}
	if err := p.Replace([]CredentialManagementGrant{g}); err != nil {
		t.Fatal(err)
	}
	if ok, _ := p.authorize(ctx, managementTestTx{}, a); ok {
		t.Fatal("in-flight stale grant accepted")
	}
	if ok, _ := p.authorize(managementContext(p, c.client), managementTestTx{}, a); !ok {
		t.Fatal("fresh grant rejected")
	}
	if p.Replace(nil) != nil {
		t.Fatal("deny-all replacement failed")
	}
	if _, _, ok, _ := p.resolve(managementContext(p, c.client)); ok {
		t.Fatal("revoked identity accepted")
	}
}
func TestCredentialManagementConcurrentReplacement(t *testing.T) {
	c := managementCerts(t)
	g := managementGrantFixture(c.client)
	p, _ := NewCredentialManagementPolicy([]CredentialManagementGrant{g})
	var wg sync.WaitGroup
	for i := 0; i < 4; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for j := 0; j < 50; j++ {
				ctx := managementContext(p, c.client)
				_, _, _, _ = p.resolve(ctx)
				_, _ = p.authorize(ctx, managementTestTx{}, storage.CredentialAccess{ScopeID: "scope-1", PrincipalID: "subject-1", DeviceID: "camera-1", CredentialID: "credential-1", Operation: "MANAGE", Version: 1})
			}
		}()
	}
	for j := 0; j < 50; j++ {
		if p.Replace([]CredentialManagementGrant{g}) != nil {
			t.Fatal("replacement failed")
		}
	}
	wg.Wait()
}
func managementServer(t *testing.T, handler http.Handler, c managementCertificates) (*httptest.Server, *http.Client) {
	t.Helper()
	s := httptest.NewUnstartedServer(handler)
	s.Config.ErrorLog = nil
	s.TLS = &tls.Config{Certificates: []tls.Certificate{c.server}, ClientCAs: c.roots, ClientAuth: tls.RequireAndVerifyClientCert, MinVersion: tls.VersionTLS12}
	s.StartTLS()
	t.Cleanup(s.Close)
	tr := &http.Transport{TLSClientConfig: &tls.Config{RootCAs: c.roots, Certificates: []tls.Certificate{c.client}, ServerName: "credential-http", MinVersion: tls.VersionTLS12}}
	t.Cleanup(tr.CloseIdleConnections)
	return s, &http.Client{Transport: tr, Timeout: 10 * time.Second}
}
func TestCredentialManagementExplicitRegistrationAndTLS(t *testing.T) {
	c := managementCerts(t)
	p, _ := NewCredentialManagementPolicy([]CredentialManagementGrant{managementGrantFixture(c.client)})
	var logs bytes.Buffer
	a, _ := New(credentialToken, slog.New(slog.NewJSONHandler(&logs, nil)))
	if h, err := RegisterCredentialManagement(a, &storage.CredentialStore{}, p, nil); h != nil || err == nil {
		t.Fatal("default unused guard installed")
	}
	credentialStatus(t, a, credentialVersionRequest("GET", credentialVersionPath, ""), 404, "NOT_FOUND")
	h, err := RegisterCredentialManagement(a, &storage.CredentialStore{}, p, credentialUnused)
	if err != nil {
		t.Fatal(err)
	}
	s, client := managementServer(t, h, c)
	r, _ := http.NewRequest("GET", s.URL+credentialVersionPath, nil)
	r.Header.Set("Authorization", "Bearer "+credentialToken)
	r.Header.Set("X-Scope-ID", "spoofed")
	res, err := client.Do(r)
	if err != nil {
		t.Fatal("actual mTLS request failed")
	}
	res.Body.Close()
	if res.StatusCode != 503 {
		t.Fatal("concrete unadmitted store accepted or trusted peer denied")
	}
	// A CA-valid certificate is still denied unless its exact DER leaf has a
	// configured principal grant. Possessing the service bearer is insufficient.
	otherTransport := client.Transport.(*http.Transport).Clone()
	otherTransport.TLSClientConfig = otherTransport.TLSClientConfig.Clone()
	otherTransport.TLSClientConfig.Certificates = []tls.Certificate{c.other}
	otherClient := &http.Client{Transport: otherTransport, Timeout: 5 * time.Second}
	t.Cleanup(otherTransport.CloseIdleConnections)
	res, err = otherClient.Do(r)
	if err != nil {
		t.Fatal("CA-valid unconfigured peer test failed")
	}
	_, _ = io.Copy(io.Discard, res.Body)
	res.Body.Close()
	if res.StatusCode != 403 {
		t.Fatal("unconfigured mTLS peer accepted")
	}
	noCertTransport := otherTransport.Clone()
	noCertTransport.TLSClientConfig = noCertTransport.TLSClientConfig.Clone()
	noCertTransport.TLSClientConfig.Certificates = nil
	t.Cleanup(noCertTransport.CloseIdleConnections)
	res, err = (&http.Client{Transport: noCertTransport, Timeout: 5 * time.Second}).Do(r)
	if res != nil {
		res.Body.Close()
	}
	if err == nil {
		t.Fatal("missing mTLS certificate accepted")
	}
	p.Replace(nil)
	res, err = client.Do(r)
	if err != nil {
		t.Fatal("mTLS revoked request failed")
	}
	res.Body.Close()
	if res.StatusCode != 403 {
		t.Fatal("revoked peer accepted")
	}
	credentialSafe(t, logs.String())
}
