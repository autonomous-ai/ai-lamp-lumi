package openclaw

import (
	"embed"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

//go:embed resources/SOUL.md
var soulFS embed.FS

//go:embed resources/KNOWLEDGE.md
var knowledgeFS embed.FS

const (
	skillsBaseURL = "https://storage.googleapis.com/s3-autonomous-upgrade-3/lumi/skills"
	hooksBaseURL  = "https://storage.googleapis.com/s3-autonomous-upgrade-3/lumi/hooks"

	lumiMandatoryMarker = "<!-- LUMI DO NOT REMOVE -->"

	agentsMDBlock = `<!-- LUMI DO NOT REMOVE -->
**MANDATORY:** Before ANY reply, scan all skill directories under ` + "`skills/`" + ` and all hook directories under ` + "`hooks/`" + ` in your workspace — read each SKILL.md / HOOK.md and follow their instructions.

**Version check:** ` + "`lumi-server --version`" + ` (Lumi), ` + "`openclaw --version`" + ` (OpenClaw), ` + "`curl -s http://127.0.0.1:5001/version`" + ` (LeLamp).

**Session Startup — also read:** ` + "`KNOWLEDGE.md`" + ` (accumulated learnings) in addition to the steps listed below.

**Priority: Skills > Knowledge > History.** When SKILL.md instructions conflict with KNOWLEDGE.md or conversation history, **SKILL.md always wins**. KNOWLEDGE.md is your personal observations — it can be wrong. Skills are the source of truth maintained by the developer. If you notice a conflict, update KNOWLEDGE.md to match the skill, not the other way around.

**Memory:** After each turn on any channel (voice, Telegram, or others) that contains something worth remembering (decisions, bugs, insights, new preferences), write it immediately to ` + "`memory/YYYY-MM-DD.md`" + `. Do not wait for heartbeat — context may be dropped before then.

**Cron format — ALWAYS read Scheduling skill before creating any cron job.** Two valid combos only: (1) ` + "`sessionTarget: \"main\"` + `payload.kind: \"systemEvent\"` + `payload.text`" + `, (2) ` + "`sessionTarget: \"isolated\"` + `payload.kind: \"agentTurn\"` + `payload.message`" + `. Do NOT mix. Do NOT add ` + "`delivery`" + ` field. Do NOT use conversation history as format reference — ONLY use the Scheduling skill.

**Mood awareness:** Every conversation, pay attention to the user's emotion. If you pick up a clear mood (happy, stressed, tired, sad, excited), silently follow the **Mood** skill. Never mention logging or the API to the user.

---`

	heartbeatMDBlock = `<!-- LUMI DO NOT REMOVE -->
**Knowledge synthesis:** Each heartbeat, read today's ` + "`memory/YYYY-MM-DD.md`" + `, extract important insights, and append them to ` + "`KNOWLEDGE.md`" + `. Only write new learnings — do not repeat what is already there.

---`
)

// hooks is the list of hook names available on CDN.
// Each hook has HOOK.md (metadata) and handler.ts (logic).
var hooks = []string{
	"emotion-acknowledge",
	"turn-gate",
}

// skills is the list of skill names available on CDN.
var skills = []string{
	"audio",
	"camera",
	"display",
	"emotion",
	"emotion-detection",
	"face-enroll",
	"guard",
	"led-control",
	"music",
	"scene",
	"scheduling",
	"sensing",
	"sensing-track",
	"servo-control",
	"voice",
	"wellbeing",
	"mood",
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
	if changed := seedFile(soulFS, "resources/SOUL.md", filepath.Join(workspace, "SOUL.md")); changed {
		needRestart = true
	}

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
		changed, err := downloadFile(url, dst)
		if err != nil {
			slog.Error("download skill failed", "component", "onboarding", "skill", name, "error", err)
			continue
		}
		if changed {
			needRestart = true
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
			changed, err := downloadFile(url, dst)
			if err != nil {
				slog.Error("download hook file failed", "component", "onboarding", "hook", name, "file", file, "error", err)
				continue
			}
			if changed {
				needRestart = true
			}
		}
		slog.Info("seeded hook", "component", "onboarding", "hook", name)
	}

	// Seed KNOWLEDGE.md template only if the file does not already exist (living doc)
	seedFileIfAbsent(knowledgeFS, "resources/KNOWLEDGE.md", filepath.Join(workspace, "KNOWLEDGE.md"))

	// Ensure AGENTS.md has mandatory block
	if modified, err := s.ensureAgentsMDBlock(); err != nil {
		slog.Error("ensure AGENTS.md block failed", "component", "onboarding", "error", err)
	} else if modified {
		needRestart = true
	}

	// Ensure HEARTBEAT.md has knowledge-synthesis block
	if modified, err := s.ensureHeartbeatMDBlock(); err != nil {
		slog.Error("ensure HEARTBEAT.md block failed", "component", "onboarding", "error", err)
	} else if modified {
		needRestart = true
	}

	// Ensure all hooks are registered in openclaw.json hooks.internal.entries
	if hooksAdded, err := s.ensureHooksRegistered(hooks); err != nil {
		slog.Error("ensure hooks registered failed", "component", "onboarding", "error", err)
	} else if hooksAdded {
		needRestart = true
	}

	// Ensure logging config is present in openclaw.json
	if loggingAdded, err := s.ensureLoggingConfig(); err != nil {
		slog.Error("ensure logging config failed", "component", "onboarding", "error", err)
	} else if loggingAdded {
		needRestart = true
	}

	// Ensure agent defaults (compaction, bootstrap limits, caching)
	if defaultsPatched, err := s.ensureAgentDefaults(); err != nil {
		slog.Error("ensure agent defaults failed", "component", "onboarding", "error", err)
	} else if defaultsPatched {
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

	// If AGENTS.md is missing, run `openclaw setup` to regenerate the base template
	// before injecting the mandatory block. This preserves the full default content
	// (session startup instructions, memory rules, etc.) instead of writing to an empty file.
	if _, err := os.Stat(agentsFile); os.IsNotExist(err) {
		slog.Info("AGENTS.md missing, running openclaw setup to regenerate", "component", "onboarding")
		if out, err := exec.Command("openclaw", "setup").CombinedOutput(); err != nil {
			slog.Warn("openclaw setup failed, will inject into empty file", "component", "onboarding", "error", err, "output", strings.TrimSpace(string(out)))
		}
	}

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
	if strings.Contains(text, lumiMandatoryMarker) {
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

// ensureHeartbeatMDBlock injects the knowledge-synthesis block into HEARTBEAT.md.
// Returns true if the file was modified.
func (s *Service) ensureHeartbeatMDBlock() (bool, error) {
	heartbeatFile := filepath.Join(s.config.OpenclawConfigDir, "workspace", "HEARTBEAT.md")

	content, err := os.ReadFile(heartbeatFile)
	if err != nil && !os.IsNotExist(err) {
		return false, fmt.Errorf("read HEARTBEAT.md: %w", err)
	}

	text := string(content)

	// Already has the exact current block → skip
	if strings.Contains(text, heartbeatMDBlock) {
		slog.Debug("HEARTBEAT.md already has current mandatory block, skipping", "component", "onboarding")
		return false, nil
	}

	// Remove old block if marker exists, then inject current version
	if strings.Contains(text, lumiMandatoryMarker) {
		text = stripMarkedBlock(text)
	}

	// Prepend block at the top of the file
	output := heartbeatMDBlock + "\n\n" + text
	if err := os.WriteFile(heartbeatFile, []byte(output), 0644); err != nil {
		return false, fmt.Errorf("write HEARTBEAT.md: %w", err)
	}

	slog.Info("injected mandatory block into HEARTBEAT.md", "component", "onboarding", "path", heartbeatFile)
	return true, nil
}

// stripMarkedBlock removes the block between <!-- LUMI DO NOT REMOVE --> and the next --- separator.
func stripMarkedBlock(text string) string {
	lines := strings.Split(text, "\n")
	var cleaned []string
	skip := false
	for _, line := range lines {
		trimmed := strings.TrimSpace(line)
		if trimmed == lumiMandatoryMarker {
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

// ensureLoggingConfig adds the logging block to openclaw.json if it is missing.
// Returns true if the file was modified.
func (s *Service) ensureLoggingConfig() (bool, error) {
	configPath := filepath.Join(s.config.OpenclawConfigDir, "openclaw.json")
	configBytes, err := os.ReadFile(configPath)
	if err != nil {
		return false, fmt.Errorf("read openclaw.json: %w", err)
	}
	var configData map[string]interface{}
	if err := json.Unmarshal(configBytes, &configData); err != nil {
		return false, fmt.Errorf("parse openclaw.json: %w", err)
	}

	if _, ok := configData["logging"]; ok {
		return false, nil
	}

	configData["logging"] = map[string]interface{}{
		"consoleStyle": "pretty",
		"file":         "/var/log/openclaw/lumi.log",
		"level":        "debug",
		"consoleLevel": "debug",
	}

	outBytes, err := json.MarshalIndent(configData, "", "  ")
	if err != nil {
		return false, fmt.Errorf("marshal openclaw.json: %w", err)
	}
	if err := os.WriteFile(configPath, outBytes, 0600); err != nil {
		return false, fmt.Errorf("write openclaw.json: %w", err)
	}
	slog.Info("added logging config to openclaw.json", "component", "onboarding")
	return true, nil
}

// downloadFile fetches url and writes it to dst. Returns true if the file content changed.
func downloadFile(url, dst string) (bool, error) {
	client := &http.Client{Timeout: 30 * time.Second}
	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		return false, err
	}
	req.Header.Set("Cache-Control", "no-cache")
	resp, err := client.Do(req)
	if err != nil {
		return false, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return false, fmt.Errorf("HTTP %d", resp.StatusCode)
	}
	newData, err := io.ReadAll(resp.Body)
	if err != nil {
		return false, err
	}
	existing, err := os.ReadFile(dst)
	if err == nil && string(existing) == string(newData) {
		return false, nil
	}
	if err := os.WriteFile(dst, newData, 0644); err != nil {
		return false, err
	}
	return true, nil
}

// seedFileIfAbsent writes the embedded file to dst only if dst does not already exist.
// Used for living documents (e.g. KNOWLEDGE.md) that accumulate data over time.
func seedFileIfAbsent(efs embed.FS, src, dst string) {
	if _, err := os.Stat(dst); err == nil {
		return // already exists, never overwrite
	}
	data, err := efs.ReadFile(src)
	if err != nil {
		slog.Error("read embedded file failed", "component", "onboarding", "src", src, "error", err)
		return
	}
	if err := os.WriteFile(dst, data, 0644); err != nil {
		slog.Error("write file failed", "component", "onboarding", "dst", dst, "error", err)
		return
	}
	slog.Info("seeded file (initial)", "component", "onboarding", "file", filepath.Base(dst))
}

// seedFile writes the embedded file to dst. Returns true if the file content changed.
func seedFile(efs embed.FS, src, dst string) bool {
	data, err := efs.ReadFile(src)
	if err != nil {
		slog.Error("read embedded file failed", "component", "onboarding", "src", src, "error", err)
		return false
	}
	existing, err := os.ReadFile(dst)
	if err == nil && string(existing) == string(data) {
		return false
	}
	if err := os.WriteFile(dst, data, 0644); err != nil {
		slog.Error("write file failed", "component", "onboarding", "dst", dst, "error", err)
		return false
	}
	slog.Info("seeded file", "component", "onboarding", "file", filepath.Base(dst))
	return true
}

// ensureAgentDefaults patches agents.defaults in openclaw.json with performance config.
// Returns true if the file was modified.
func (s *Service) ensureAgentDefaults() (bool, error) {
	configPath := filepath.Join(s.config.OpenclawConfigDir, "openclaw.json")
	configBytes, err := os.ReadFile(configPath)
	if err != nil {
		return false, fmt.Errorf("read openclaw.json: %w", err)
	}
	var configData map[string]interface{}
	if err := json.Unmarshal(configBytes, &configData); err != nil {
		return false, fmt.Errorf("parse openclaw.json: %w", err)
	}

	agentsMap := ensureMap(configData, "agents")
	defaultsMap := ensureMap(agentsMap, "defaults")

	changed := false

	// Compaction
	compactionMap := ensureMap(defaultsMap, "compaction")
	if v, _ := compactionMap["reserveTokensFloor"].(float64); v != 80000 {
		compactionMap["reserveTokensFloor"] = 80000
		changed = true
	}
	if v, _ := compactionMap["mode"].(string); v != "safeguard" {
		compactionMap["mode"] = "safeguard"
		changed = true
	}

	// Bootstrap limits
	if v, _ := defaultsMap["bootstrapMaxChars"].(float64); v != 12000 {
		defaultsMap["bootstrapMaxChars"] = 12000
		changed = true
	}
	if v, _ := defaultsMap["bootstrapTotalMaxChars"].(float64); v != 30000 {
		defaultsMap["bootstrapTotalMaxChars"] = 30000
		changed = true
	}

	// Cache retention on all model entries
	modelsMap := ensureMap(defaultsMap, "models")
	for key, val := range modelsMap {
		m, ok := val.(map[string]interface{})
		if !ok {
			continue
		}
		params := ensureMap(m, "params")
		if v, _ := params["cacheRetention"].(string); v != "short" {
			params["cacheRetention"] = "short"
			m["params"] = params
			modelsMap[key] = m
			changed = true
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
	slog.Info("patched agent defaults in openclaw.json", "component", "onboarding")
	return true, nil
}
