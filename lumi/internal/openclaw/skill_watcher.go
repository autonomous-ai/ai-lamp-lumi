package openclaw

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"path/filepath"
	"time"
)

const skillWatchInterval = 5 * time.Minute
const defaultOTAMetadataURL = "https://storage.googleapis.com/s3-autonomous-upgrade-3/lumi/ota/metadata.json"

// StartSkillWatcher polls OTA metadata for per-skill version changes.
// When any skill version changes, downloads that skill from CDN and notifies
// the agent to re-read it.
func (s *Service) StartSkillWatcher(ctx context.Context) {

	slog.Info("skill watcher started", "component", "skill-watcher", "interval", skillWatchInterval)

	// Seed last known versions from current metadata so first poll doesn't re-notify
	lastVersions := map[string]string{}
	if initial, err := s.fetchSkillVersions(); err == nil && initial != nil {
		lastVersions = initial
		slog.Info("skill watcher seeded versions", "component", "skill-watcher", "count", len(lastVersions))
	}

	ticker := time.NewTicker(skillWatchInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			slog.Info("skill watcher stopped", "component", "skill-watcher")
			return
		case <-ticker.C:
			remote, err := s.fetchSkillVersions()
			if err != nil {
				slog.Info("skill watcher: fetch failed", "component", "skill-watcher", "error", err)
				continue
			}
			slog.Info("skill watcher: checked", "component", "skill-watcher", "skills", len(remote))

			// Find skills with changed versions
			var toUpdate []string
			for name, ver := range remote {
				if ver != "" && ver != lastVersions[name] {
					toUpdate = append(toUpdate, name)
					lastVersions[name] = ver
				}
			}
			if len(toUpdate) == 0 {
				continue
			}

			slog.Info("skill versions changed", "component", "skill-watcher", "skills", toUpdate)
			changed := s.downloadSkillsByName(toUpdate)
			s.notifySkillChanges(changed)
		}
	}
}

// downloadSkills downloads all skills from CDN, returns names of changed ones.
func (s *Service) downloadSkills() []string {
	return s.downloadSkillsByName(skills)
}

// downloadSkillsByName downloads specific skills from CDN, returns names of changed ones.
func (s *Service) downloadSkillsByName(names []string) []string {
	skillsDir := filepath.Join(s.config.OpenclawConfigDir, "workspace", "skills")
	var changed []string
	for _, name := range names {
		dst := filepath.Join(skillsDir, name, "SKILL.md")
		url := fmt.Sprintf("%s/%s/SKILL.md", skillsBaseURL, name)
		updated, err := downloadFile(url, dst)
		if err != nil {
			slog.Warn("skill download failed", "component", "skill-watcher", "skill", name, "error", err)
			continue
		}
		if updated {
			changed = append(changed, name)
		}
	}
	return changed
}

// notifySkillChanges sends a single message to the agent listing all changed skills.
func (s *Service) notifySkillChanges(changedSkills []string) {
	if len(changedSkills) == 0 {
		return
	}
	slog.Info("skills updated, notifying agent", "component", "skill-watcher", "changed", changedSkills)
	list := ""
	for _, name := range changedSkills {
		list += fmt.Sprintf("\n- skills/%s/SKILL.md", name)
	}
	msg := fmt.Sprintf("[system] The following skills have been updated. Re-read them now — files on disk have changed. Follow the updated instructions strictly. Keep your reply under 5 words.%s", list)
	if _, err := s.SendChatMessage(msg); err != nil {
		slog.Warn("notify agent failed", "component", "skill-watcher", "error", err)
	}
}

// fetchSkillVersions gets per-skill versions from OTA metadata.
// Returns map[skillName]version.
func (s *Service) fetchSkillVersions() (map[string]string, error) {
	url := s.config.OTAMetadataURL
	if url == "" {
		url = defaultOTAMetadataURL
	}
	resp, err := http.Get(url)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("HTTP %d", resp.StatusCode)
	}
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}
	var meta map[string]json.RawMessage
	if err := json.Unmarshal(body, &meta); err != nil {
		return nil, err
	}
	raw, ok := meta["skills"]
	if !ok {
		return nil, nil
	}
	var skillMap map[string]struct {
		Version string `json:"version"`
	}
	if err := json.Unmarshal(raw, &skillMap); err != nil {
		return nil, err
	}
	result := make(map[string]string, len(skillMap))
	for name, v := range skillMap {
		result[name] = v.Version
	}
	return result, nil
}
