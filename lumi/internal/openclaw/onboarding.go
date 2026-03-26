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

// EnsureOnboarding seeds SOUL.md into the OpenClaw workspace, always overwriting
// to ensure Lumi's personality is applied over any default.
// IDENTITY.md is managed by OpenClaw itself (created during openclaw onboard).
func (s *Service) EnsureOnboarding() error {
	workspace := filepath.Join(s.config.OpenclawConfigDir, "workspace")
	if err := os.MkdirAll(workspace, 0755); err != nil {
		return fmt.Errorf("create workspace dir: %w", err)
	}

	seedFile(onboardingFS, "resources/SOUL.md", filepath.Join(workspace, "SOUL.md"))
	return nil
}

// seedFile writes the embedded file to dst, always overwriting to ensure
// the latest version is applied (e.g. Lumi's SOUL.md replaces OpenClaw default).
func seedFile(fs embed.FS, src, dst string) {
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
