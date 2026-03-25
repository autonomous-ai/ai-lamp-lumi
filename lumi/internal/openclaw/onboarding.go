package openclaw

import (
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"
)

const (
	onboardingSkillURL = "https://raw.githubusercontent.com/autonomous-ecm/intern-skills/main/autonomous-intern-onboarding/SKILL.md"
	onboardingSkillRel = "autonomous-intern-onboarding/SKILL.md"

	agentsMDMandatoryMarker = "<!-- DO NOT REMOVE -->"
	agentsMDBlock           = "<!-- DO NOT REMOVE -->\n**MANDATORY:** Before ANY reply, check `skills/autonomous-intern-onboarding/` — read its SKILL.md and follow instructions.\n\n---"

	onboardingMaxRetries = 3
	onboardingRetryDelay = 2 * time.Second
)

// EnsureOnboardingSkill downloads the onboarding skill SKILL.md if missing
// and injects the mandatory block into workspace/AGENTS.md.
func (s *Service) EnsureOnboardingSkill() error {
	skillsDir := filepath.Join(s.config.OpenclawConfigDir, "workspace", "skills")
	skillFile := filepath.Join(skillsDir, onboardingSkillRel)

	needRestart := false

	// Step 1: Download SKILL.md if missing
	if _, err := os.Stat(skillFile); os.IsNotExist(err) {
		if err := s.downloadOnboardingSkill(skillFile); err != nil {
			return err
		}
		needRestart = true
	} else {
		log.Println("[onboarding] skill already exists, skipping download")
	}

	// Step 2: Ensure AGENTS.md has mandatory block
	modified, err := s.ensureAgentsMDBlock()
	if err != nil {
		return fmt.Errorf("ensure AGENTS.md block: %w", err)
	}
	if modified {
		needRestart = true
	}

	// Step 3: Restart OpenClaw if anything changed
	// Restarting the gateway forces OpenClaw to create a new session,
	// which picks up the updated AGENTS.md. Old sessions are preserved.
	if needRestart {
		log.Println("[onboarding] restarting OpenClaw to pick up changes...")
		if err := restartOpenclawGateway(); err != nil {
			return fmt.Errorf("restart openclaw after onboarding setup: %w", err)
		}
		log.Println("[onboarding] OpenClaw restarted successfully")
	}

	return nil
}

func (s *Service) downloadOnboardingSkill(destPath string) error {
	log.Println("[onboarding] skill not found, downloading from GitHub...")

	var lastErr error
	for attempt := 1; attempt <= onboardingMaxRetries; attempt++ {
		body, err := fetchURL(onboardingSkillURL)
		if err != nil {
			lastErr = err
			log.Printf("[onboarding] download attempt %d/%d failed: %v", attempt, onboardingMaxRetries, err)
			if attempt < onboardingMaxRetries {
				time.Sleep(onboardingRetryDelay)
			}
			continue
		}

		if err := os.MkdirAll(filepath.Dir(destPath), 0755); err != nil {
			return fmt.Errorf("create onboarding skill dir: %w", err)
		}
		if err := os.WriteFile(destPath, body, 0644); err != nil {
			return fmt.Errorf("write onboarding skill: %w", err)
		}

		log.Printf("[onboarding] skill installed at %s", destPath)
		return nil
	}

	return fmt.Errorf("download onboarding skill after %d retries: %w", onboardingMaxRetries, lastErr)
}

// ensureAgentsMDBlock returns true if AGENTS.md was modified.
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

func fetchURL(url string) ([]byte, error) {
	resp, err := http.Get(url)
	if err != nil {
		return nil, fmt.Errorf("GET %s: %w", url, err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("GET %s: HTTP %d", url, resp.StatusCode)
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("read body from %s: %w", url, err)
	}

	return body, nil
}
