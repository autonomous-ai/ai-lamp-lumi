#!/usr/bin/env bash
# Manual setup script for Google Workspace CLI + skills.
# Mirrors the logic in server/device/delivery/mqtt/handler.go (handleInstallGWS)
set -e

GWS_REPO="https://github.com/googleworkspace/cli"
SKILLS_DIR="/root/openclaw/workspace/skills"
MIN_NODE_MAJOR=18

echo "[gws] Checking internet connectivity..."
if ! timeout 5 bash -c 'cat < /dev/null > /dev/tcp/registry.npmjs.org/443' 2>/dev/null; then
  echo "[gws] ERROR: no internet connection"
  exit 1
fi

# Ensure Node.js >= 18
NODE_MAJOR=0
if command -v node &>/dev/null; then
  NODE_MAJOR=$(node -v | sed 's/v//' | cut -d. -f1)
fi

if [ "$NODE_MAJOR" -lt "$MIN_NODE_MAJOR" ]; then
  echo "[gws] Node.js missing or too old (major=$NODE_MAJOR), installing v20..."
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y nodejs
  echo "[gws] Node.js $(node -v) installed"
else
  echo "[gws] Node.js $(node -v) ready"
fi

# Ensure gws CLI
if command -v gws &>/dev/null; then
  echo "[gws] gws already installed ($(gws --version 2>/dev/null || echo 'unknown version'))"
else
  echo "[gws] Installing @googleworkspace/cli..."
  npm install -g @googleworkspace/cli
  echo "[gws] gws CLI installed ($(gws --version 2>/dev/null || echo 'unknown version'))"
fi

# Ensure npx
if ! command -v npx &>/dev/null; then
  echo "[gws] ERROR: npx not found"
  exit 1
fi

# Install skills
mkdir -p "$SKILLS_DIR"
SKILLS="${1:-all}"

if [ "$SKILLS" = "all" ]; then
  echo "[gws] Installing all skills..."
  npx skills add "$GWS_REPO"
else
  IFS=',' read -ra SKILL_LIST <<< "$SKILLS"
  for skill in "${SKILL_LIST[@]}"; do
    skill=$(echo "$skill" | xargs)
    [ -z "$skill" ] && continue
    echo "[gws] Installing skill $skill..."
    npx skills add "$GWS_REPO/tree/main/skills/$skill"
  done
fi

echo "[gws] Done. Installed skills:"
ls "$SKILLS_DIR" 2>/dev/null | grep '^gws-' || echo "(none)"
