package openclaw

import (
	"embed"
	"fmt"
	"log"
	"os"
	"path/filepath"
)

//go:embed resources/SOUL.md
var onboardingFS embed.FS

// EnsureOnboarding seeds SOUL.md into the OpenClaw workspace if it doesn't
// exist yet. Factory default — once created, the user owns it. We never override.
// IDENTITY.md is managed by OpenClaw itself (created during openclaw onboard).
func (s *Service) EnsureOnboarding() error {
	workspace := filepath.Join(s.config.OpenclawConfigDir, "workspace")
	if err := os.MkdirAll(workspace, 0755); err != nil {
		return fmt.Errorf("create workspace dir: %w", err)
	}

	seedFile(onboardingFS, "resources/SOUL.md", filepath.Join(workspace, "SOUL.md"))
	return nil
}

// seedFile writes the embedded file to dst only if dst does not exist.
func seedFile(fs embed.FS, src, dst string) {
	if _, err := os.Stat(dst); err == nil {
		return
	}
	data, err := fs.ReadFile(src)
	if err != nil {
		log.Printf("[onboarding] read embedded %s: %v", src, err)
		return
	}
	if err := os.WriteFile(dst, data, 0644); err != nil {
		log.Printf("[onboarding] write %s: %v", dst, err)
		return
	}
	log.Printf("[onboarding] seeded %s", filepath.Base(dst))
}
