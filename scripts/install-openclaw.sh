stage_prerequisites() {
  echo "[stage] Install system packages"
  apt update
  apt install -y \
    hostapd dnsmasq nginx unzip curl wpasupplicant dhcpcd iproute2 iptables \
    git dash xvfb chromium chromium-sandbox || true
  systemctl stop hostapd dnsmasq nginx 2>/dev/null || true
  systemctl unmask hostapd dnsmasq 2>/dev/null || true
  # Node.js 22 for OpenClaw CLI
  if ! command -v node &>/dev/null || ! node -v 2>/dev/null | grep -qE '^v(2[2-9]|[3-9][0-9])'; then
    echo "[stage] Install Node.js 22 (NodeSource)"
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
    apt install -y nodejs
  fi
  # Keep wpa_supplicant running so STA (e.g. Pi Imager WiFi) stays connected during setup.
  # Global wpa_supplicant is stopped/masked only when we switch to AP in device-ap-mode.
}

stage_openclaw() {
  echo "[stage] Install OpenClaw (from fork peterparkernho/openclaw)"
  OPENCLAW_REPO="${OPENCLAW_REPO:-https://github.com/peterparkernho/openclaw.git}"
  OPENCLAW_REF="${OPENCLAW_REF:-peter/eternalai}"
  npm install -g --ignore-scripts "git+${OPENCLAW_REPO}#${OPENCLAW_REF}"
  # npm git install can leave openclaw as a symlink into /root/.npm/_cacache/tmp/...; chmod so User=openclaw can read it
  OPENCLAW_MODULE=$(npm root -g 2>/dev/null)/openclaw
  if [ -L "$OPENCLAW_MODULE" ]; then
    OPENCLAW_REAL=$(readlink -f "$OPENCLAW_MODULE" 2>/dev/null)
    if [ -n "$OPENCLAW_REAL" ] && [ -d "$OPENCLAW_REAL" ]; then
      chmod -R a+rX "$OPENCLAW_REAL" 2>/dev/null || true
      dir=$(dirname "$OPENCLAW_REAL")
      while [ -n "$dir" ] && [ "$dir" != "/" ]; do
        chmod a+rX "$dir" 2>/dev/null || true
        [ "$dir" = "/root" ] && break
        dir=$(dirname "$dir")
      done
    fi
  fi
  openclaw --version || true

  if ! id openclaw &>/dev/null; then
    useradd --system --no-create-home --shell /usr/sbin/nologin openclaw
  fi
  mkdir -p /etc/openclaw /var/log/openclaw
  chown -R openclaw:openclaw /etc/openclaw /var/log/openclaw

  CHROME_PATH=$(command -v chromium 2>/dev/null || command -v chromium-browser 2>/dev/null || true)
  : "${CHROME_PATH:=/usr/bin/chromium}"
  OPENCLAW_BIN=$(command -v openclaw)
  cat >/etc/systemd/system/openclaw.service <<EOF
[Unit]
Description=OpenClaw Gateway
After=network.target

[Service]
Type=simple
User=openclaw
WorkingDirectory=/etc/openclaw
Environment="OPENCLAW_STATE_DIR=/etc/openclaw"
Environment="PUPPETEER_EXECUTABLE_PATH=$CHROME_PATH"
Environment="PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1"
Environment="CHROME_BIN=$CHROME_PATH"
LimitNOFILE=65535
MemoryMax=1500M
ExecStart=/usr/bin/xvfb-run -a --server-args="-screen 0 1280x800x24" $OPENCLAW_BIN gateway run
Restart=always
RestartSec=5
StandardOutput=append:/var/log/openclaw/output.log
StandardError=append:/var/log/openclaw/error.log

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable openclaw
  systemctl start openclaw
}

stage_prerequisites
stage_openclaw