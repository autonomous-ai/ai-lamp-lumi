package openclaw

import (
	"embed"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"
)

//go:embed resources/SOUL.md
var soulFS embed.FS

const (
	skillsBaseURL = "https://storage.googleapis.com/s3-autonomous-upgrade-3/lumi/skills"

	agentsMDMandatoryMarker = "<!-- LUMI DO NOT REMOVE -->"
	agentsMDBlock           = `<!-- LUMI DO NOT REMOVE -->
**MANDATORY:** Before ANY reply, scan all skill directories under ` + "`skills/`" + ` in your workspace — read each SKILL.md and follow their instructions.

---`
)

// skills is the list of skill names available on CDN.
var skills = []string{
	"audio",
	"camera",
	"display",
	"emotion",
	"led-control",
	"scene",
	"scheduling",
	"sensing",
	"servo-control",
}

// EnsureOnboarding seeds SOUL.md, downloads skills, and injects the mandatory
// block into workspace/AGENTS.md so OpenClaw scans the skills directory.
// IDENTITY.md is managed by OpenClaw itself (created during openclaw onboard).
func (s *Service) EnsureOnboarding() error {
	workspace := filepath.Join(s.config.OpenclawConfigDir, "workspace")
	if err := os.MkdirAll(workspace, 0755); err != nil {
		return fmt.Errorf("create workspace dir: %w", err)
	}

	needRestart := false

	// Seed SOUL.md from embedded binary
	seedFile(soulFS, "resources/SOUL.md", filepath.Join(workspace, "SOUL.md"))

	// Download skills from CDN
	skillsDir := filepath.Join(workspace, "skills")
	if err := os.MkdirAll(skillsDir, 0755); err != nil {
		return fmt.Errorf("create skills dir: %w", err)
	}
	for _, name := range skills {
		dir := filepath.Join(skillsDir, name)
		if err := os.MkdirAll(dir, 0755); err != nil {
			log.Printf("[onboarding] mkdir %s: %v", dir, err)
			continue
		}
		dst := filepath.Join(dir, "SKILL.md")
		url := fmt.Sprintf("%s/%s/SKILL.md", skillsBaseURL, name)
		if err := downloadFile(url, dst); err != nil {
			log.Printf("[onboarding] download skill %s: %v", name, err)
			continue
		}
		log.Printf("[onboarding] seeded skill %s", name)
	}

	// Ensure AGENTS.md has mandatory block
	modified, err := s.ensureAgentsMDBlock()
	if err != nil {
		return fmt.Errorf("ensure AGENTS.md block: %w", err)
	}
	if modified {
		needRestart = true
	}

	// Restart OpenClaw if AGENTS.md was modified so the new session picks it up
	if needRestart {
		log.Println("[onboarding] restarting OpenClaw to pick up AGENTS.md changes...")
		if err := restartOpenclawGateway(); err != nil {
			return fmt.Errorf("restart openclaw after onboarding: %w", err)
		}
		log.Println("[onboarding] OpenClaw restarted successfully")
	}

	return nil
}

// ensureAgentsMDBlock injects the mandatory skills block into AGENTS.md.
// Returns true if the file was modified.
func (s *Service) ensureAgentsMDBlock() (bool, error) {
	agentsFile := filepath.Join(s.config.OpenclawConfigDir, "workspace", "AGENTS.md")

	content, err := os.ReadFile(agentsFile)
	if err != nil && !os.IsNotExist(err) {
		return false, fmt.Errorf("read AGENTS.md: %w", err)
	}

	text := string(content)

	// Already has the block → skip
	if strings.Contains(text, agentsMDMandatoryMarker) {
		log.Println("[onboarding] AGENTS.md already has mandatory block, skipping")
		return false, nil
	}

	// Find "Your workspace" line and inject block below it
	lines := strings.Split(text, "\n")
	var result []string
	injected := false

	for _, line := range lines {
		result = append(result, line)
		if !injected && strings.Contains(strings.ToLower(line), "your workspace") {
			result = append(result, agentsMDBlock)
			injected = true
		}
	}

	// If "Your workspace" not found, prepend to top of file
	if !injected {
		log.Println("[onboarding] 'Your workspace' not found in AGENTS.md, prepending block")
		result = append([]string{agentsMDBlock, ""}, result...)
	}

	output := strings.Join(result, "\n")
	if err := os.WriteFile(agentsFile, []byte(output), 0644); err != nil {
		return false, fmt.Errorf("write AGENTS.md: %w", err)
	}

	log.Printf("[onboarding] injected mandatory block into %s", agentsFile)
	return true, nil
}

// downloadFile fetches url and writes it to dst, overwriting any existing file.
func downloadFile(url, dst string) error {
	client := &http.Client{Timeout: 30 * time.Second}
	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		return err
	}
	req.Header.Set("Cache-Control", "no-cache")
	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("HTTP %d", resp.StatusCode)
	}
	f, err := os.Create(dst)
	if err != nil {
		return err
	}
	defer f.Close()
	_, err = io.Copy(f, resp.Body)
	return err
}

// seedFile writes the embedded file to dst, always overwriting.
func seedFile(efs embed.FS, src, dst string) {
	data, err := efs.ReadFile(src)
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
