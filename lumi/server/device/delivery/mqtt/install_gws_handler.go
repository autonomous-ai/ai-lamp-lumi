package mqtthandler

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"os/exec"
	"strconv"
	"strings"

	"go-lamp.autonomous.ai/domain"
	"go-lamp.autonomous.ai/internal/device"
)

func (h *DeviceMQTTHandler) publishInstallGWSFailure(errMsg, step string, failedSkills map[string]string) error {
	resp := domain.MQTTInstallGWSResponse{
		MQTTInfoResponse: domain.NewMQTTInfoResponse(h.config, "install_gws", device.GetDeviceMac()),
		Status:           "failure",
		Error:            errMsg,
		ErrorStep:        step,
		FailedSkills:     failedSkills,
	}
	log.Printf("[mqtt] install_gws: FAILURE at step=%s: %s", step, errMsg)
	return h.publish(resp)
}

func (h *DeviceMQTTHandler) handleInstallGWS(cmd domain.MQTTMessage) error {
	var req domain.MQTTInstallGWSCommand
	if err := json.Unmarshal(cmd.Raw(), &req); err != nil {
		log.Printf("[mqtt] install_gws: invalid payload: %v", err)
		return h.publishInstallGWSFailure("invalid JSON payload", "parse_payload", nil)
	}

	skills := req.Skills
	if skills == "" {
		skills = "all"
	}

	log.Printf("[mqtt] install_gws: starting installation (skills=%s)", skills)

	if ok, err := h.networkService.CheckInternet(); !ok {
		log.Printf("[mqtt] install_gws: no internet: %v", err)
		return h.publishInstallGWSFailure("no internet connection — cannot download packages", "check_internet", nil)
	}

	if err := h.ensureNodeJS(); err != nil {
		return h.publishInstallGWSFailure(err.Error(), "install_node", nil)
	}

	nodeVer, _ := getNodeVersion()
	log.Printf("[mqtt] install_gws: Node.js %s ready", nodeVer)

	if err := h.ensureGWS(); err != nil {
		return h.publishInstallGWSFailure(err.Error(), "install_gws_cli", nil)
	}

	if _, err := exec.LookPath("npx"); err != nil {
		log.Printf("[mqtt] install_gws: npx not found, reinstalling Node.js...")
		if err := h.installNodeJS(); err != nil {
			return h.publishInstallGWSFailure("npx not found and failed to fix: "+err.Error(), "fix_npx", nil)
		}
		if _, err := exec.LookPath("npx"); err != nil {
			return h.publishInstallGWSFailure("npx still not found after reinstalling Node.js", "fix_npx", nil)
		}
	}

	if out, err := exec.Command("mkdir", "-p", skillsDir).CombinedOutput(); err != nil {
		return h.publishInstallGWSFailure("cannot create skills directory "+skillsDir+": "+strings.TrimSpace(string(out)), "create_skills_dir", nil)
	}

	skillsBefore := listInstalledSkills()
	beforeSet := make(map[string]bool, len(skillsBefore))
	for _, s := range skillsBefore {
		beforeSet[s] = true
	}

	failedSkills := h.installSkills(skills)

	gwsVersion := ""
	vOut, err := exec.Command("gws", "--version").Output()
	if err == nil {
		gwsVersion = strings.TrimSpace(string(vOut))
	}

	installed := listInstalledSkills()
	newCount := 0
	for _, s := range installed {
		if !beforeSet[s] {
			newCount++
		}
	}

	if newCount == 0 && len(failedSkills) > 0 {
		return h.publishInstallGWSFailure("all skills failed to install", "install_skills", failedSkills)
	}

	resp := domain.MQTTInstallGWSResponse{
		MQTTInfoResponse: domain.NewMQTTInfoResponse(h.config, "install_gws", device.GetDeviceMac()),
		Status:           "success",
		GWSVersion:       gwsVersion,
		NodeVersion:      nodeVer,
		SkillsInstalled:  installed,
		FailedSkills:     failedSkills,
	}
	log.Printf("[mqtt] install_gws: done — gws=%s, installed=%d, failed=%d",
		gwsVersion, len(installed), len(failedSkills))
	return h.publish(resp)
}

func (h *DeviceMQTTHandler) ensureNodeJS() error {
	_, major := getNodeVersion()
	if major >= minNodeMajor {
		return nil
	}
	log.Printf("[mqtt] install_gws: Node.js missing or too old (major=%d), installing v20...", major)
	return h.installNodeJS()
}

func (h *DeviceMQTTHandler) installNodeJS() error {
	if _, err := exec.LookPath("apt-get"); err != nil {
		return fmt.Errorf("apt-get not found — only Debian/Raspberry Pi OS is supported")
	}
	if _, err := exec.LookPath("curl"); err != nil {
		log.Printf("[mqtt] install_gws: curl not found, installing...")
		if out, err := exec.Command("apt-get", "install", "-y", "curl").CombinedOutput(); err != nil {
			return fmt.Errorf("curl not found and apt-get install curl failed: %s", truncate(strings.TrimSpace(string(out)), maxErrorLength))
		}
	}

	ctx, cancel := context.WithTimeout(context.Background(), npmInstallTimeout)
	defer cancel()

	script := `
set -e
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt-get install -y nodejs
node --version
npm --version
`
	out, err := exec.CommandContext(ctx, "bash", "-c", script).CombinedOutput()
	if err != nil {
		errMsg := truncate(strings.TrimSpace(string(out)), maxErrorLength)
		if errors.Is(ctx.Err(), context.DeadlineExceeded) {
			errMsg = "Node.js install timed out after " + npmInstallTimeout.String()
		}
		log.Printf("[mqtt] install_gws: Node.js install failed: %v\n%s", err, string(out))
		return fmt.Errorf("Node.js install failed: %s", errMsg)
	}

	_, major := getNodeVersion()
	if major < minNodeMajor {
		return fmt.Errorf("Node.js installed but version still < %d", minNodeMajor)
	}

	log.Printf("[mqtt] install_gws: Node.js installed successfully:\n%s", string(out))
	return nil
}

func (h *DeviceMQTTHandler) ensureGWS() error {
	if _, err := exec.LookPath("gws"); err == nil {
		log.Printf("[mqtt] install_gws: gws already installed")
		return nil
	}

	log.Printf("[mqtt] install_gws: gws not found, installing...")
	ctx, cancel := context.WithTimeout(context.Background(), npmInstallTimeout)
	defer cancel()

	out, err := exec.CommandContext(ctx, "npm", "install", "-g", "@googleworkspace/cli").CombinedOutput()
	if err != nil {
		errMsg := truncate(strings.TrimSpace(string(out)), maxErrorLength)
		if errors.Is(ctx.Err(), context.DeadlineExceeded) {
			errMsg = "npm install timed out after " + npmInstallTimeout.String()
		}
		log.Printf("[mqtt] install_gws: npm install gws failed: %v\n%s", err, string(out))
		return fmt.Errorf("npm install @googleworkspace/cli failed: %s", errMsg)
	}

	if _, err := exec.LookPath("gws"); err != nil {
		log.Printf("[mqtt] install_gws: gws not in PATH after install")
		return fmt.Errorf("gws package installed but 'gws' command not found in PATH — check npm global bin directory")
	}

	log.Printf("[mqtt] install_gws: gws CLI installed successfully")
	return nil
}

func (h *DeviceMQTTHandler) installSkills(skills string) map[string]string {
	if skills == "all" {
		log.Printf("[mqtt] install_gws: installing all skills")
		ctx, cancel := context.WithTimeout(context.Background(), skillInstallTimeout)
		defer cancel()
		out, err := exec.CommandContext(ctx, "npx", "skills", "add", gwsRepo).CombinedOutput()
		if err != nil {
			reason := truncate(strings.TrimSpace(string(out)), maxErrorLength)
			if errors.Is(ctx.Err(), context.DeadlineExceeded) {
				reason = "timed out after " + skillInstallTimeout.String()
			}
			log.Printf("[mqtt] install_gws: skills install failed: %v\n%s", err, string(out))
			return map[string]string{"all": reason}
		}
		return nil
	}

	failed := make(map[string]string)
	for _, skill := range strings.Split(skills, ",") {
		skill = strings.TrimSpace(skill)
		if skill == "" {
			continue
		}
		log.Printf("[mqtt] install_gws: installing skill %s", skill)
		ctx, cancel := context.WithTimeout(context.Background(), skillInstallTimeout)
		url := gwsRepo + "/tree/main/skills/" + skill
		out, err := exec.CommandContext(ctx, "npx", "skills", "add", url).CombinedOutput()
		cancel()
		if err != nil {
			reason := truncate(strings.TrimSpace(string(out)), maxErrorLength)
			if errors.Is(ctx.Err(), context.DeadlineExceeded) {
				reason = "timed out after " + skillInstallTimeout.String()
			}
			log.Printf("[mqtt] install_gws: skill %s failed: %v\n%s", skill, err, string(out))
			failed[skill] = reason
			continue
		}
		log.Printf("[mqtt] install_gws: skill %s installed", skill)
	}
	if len(failed) == 0 {
		return nil
	}
	return failed
}

func getNodeVersion() (string, int) {
	out, err := exec.Command("node", "--version").Output()
	if err != nil {
		return "not_installed", 0
	}
	ver := strings.TrimSpace(string(out))
	ver = strings.TrimPrefix(ver, "v")
	parts := strings.SplitN(ver, ".", 3)
	if len(parts) == 0 {
		return ver, 0
	}
	major, err := strconv.Atoi(parts[0])
	if err != nil {
		return ver, 0
	}
	return ver, major
}

func truncate(s string, maxLen int) string {
	if len(s) <= maxLen {
		return s
	}
	return s[:maxLen-3] + "..."
}

func listInstalledSkills() []string {
	out, err := exec.Command("ls", skillsDir).Output()
	if err != nil {
		return nil
	}
	var skills []string
	for _, name := range strings.Split(strings.TrimSpace(string(out)), "\n") {
		name = strings.TrimSpace(name)
		if name != "" && strings.HasPrefix(name, "gws-") {
			skills = append(skills, name)
		}
	}
	return skills
}
