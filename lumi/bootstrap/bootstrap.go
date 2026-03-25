package bootstrap

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"regexp"
	"strings"
	"syscall"
	"time"

	"github.com/gin-gonic/gin"

	"go-lamp.autonomous.ai/bootstrap/config"
	"go-lamp.autonomous.ai/bootstrap/state"
	"go-lamp.autonomous.ai/domain"
	"go-lamp.autonomous.ai/lib/core/system"
)

// semverRe captures the first semver-like token (e.g. 2026.3.8 or v1.2.3-beta).
var semverRe = regexp.MustCompile(`(\d+\.\d+\.\d+(?:[-+._][0-9A-Za-z.-]+)?)`)

// Bootstrap is the simplified OTA worker.
type Bootstrap struct {
	cfg    *config.Config
	client *http.Client
	state  *state.State
}

// ProvideServer creates a Bootstrap from config.
func ProvideServer() (*Bootstrap, error) {
	cfg := config.LoadOrDefault()
	if strings.TrimSpace(cfg.MetadataURL) == "" {
		return nil, fmt.Errorf("metadata URL is required")
	}
	st, err := state.Load(cfg.StateFile)
	if err != nil {
		return nil, fmt.Errorf("load state: %w", err)
	}
	return &Bootstrap{
		cfg:    cfg,
		client: &http.Client{Timeout: 20 * time.Second},
		state:  st,
	}, nil
}

// Serve runs the gin HTTP server as the main loop, with OTA checks in a background goroutine.
// Handles SIGINT/SIGTERM for graceful shutdown.
func (b *Bootstrap) Serve() error {
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGINT, syscall.SIGTERM)
	defer cancel()

	pollInterval, err := time.ParseDuration(b.cfg.PollInterval)
	if err != nil {
		return fmt.Errorf("parse poll interval: %w", err)
	}
	log.Printf("bootstrap: started (metadata_url=%s interval=%s)", b.cfg.MetadataURL, b.cfg.PollInterval)

	// Run OTA check loop in background.
	go b.checkLoop(ctx, pollInterval)

	// Gin healthcheck as main serve.
	gin.SetMode(gin.ReleaseMode)
	r := gin.New()
	r.Use(gin.Recovery())
	r.GET("/health", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"status": "ok"})
	})

	port := b.cfg.HttpPort
	srv := &http.Server{Addr: fmt.Sprintf(":%d", port), Handler: r}
	go func() {
		<-ctx.Done()
		shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer shutdownCancel()
		_ = srv.Shutdown(shutdownCtx)
	}()
	log.Printf("bootstrap: healthcheck listening on :%d", port)
	if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		return fmt.Errorf("healthcheck server: %w", err)
	}
	return nil
}

// checkLoop runs OTA checks on a ticker in the background.
func (b *Bootstrap) checkLoop(ctx context.Context, pollInterval time.Duration) {
	if err := b.checkOnce(ctx); err != nil {
		log.Printf("bootstrap: initial check failed: %v", err)
	}

	ticker := time.NewTicker(pollInterval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			if err := b.checkOnce(ctx); err != nil {
				log.Printf("bootstrap: check failed: %v", err)
			}
		}
	}
}

// checkOnce fetches metadata and reconciles all components.
func (b *Bootstrap) checkOnce(ctx context.Context) error {
	meta, err := b.fetchMetadata(ctx)
	if err != nil {
		return err
	}
	if len(meta) == 0 {
		log.Printf("bootstrap: empty metadata from %s", b.cfg.MetadataURL)
		return nil
	}

	changed := false
	for _, key := range []string{domain.OTAKeyLumi, domain.OTAKeyBootstrap, domain.OTAKeyWeb} {
		component, ok := meta[key]
		if !ok {
			continue
		}
		updated, err := b.reconcile(ctx, key, component)
		if err != nil {
			log.Printf("bootstrap: %s reconcile error: %v", key, err)
			continue
		}
		if updated {
			changed = true
		}
	}

	if b.reconcileOpenClawFromNpm(ctx) {
		changed = true
	}

	if changed {
		if err := state.Save(b.cfg.StateFile, b.state); err != nil {
			return fmt.Errorf("save state: %w", err)
		}
	}
	return nil
}

// reconcileOpenClawFromNpm fetches the latest openclaw version from npm and reconciles if needed.
func (b *Bootstrap) reconcileOpenClawFromNpm(ctx context.Context) (changed bool) {
	runCtx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()
	out, err := system.Run(runCtx, "npm", "view", "openclaw", "version")
	if err != nil {
		log.Printf("bootstrap: failed to get latest openclaw version from npm: %v", err)
		return false
	}
	latestVersion := strings.TrimSpace(string(out))
	if latestVersion == "" {
		return false
	}
	updated, err := b.reconcile(ctx, "openclaw", domain.OTAComponent{Version: latestVersion})
	if err != nil {
		log.Printf("bootstrap: openclaw (npm latest) reconcile error: %v", err)
		return false
	}
	return updated
}

// reconcile compares current vs target version and applies update if needed.
func (b *Bootstrap) reconcile(ctx context.Context, key string, target domain.OTAComponent) (bool, error) {
	targetVersion := strings.TrimSpace(target.Version)
	if targetVersion == "" {
		return false, fmt.Errorf("metadata[%s].version is empty", key)
	}

	current := b.detectVersion(ctx, key)
	if current == "" {
		current = b.state.Components[key]
	}

	if current == targetVersion {
		if b.state.Components[key] != targetVersion {
			b.state.Components[key] = targetVersion
			return true, nil
		}
		return false, nil
	}

	log.Printf("bootstrap: update available for %s: current=%q target=%q", key, current, targetVersion)
	if err := b.applyUpdate(ctx, key, target); err != nil {
		return false, err
	}
	log.Printf("bootstrap: %s updated to %s", key, targetVersion)
	b.state.Components[key] = targetVersion
	return true, nil
}

// fetchMetadata fetches OTA metadata JSON from the configured URL.
func (b *Bootstrap) fetchMetadata(ctx context.Context) (domain.OTAMetadata, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, b.cfg.MetadataURL, nil)
	if err != nil {
		return nil, fmt.Errorf("build metadata request: %w", err)
	}
	resp, err := b.client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("fetch metadata %s: %w", b.cfg.MetadataURL, err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("fetch metadata %s: status %s", b.cfg.MetadataURL, resp.Status)
	}
	var meta domain.OTAMetadata
	if err := json.NewDecoder(resp.Body).Decode(&meta); err != nil {
		return nil, fmt.Errorf("decode metadata: %w", err)
	}
	return meta, nil
}

// detectVersion returns the current installed version for a component.
func (b *Bootstrap) detectVersion(ctx context.Context, key string) string {
	runCtx, cancel := context.WithTimeout(ctx, 10*time.Minute)
	defer cancel()

	switch key {
	case domain.OTAKeyLumi:
		out, err := system.Run(runCtx, "lumi-server", "--version")
		if err != nil {
			return ""
		}
		return normalizeVersion(string(out))
	case domain.OTAKeyBootstrap:
		return strings.TrimSpace(config.BootstrapVersion)
	case domain.OTAKeyWeb:
		path := filepath.Join("/usr/share/nginx/html/setup", "VERSION")
		data, err := os.ReadFile(path)
		if err != nil {
			return ""
		}
		return strings.TrimSpace(string(data))
	case domain.OTAKeyOpenClaw:
		out, err := system.Run(runCtx, "openclaw", "--version")
		if err != nil {
			return ""
		}
		return openclawNormalizeVersion(string(out))
	default:
		return ""
	}
}

// applyUpdate runs the appropriate update command for the given component.
func (b *Bootstrap) applyUpdate(ctx context.Context, key string, component domain.OTAComponent) error {
	switch key {
	case domain.OTAKeyLumi, domain.OTAKeyWeb:
		runCtx, cancel := context.WithTimeout(ctx, 10*time.Minute)
		defer cancel()
		out, err := system.Run(runCtx, "software-update", key)
		if err != nil {
			return fmt.Errorf("software-update %s: %w", key, err)
		}
		log.Printf("bootstrap: %s update output: %s", key, out)
		return nil

	case domain.OTAKeyBootstrap:
		// Spawn as detached background process so it survives bootstrap exit.
		log.Printf("bootstrap: spawning background software-update bootstrap")
		if err := system.SpawnBackground("software-update", "bootstrap"); err != nil {
			return fmt.Errorf("spawn software-update bootstrap: %w", err)
		}
		return nil

	case domain.OTAKeyOpenClaw:
		runCtx, cancel := context.WithTimeout(ctx, 10*time.Minute)
		defer cancel()
		version := strings.TrimSpace(component.Version)
		if version == "" {
			version = "latest"
		}
		pkg := fmt.Sprintf("openclaw@%s", version)
		if _, err := system.Run(runCtx, "npm", "install", "-g", pkg); err != nil {
			return fmt.Errorf("npm install %s: %w", pkg, err)
		}
		if err := system.RestartService(runCtx, "openclaw"); err != nil {
			return fmt.Errorf("restart openclaw: %w", err)
		}
		log.Printf("bootstrap: openclaw updated to %s", version)
		return nil

	default:
		return fmt.Errorf("unsupported component %q", key)
	}
}

// openclawNormalizeVersion extracts the version from openclaw --version output (e.g. "OpenClaw 2026.3.8 (3caab92)" -> "2026.3.8").
// Used only for OTAKeyOpenClaw.
func openclawNormalizeVersion(raw string) string {
	line := strings.TrimSpace(strings.TrimRight(raw, "\r\n"))
	if i := strings.IndexByte(line, '\n'); i >= 0 {
		line = strings.TrimSpace(line[:i])
	}
	if loc := semverRe.FindStringSubmatch(line); len(loc) > 1 {
		return loc[1]
	}
	return ""
}

// normalizeVersion extracts a semver-like version from command output (e.g. "1.0.83" or "lumi-server 1.0.83" -> "1.0.83").
// Used for OTAKeyLumi and bootstrap-style version output (lumi-server --version, bootstrap-server --version).
func normalizeVersion(raw string) string {
	line := strings.TrimSpace(strings.TrimRight(raw, "\r\n"))
	if line == "" {
		return ""
	}
	if i := strings.IndexByte(line, '\n'); i >= 0 {
		line = strings.TrimSpace(line[:i])
	}
	if loc := semverRe.FindStringSubmatch(line); len(loc) > 1 {
		return loc[1]
	}
	fields := strings.Fields(line)
	if len(fields) == 0 {
		return ""
	}
	return strings.TrimSpace(fields[len(fields)-1])
}
