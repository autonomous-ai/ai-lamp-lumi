package openclaw

import (
	"embed"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
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
	hooksBaseURL  = "https://storage.googleapis.com/s3-autonomous-upgrade-3/lumi/hooks"

	agentsMDMandatoryMarker = "<!-- LUMI DO NOT REMOVE -->"
	agentsMDBlock           = `<!-- LUMI DO NOT REMOVE -->
**MANDATORY:** Before ANY reply, scan all skill directories under ` + "`skills/`" + ` and all hook directories under ` + "`hooks/`" + ` in your workspace — read each SKILL.md / HOOK.md and follow their instructions.

**Version check:** ` + "`lumi-server --version`" + ` (Lumi), ` + "`openclaw --version`" + ` (OpenClaw), ` + "`curl -s http://127.0.0.1:5001/version`" + ` (LeLamp).

---`
)

// hooks is the list of hook names available on CDN.
// Each hook has HOOK.md (metadata) and handler.ts (logic).
var hooks = []string{
	"camera-inject",
	"emotion-acknowledge",
}

// skills is the list of skill names available on CDN.
var skills = []string{
	"audio",
	"camera",
	"display",
	"emotion",
	"face-enroll",
	"led-control",
	"music",
	"scene",
	"scheduling",
	"sensing",
	"servo-control",
	"voice",
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
			slog.Error("mkdir failed", "component", "onboarding", "dir", dir, "error", err)
			continue
		}
		dst := filepath.Join(dir, "SKILL.md")
		url := fmt.Sprintf("%s/%s/SKILL.md", skillsBaseURL, name)
		if err := downloadFile(url, dst); err != nil {
			slog.Error("download skill failed", "component", "onboarding", "skill", name, "error", err)
			continue
		}
		slog.Info("seeded skill", "component", "onboarding", "skill", name)
	}

	// Download hooks from CDN
	hooksDir := filepath.Join(workspace, "hooks")
	if err := os.MkdirAll(hooksDir, 0755); err != nil {
		return fmt.Errorf("create hooks dir: %w", err)
	}
	hookFiles := []string{"HOOK.md", "handler.ts"}
	for _, name := range hooks {
		dir := filepath.Join(hooksDir, name)
		if err := os.MkdirAll(dir, 0755); err != nil {
			slog.Error("mkdir failed", "component", "onboarding", "dir", dir, "error", err)
			continue
		}
		for _, file := range hookFiles {
			dst := filepath.Join(dir, file)
			url := fmt.Sprintf("%s/%s/%s", hooksBaseURL, name, file)
			if err := downloadFile(url, dst); err != nil {
				slog.Error("download hook file failed", "component", "onboarding", "hook", name, "file", file, "error", err)
				continue
			}
		}
		slog.Info("seeded hook", "component", "onboarding", "hook", name)
	}

	// Ensure AGENTS.md has mandatory block
	modified, err := s.ensureAgentsMDBlock()
	if err != nil {
		return fmt.Errorf("ensure AGENTS.md block: %w", err)
	}
	if modified {
		needRestart = true
	}

	// Ensure all hooks are registered in openclaw.json hooks.internal.entries
	if hooksAdded, err := s.ensureHooksRegistered(hooks); err != nil {
		slog.Error("ensure hooks registered failed", "component", "onboarding", "error", err)
	} else if hooksAdded {
		needRestart = true
	}

	// Restart OpenClaw if anything changed so the new session picks it up
	if needRestart {
		slog.Info("restarting OpenClaw to pick up changes", "component", "onboarding")
		if err := restartOpenclawGateway(); err != nil {
			return fmt.Errorf("restart openclaw after onboarding: %w", err)
		}
		slog.Info("OpenClaw restarted successfully", "component", "onboarding")
	}

	return nil
}

// ensureHooksRegistered adds any missing hooks to openclaw.json hooks.internal.entries.
// Returns true if the file was modified.
func (s *Service) ensureHooksRegistered(hookNames []string) (bool, error) {
	configPath := filepath.Join(s.config.OpenclawConfigDir, "openclaw.json")
	configBytes, err := os.ReadFile(configPath)
	if err != nil {
		return false, fmt.Errorf("read openclaw.json: %w", err)
	}
	var configData map[string]interface{}
	if err := json.Unmarshal(configBytes, &configData); err != nil {
		return false, fmt.Errorf("parse openclaw.json: %w", err)
	}

	hooksMap := ensureMap(configData, "hooks")
	internalMap := ensureMap(hooksMap, "internal")
	if _, ok := internalMap["enabled"]; !ok {
		internalMap["enabled"] = true
	}
	entriesMap := ensureMap(internalMap, "entries")

	changed := false
	for _, name := range hookNames {
		if _, exists := entriesMap[name]; !exists {
			entriesMap[name] = map[string]interface{}{"enabled": true}
			changed = true
			slog.Info("registered hook in openclaw.json", "component", "onboarding", "hook", name)
		}
	}
	if !changed {
		return false, nil
	}

	outBytes, err := json.MarshalIndent(configData, "", "  ")
	if err != nil {
		return false, fmt.Errorf("marshal openclaw.json: %w", err)
	}
	if err := os.WriteFile(configPath, outBytes, 0600); err != nil {
		return false, fmt.Errorf("write openclaw.json: %w", err)
	}
	return true, nil
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

	// Already has the exact current block → skip
	if strings.Contains(text, agentsMDBlock) {
		slog.Debug("AGENTS.md already has current mandatory block, skipping", "component", "onboarding")
		return false, nil
	}

	// Remove old block (with or without marker) before injecting current version
	if strings.Contains(text, agentsMDMandatoryMarker) {
		text = stripMarkedBlock(text)
	} else {
		text = stripLegacyMandatoryBlock(text)
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
		slog.Debug("'Your workspace' not found in AGENTS.md, prepending block", "component", "onboarding")
		result = append([]string{agentsMDBlock, ""}, result...)
	}

	output := strings.Join(result, "\n")
	if err := os.WriteFile(agentsFile, []byte(output), 0644); err != nil {
		return false, fmt.Errorf("write AGENTS.md: %w", err)
	}

	slog.Info("injected mandatory block into AGENTS.md", "component", "onboarding", "path", agentsFile)
	return true, nil
}

// stripMarkedBlock removes the block between <!-- LUMI DO NOT REMOVE --> and the next --- separator.
func stripMarkedBlock(text string) string {
	lines := strings.Split(text, "\n")
	var cleaned []string
	skip := false
	for _, line := range lines {
		trimmed := strings.TrimSpace(line)
		if trimmed == agentsMDMandatoryMarker {
			skip = true
			continue
		}
		if skip && trimmed == "---" {
			skip = false
			continue
		}
		if skip {
			continue
		}
		cleaned = append(cleaned, line)
	}
	return strings.Join(cleaned, "\n")
}

// stripLegacyMandatoryBlock removes the old MANDATORY block that was injected
// before the <!-- LUMI DO NOT REMOVE --> marker was introduced.
func stripLegacyMandatoryBlock(text string) string {
	lines := strings.Split(text, "\n")
	var cleaned []string
	skip := false
	for _, line := range lines {
		trimmed := strings.TrimSpace(line)
		// Detect start of legacy block: starts with **MANDATORY:** but no marker above
		if !skip && strings.HasPrefix(trimmed, "**MANDATORY:**") {
			skip = true
			continue
		}
		// End of legacy block: next non-empty line that doesn't look like continuation
		if skip {
			if trimmed == "" || trimmed == "---" {
				skip = false
				// Keep the separator/blank line
				cleaned = append(cleaned, line)
			}
			// Skip continuation lines of the old block
			continue
		}
		cleaned = append(cleaned, line)
	}
	return strings.Join(cleaned, "\n")
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
		slog.Error("read embedded file failed", "component", "onboarding", "src", src, "error", err)
		return
	}
	if err := os.WriteFile(dst, data, 0644); err != nil {
		slog.Error("write file failed", "component", "onboarding", "dst", dst, "error", err)
		return
	}
	slog.Info("seeded file", "component", "onboarding", "file", filepath.Base(dst))
}
