#!/bin/bash
# Production setup for Raspberry Pi 5: single-interface AP/STA switch, nginx setup web + API proxy, lumi backend.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

# ----------------------------------------------------------
# Utils
# ----------------------------------------------------------
retry() {
  local n=0
  local max=$2
  local delay=${3:-2}
  local cmd="$1"
  until [ $n -ge $max ]; do
    eval "$cmd" && return 0
    n=$((n+1))
    echo "Retry $n/$max..."
    sleep $delay
  done
  echo "ERROR: Command failed after $max attempts: $cmd"
  return 1
}

ensure_root() {
  if [ "$(id -u)" -ne 0 ]; then
    echo "Run as root"
    exit 1
  fi
}

# Optional: AP band and channel. Pi 5 Bookworm: firmware config is /boot/firmware/config.txt;
# ensure dtoverlay=disable-wifi is not set or WiFi will stay off.
AP_BAND="${AP_BAND:-2.4}"       # 2.4 or 5 (5 GHz for better throughput)
AP_CHANNEL="${AP_CHANNEL:-}"    # default: 6 (2.4 GHz) or 36 (5 GHz); override e.g. AP_CHANNEL=11 or 40

# ----------------------------------------------------------
# Stage -1: Locale (Bookworm hygiene)
# ----------------------------------------------------------
stage_locale() {
  echo "[stage] Fix locale (Bookworm)"
  unset LC_CTYPE
  apt update
  apt install -y locales
  sed -i 's/^# *\(C\.UTF-8 UTF-8\)/\1/' /etc/locale.gen 2>/dev/null || true
  grep -q '^C\.UTF-8 UTF-8' /etc/locale.gen || echo 'C.UTF-8 UTF-8' >> /etc/locale.gen
  locale-gen C.UTF-8 2>/dev/null || locale-gen
  echo "LC_ALL=C.UTF-8" > /etc/locale.conf
  echo "LANG=C.UTF-8" >> /etc/locale.conf
}

# ----------------------------------------------------------
# Stage 0: Prerequisites
# ----------------------------------------------------------
stage_prerequisites() {
  echo "[stage] Install system packages"
  apt update
  apt install -y \
    hostapd dnsmasq nginx unzip curl jq wpasupplicant dhcpcd iproute2 iptables \
    iw git xvfb chromium chromium-sandbox || true
  systemctl stop hostapd dnsmasq nginx 2>/dev/null || true
  systemctl unmask hostapd dnsmasq 2>/dev/null || true
  # Node.js 22 for OpenClaw CLI
  if ! command -v node &>/dev/null || ! node -v 2>/dev/null | grep -qE '^v(2[2-9]|[3-9][0-9])'; then
    echo "[stage] Install Node.js 22 (NodeSource)"
    curl -fsSL -H "Cache-Control: no-cache" -H "Pragma: no-cache" https://deb.nodesource.com/setup_22.x | bash -
    apt install -y nodejs
  fi
  # Keep wpa_supplicant running so STA (e.g. Pi Imager WiFi) stays connected during setup.
  # Global wpa_supplicant is stopped/masked only when we switch to AP in device-ap-mode.
}

# ----------------------------------------------------------
# Stage 0a: Raspberry Pi 5 WiFi stability (reduces STA drops when SSID/PSK are correct)
# ----------------------------------------------------------
stage_rpi5_wifi_stability() {
  echo "[stage] RPi 5 WiFi stability (power save off, IPv6 disable)"

  # Disable IPv6 — can cause connection drops on RPi 5
  mkdir -p /etc/sysctl.d
  cat >/etc/sysctl.d/99-lumi-wifi.conf <<'EOF'
net.ipv6.conf.all.disable_ipv6 = 1
net.ipv6.conf.default.disable_ipv6 = 1
net.ipv6.conf.lo.disable_ipv6 = 1
EOF
  sysctl -p /etc/sysctl.d/99-lumi-wifi.conf 2>/dev/null || true

  # Disable WiFi power saving at boot (chip sleep causes STA drops)
  # device-ap-mode and device-sta-mode also run power_save off when switching modes
  cat >/etc/systemd/system/lumi-wifi-power-save.service <<'EOF'
[Unit]
Description=Disable WiFi power save on wlan0 (RPi 5 stability)
After=network-online.target
Before=hostapd.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/sh -c 'for i in 1 2 3 4 5 6 7 8 9 10; do ip link show wlan0 >/dev/null 2>&1 && break; sleep 2; done; iw dev wlan0 set power_save off 2>/dev/null || iwconfig wlan0 power off 2>/dev/null || true'

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable lumi-wifi-power-save.service
  # Run now if wlan0 exists (e.g. already on STA from image)
  systemctl start lumi-wifi-power-save.service 2>/dev/null || true
}

# ----------------------------------------------------------
# Stage 0b: OTA metadata (web, lumi, bootstrap URLs from GCS)
# ----------------------------------------------------------
# ----------------------------------------------------------
# Stage 0c: Enable SPI in firmware config
# ----------------------------------------------------------device-
stage_enable_spi() {
  echo "[stage] Enable SPI in firmware config"

  local cfg=""
  if [ -f /boot/firmware/config.txt ]; then
    cfg="/boot/firmware/config.txt"
  elif [ -f /boot/config.txt ]; then
    cfg="/boot/config.txt"
  else
    echo "[stage] No /boot/firmware/config.txt or /boot/config.txt found; skipping SPI enable"
    return 0
  fi

  # If dtparam=spi=on is present but commented, uncomment it; otherwise append.
  if grep -qE '^\s*#?\s*dtparam=spi=on' "$cfg" 2>/dev/null; then
    sed -i -E 's/^\s*#\s*(dtparam=spi=on)/\1/' "$cfg" 2>/dev/null || true
    echo "[stage] Ensured dtparam=spi=on is enabled in $cfg"
  else
    {
      echo ""
      echo "# Enabled by lumi setup.sh to turn on SPI"
      echo "dtparam=spi=on"
    } >>"$cfg"
    echo "[stage] Added dtparam=spi=on to $cfg"
  fi

  echo "[stage] SPI enablement will take effect after reboot"
}

OTA_METADATA_URL="${OTA_METADATA_URL:-https://storage.googleapis.com/s3-autonomous-upgrade-3/lumi/ota/metadata.json}"

stage_ota_metadata() {
  echo "[stage] Fetch OTA metadata"
  METADATA_TMP="/tmp/ota-metadata.$$.json"
  retry "curl -fsSL -H \"Cache-Control: no-cache\" -H \"Pragma: no-cache\" -o \"$METADATA_TMP\" \"$OTA_METADATA_URL\"" 5
  export WEB_VERSION WEB_URL LUMI_VERSION LUMI_URL BOOTSTRAP_VERSION BOOTSTRAP_URL
  WEB_VERSION=$(jq -r '.web.version // empty' "$METADATA_TMP")
  WEB_URL=$(jq -r '.web.url // empty' "$METADATA_TMP")
  LUMI_VERSION=$(jq -r '.lumi.version // empty' "$METADATA_TMP")
  LUMI_URL=$(jq -r '.lumi.url // empty' "$METADATA_TMP")
  BOOTSTRAP_VERSION=$(jq -r '.bootstrap.version // empty' "$METADATA_TMP")
  BOOTSTRAP_URL=$(jq -r '.bootstrap.url // empty' "$METADATA_TMP")
  rm -f "$METADATA_TMP"
  LELAMP_VERSION=$(jq -r '.lelamp.version // empty' "$METADATA_TMP")
  LELAMP_URL=$(jq -r '.lelamp.url // empty' "$METADATA_TMP")
  rm -f "$METADATA_TMP"
  if [ -z "$WEB_URL" ] || [ -z "$LUMI_URL" ] || [ -z "$BOOTSTRAP_URL" ]; then
    echo "ERROR: OTA metadata missing web.url, lumi.url or bootstrap.url. Check $OTA_METADATA_URL"
    exit 1
  fi
  echo "[stage] OTA versions: web=$WEB_VERSION lumi=$LUMI_VERSION bootstrap=$BOOTSTRAP_VERSION lelamp=$LELAMP_VERSION"
}

# Download zip from URL, unzip, copy single binary to dest path (handles lumi-server, bootstrap-server in zip)
install_binary_from_zip() {
  local url="$1"
  local dest_binary="$2"
  local name="$3"
  local zip_tmp="/tmp/${name}-zip.$$"
  local dir_tmp="/tmp/${name}-dir.$$"
  mkdir -p "$dir_tmp"
  retry "curl -fsSL -H \"Cache-Control: no-cache\" -H \"Pragma: no-cache\" -o \"$zip_tmp\" \"$url\"" 5
  unzip -o -q "$zip_tmp" -d "$dir_tmp"
  rm -f "$zip_tmp"
  # Zip may contain lumi-server, bootstrap-server or bare binary (at root or in subdir)
  local bin_file
  bin_file=$(find "$dir_tmp" -type f -executable 2>/dev/null | head -1)
  [ -z "$bin_file" ] && bin_file=$(find "$dir_tmp" -type f 2>/dev/null | head -1)
  if [ -z "$bin_file" ] || [ ! -f "$bin_file" ]; then
    echo "ERROR: No binary found in zip from $url"
    rm -rf "$dir_tmp" 2>/dev/null || true
    exit 1
  fi
  cp -f "$bin_file" "$dest_binary"
  chmod +x "$dest_binary"
  rm -rf "$dir_tmp"
}

# ----------------------------------------------------------
# Stage 1: Backend (bootstrap + lumi from OTA metadata)
# ----------------------------------------------------------
stage_backend() {
  echo "[stage] Install backend (bootstrap + lumi)"

  install_binary_from_zip "$BOOTSTRAP_URL" /usr/local/bin/bootstrap-server "bootstrap"
  install_binary_from_zip "$LUMI_URL" /usr/local/bin/lumi-server "lumi"

  cat >/etc/systemd/system/bootstrap.service <<EOF
[Unit]
Description=Bootstrap Backend
After=network-online.target

[Service]
User=root
ExecStart=/usr/local/bin/bootstrap-server
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=bootstrap

[Install]
WantedBy=multi-user.target
EOF

  cat >/etc/systemd/system/lumi.service <<EOF
[Unit]
Description=Lumi Backend
After=network-online.target

[Service]
User=root
WorkingDirectory=/root
ExecStart=/usr/local/bin/lumi-server
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=lumi

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload
  systemctl enable bootstrap lumi
  systemctl restart bootstrap lumi

  # software-update: download and install binary from OTA metadata (or kind + version)
  # Usage: software-update <bootstrap|lumi|web> [version]
  #   If version omitted or "latest": use URL from metadata.
  #   If version given: fetch metadata and install only if metadata version matches.
  cat >/usr/local/bin/software-update <<'SOFTWAREUPDATE'
#!/bin/bash
set -euo pipefail
OTA_METADATA_URL="${OTA_METADATA_URL:-https://cdn.autonomous.ai/lumi/ota/metadata.json}"
retry() {
  local n=0 max="${2:-5}" delay="${3:-2}" cmd="$1"
  until [ "$n" -ge "$max" ]; do
    eval "$cmd" && return 0
    n=$((n+1)); echo "Retry $n/$max..."; sleep "$delay"
  done
  echo "ERROR: Command failed after $max attempts: $cmd"; return 1
}
[ "$(id -u)" -ne 0 ] && { echo "Run as root or with sudo."; exit 1; }
if [ $# -lt 1 ]; then
  echo "Usage: software-update <bootstrap|lumi|web> [version]"
  echo "  Download from OTA metadata. If version is given, install only when metadata version matches."
  exit 1
fi
KIND="$1"
VERSION="${2:-}"
case "$KIND" in
  bootstrap|lumi|web) ;;
  *) echo "Unknown kind: $KIND (bootstrap, lumi, web)"; exit 1 ;;
esac
METADATA_TMP="/tmp/ota-metadata.$$.json"
retry "curl -fsSL -H 'Cache-Control: no-cache' -H 'Pragma: no-cache' -o '$METADATA_TMP' '$OTA_METADATA_URL'" 5
META_VERSION=$(jq -r --arg k "$KIND" '.[$k].version // empty' "$METADATA_TMP")
META_URL=$(jq -r --arg k "$KIND" '.[$k].url // empty' "$METADATA_TMP")
rm -f "$METADATA_TMP"
if [ -z "$META_URL" ]; then
  echo "ERROR: No url for kind '$KIND' in metadata ($OTA_METADATA_URL)"
  exit 1
fi
if [ -n "$VERSION" ] && [ "$VERSION" != "latest" ] && [ "$VERSION" != "$META_VERSION" ]; then
  echo "ERROR: Requested version $VERSION does not match metadata version $META_VERSION for $KIND"
  exit 1
fi
echo "Installing $KIND version $META_VERSION from $META_URL"
if [ "$KIND" = "web" ]; then
  mkdir -p /usr/share/nginx/html/setup
  retry "curl -fsSL -H 'Cache-Control: no-cache' -H 'Pragma: no-cache' -o /tmp/setup.zip '$META_URL'" 5
  unzip -o -q /tmp/setup.zip -d /usr/share/nginx/html/setup
  rm -f /tmp/setup.zip
  systemctl reload nginx 2>/dev/null || true
  systemctl restart nginx 2>/dev/null || true
  echo "Installed web to /usr/share/nginx/html/setup"
fi
if [ "$KIND" = "lumi" ]; then
  BIN_NAME="lumi-server"
  zip_tmp="/tmp/${KIND}-zip.$$"
  dir_tmp="/tmp/${KIND}-dir.$$"
  mkdir -p "$dir_tmp"
  retry "curl -fsSL -H 'Cache-Control: no-cache' -H 'Pragma: no-cache' -o '$zip_tmp' '$META_URL'" 5
  unzip -o -q "$zip_tmp" -d "$dir_tmp"
  rm -f "$zip_tmp"
  bin_file=$(find "$dir_tmp" -type f -executable 2>/dev/null | head -1)
  [ -z "$bin_file" ] && bin_file=$(find "$dir_tmp" -type f 2>/dev/null | head -1)
  if [ -z "$bin_file" ] || [ ! -f "$bin_file" ]; then
    echo "ERROR: No binary found in zip from $META_URL"
    rm -rf "$dir_tmp" 2>/dev/null || true
    exit 1
  fi
  cp -f "$bin_file" "/usr/local/bin/$BIN_NAME"
  chmod +x "/usr/local/bin/$BIN_NAME"
  rm -rf "$dir_tmp"
  systemctl restart "$KIND" 2>/dev/null || true
  echo "Installed $KIND to /usr/local/bin/$BIN_NAME"
fi
if [ "$KIND" = "bootstrap" ]; then
  BIN_NAME="bootstrap-server"
  zip_tmp="/tmp/${KIND}-zip.$$"
  dir_tmp="/tmp/${KIND}-dir.$$"
  mkdir -p "$dir_tmp"
  retry "curl -fsSL -H 'Cache-Control: no-cache' -H 'Pragma: no-cache' -o '$zip_tmp' '$META_URL'" 5
  unzip -o -q "$zip_tmp" -d "$dir_tmp"
  rm -f "$zip_tmp"
  bin_file=$(find "$dir_tmp" -type f -executable 2>/dev/null | head -1)
  [ -z "$bin_file" ] && bin_file=$(find "$dir_tmp" -type f 2>/dev/null | head -1)
  if [ -z "$bin_file" ] || [ ! -f "$bin_file" ]; then
    echo "ERROR: No binary found in zip from $META_URL"
    rm -rf "$dir_tmp" 2>/dev/null || true
    exit 1
  fi
  cp -f "$bin_file" "/usr/local/bin/$BIN_NAME"
  chmod +x "/usr/local/bin/$BIN_NAME"
  rm -rf "$dir_tmp"
  systemctl restart "$KIND" 2>/dev/null || true
  echo "Installed $KIND to /usr/local/bin/$BIN_NAME"
fi
SOFTWAREUPDATE
  chmod +x /usr/local/bin/software-update
}

# ----------------------------------------------------------
# Stage 1a: LeLamp (Python hardware runtime)
# ----------------------------------------------------------
stage_lelamp() {
  echo "[stage] Install LeLamp (Python hardware drivers)"

  LELAMP_DIR="/opt/lelamp"
  mkdir -p "$LELAMP_DIR"

  if [ -n "$LELAMP_URL" ]; then
    echo "[stage] Downloading LeLamp from OTA..."
    retry "curl -fsSL -H \"Cache-Control: no-cache\" -H \"Pragma: no-cache\" -o /tmp/lelamp.zip \"$LELAMP_URL\"" 5
    unzip -o -q /tmp/lelamp.zip -d "$LELAMP_DIR"
    rm -f /tmp/lelamp.zip
  else
    echo "[stage] WARN: No lelamp URL in OTA metadata, skipping download"
  fi

  # Install Python venv + dependencies
  apt install -y python3-venv python3-pip || true
  if [ ! -d "$LELAMP_DIR/.venv" ]; then
    python3 -m venv "$LELAMP_DIR/.venv"
  fi
  if [ -f "$LELAMP_DIR/requirements.txt" ]; then
    "$LELAMP_DIR/.venv/bin/pip" install -r "$LELAMP_DIR/requirements.txt" --quiet
  fi

  cat >/etc/systemd/system/lumi-lelamp.service <<EOF
[Unit]
Description=Lumi LeLamp Hardware Runtime
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$LELAMP_DIR
Environment="PYTHONPATH=/opt"
ExecStart=$LELAMP_DIR/.venv/bin/uvicorn lelamp.server:app --host 127.0.0.1 --port 5001
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=lumi-lelamp

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload
  systemctl enable lumi-lelamp
  systemctl restart lumi-lelamp
}

# ----------------------------------------------------------
# Stage 1b: OpenClaw (CLI + gateway service; runs as root for full system access) - TODO: remove this
# ----------------------------------------------------------
stage_openclaw() {
  echo "[stage] Install OpenClaw"
  OPENCLAW_VERSION="${OPENCLAW_VERSION:-latest}"
  retry "npm install -g openclaw@${OPENCLAW_VERSION} --ignore-scripts --omit=optional" 5
  openclaw --version || true

  # OpenClaw state root for root-run service (under root's home)
  OPENCLAW_HOME="${OPENCLAW_HOME:-/root/openclaw}"
  mkdir -p \
    "$OPENCLAW_HOME" \
    "$OPENCLAW_HOME/workspace" \
    "$OPENCLAW_HOME/agents/main/agent" \
    "$OPENCLAW_HOME/agents/main/sessions" \
    "$OPENCLAW_HOME/credentials" \
    "$OPENCLAW_HOME/.cache" \
    "$OPENCLAW_HOME/.config" \
    "$OPENCLAW_HOME/.local/share" \
    /var/log/openclaw
  for p in \
    "$OPENCLAW_HOME" \
    "$OPENCLAW_HOME/workspace" \
    "$OPENCLAW_HOME/agents" \
    "$OPENCLAW_HOME/agents/main" \
    "$OPENCLAW_HOME/agents/main/agent" \
    "$OPENCLAW_HOME/agents/main/sessions" \
    "$OPENCLAW_HOME/credentials" \
    "$OPENCLAW_HOME/.cache" \
    "$OPENCLAW_HOME/.config" \
    "$OPENCLAW_HOME/.local" \
    "$OPENCLAW_HOME/.local/share"; do
    chmod 700 "$p" 2>/dev/null || true
  done

  if [ -z "${GATEWAY_TOKEN:-}" ]; then
    if command -v openssl >/dev/null 2>&1; then
      GATEWAY_TOKEN="$(openssl rand -hex 24)"
    else
      GATEWAY_TOKEN="$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')"
    fi
  fi

  # Seed a minimal valid config so gateway can boot cleanly on first run.
  if [ ! -f "$OPENCLAW_HOME/openclaw.json" ]; then
    cat >"$OPENCLAW_HOME/openclaw.json" <<EOF
{
  "agents": {
    "defaults": {
      "workspace": "$OPENCLAW_HOME/workspace"
    }
  },
  "gateway": {
    "mode": "local",
    "bind": "loopback",
    "port": 18789,
    "auth": {
      "mode": "token",
      "token": "$GATEWAY_TOKEN"
    }
  }
}
EOF
    chmod 600 "$OPENCLAW_HOME/openclaw.json"
  fi

  CHROME_PATH=$(command -v chromium 2>/dev/null || command -v chromium-browser 2>/dev/null || true)
  : "${CHROME_PATH:=/usr/bin/chromium}"
  OPENCLAW_BIN=$(command -v openclaw)
  if [ -z "$OPENCLAW_BIN" ]; then
    echo "ERROR: openclaw binary not found after npm install"
    exit 1
  fi
  cat >/etc/systemd/system/openclaw.service <<EOF
[Unit]
Description=OpenClaw Gateway
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$OPENCLAW_HOME
Environment="OPENCLAW_HOME=$OPENCLAW_HOME"
Environment="OPENCLAW_STATE_DIR=$OPENCLAW_HOME"
Environment="HOME=/root"
Environment="XDG_CACHE_HOME=$OPENCLAW_HOME/.cache"
Environment="XDG_CONFIG_HOME=$OPENCLAW_HOME/.config"
Environment="XDG_DATA_HOME=$OPENCLAW_HOME/.local/share"
Environment="PUPPETEER_EXECUTABLE_PATH=$CHROME_PATH"
Environment="PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1"
Environment="CHROME_BIN=$CHROME_PATH"
LimitNOFILE=65535
MemoryMax=1500M
ExecStart=/usr/bin/xvfb-run -a --server-args="-screen 0 1280x800x24" $OPENCLAW_BIN gateway run
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
  # Download openclaw skills from CDN
  SKILLS_DST="$OPENCLAW_HOME/workspace/skills"
  SKILLS_CDN="https://storage.googleapis.com/s3-autonomous-upgrade-3/lumi/skills"
  mkdir -p "$SKILLS_DST"
  echo "[stage] Download openclaw skills from CDN"
  # LED control skill disabled — lumi-server WS client handles LED via OpenClaw lifecycle events
  # mkdir -p "$SKILLS_DST/led-control"
  # curl -fsSL -o "$SKILLS_DST/led-control/SKILL.md" "$SKILLS_CDN/led-control/SKILL.md" || echo "[stage] WARN: failed to download led-control skill (non-fatal)"
  # chmod 600 "$SKILLS_DST"/*/SKILL.md 2>/dev/null || true

  systemctl daemon-reload
  systemctl enable openclaw
  systemctl restart openclaw
  sleep 3
  if ! systemctl is-active --quiet openclaw; then
    echo "ERROR: openclaw service is not active after start"
    systemctl status openclaw --no-pager || true
    journalctl -u openclaw -n 80 --no-pager || true
    exit 1
  fi
}

# ----------------------------------------------------------
# Stage 2: nginx (setup web + API proxy)
# ----------------------------------------------------------
stage_nginx() {
  echo "[stage] Setup nginx (setup web + API proxy)"

  rm -f /etc/nginx/sites-enabled/default
  mkdir -p /usr/share/nginx/html/setup
  chmod 755 /usr/share/nginx/html/setup

  retry "curl -fsSL -H \"Cache-Control: no-cache\" -H \"Pragma: no-cache\" -o /tmp/setup.zip \"$WEB_URL\"" 5
  unzip -o -q /tmp/setup.zip -d /usr/share/nginx/html/setup
  rm -f /tmp/setup.zip

  cat >/etc/nginx/conf.d/lumi.conf <<EOF
upstream backend { server 127.0.0.1:5000; }

server {
  listen 80 default_server;

  root /usr/share/nginx/html/setup;
  index index.html;

  location / {
    try_files \$uri /index.html;
  }

  location /api/ {
    proxy_pass http://backend;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
  }

  # Return 204 so OS does not detect captive portal (no auto-open browser)
  location = /generate_204 { return 204; }
  location = /hotspot-detect.html { return 204; }
  location = /ncsi.txt { return 204; }
  location = /connecttest.txt { return 204; }
}
EOF

  nginx -t
  systemctl enable nginx
  systemctl restart nginx
}

# ----------------------------------------------------------
# Stage 3: AP setup (hostapd + dnsmasq)
# ----------------------------------------------------------
stage_ap() {
  echo "[stage] Setup WiFi AP"

  # Pi 5: prefer device-tree serial; fallback to cpuinfo
  SERIAL=$(tr -d '\0' </proc/device-tree/serial-number 2>/dev/null) || SERIAL=$(awk '/Serial/ {print $3}' /proc/cpuinfo)
  SUFFIX=${SERIAL: -4}
  AP_SSID="Lumi-${SUFFIX}"
  echo "[stage] AP SSID = $AP_SSID"

  # Ignore Pi Imager WiFi credentials baked into the image.
  if [ -f /etc/wpa_supplicant/wpa_supplicant.conf ]; then
    mv /etc/wpa_supplicant/wpa_supplicant.conf /etc/wpa_supplicant/wpa_supplicant.conf.bak 2>/dev/null || true
  fi

  # Many Pi images keep wlan0 down until WiFi country is set. Create minimal config with country
  # so the system enables wlan0; connect-wifi and hostapd use the same country.
  COUNTRY_CODE="${COUNTRY_CODE:-US}"
  mkdir -p /etc/wpa_supplicant
  if [ ! -f /etc/wpa_supplicant/wpa_supplicant-wlan0.conf ]; then
    cat >/etc/wpa_supplicant/wpa_supplicant-wlan0.conf <<EOF
country=$COUNTRY_CODE
ctrl_interface=DIR=/run/wpa_supplicant
update_config=1
EOF
    chmod 600 /etc/wpa_supplicant/wpa_supplicant-wlan0.conf 2>/dev/null || true
    echo "[stage] Created /etc/wpa_supplicant/wpa_supplicant-wlan0.conf with country=$COUNTRY_CODE so wlan0 can appear"
  fi
  
  # Ensure wpa_supplicant@wlan0 uses the intended config file.
  mkdir -p /etc/systemd/system/wpa_supplicant@wlan0.service.d
  cat >/etc/systemd/system/wpa_supplicant@wlan0.service.d/override.conf <<'WPADROP'
[Service]
ExecStart=
ExecStart=/sbin/wpa_supplicant -c /etc/wpa_supplicant/wpa_supplicant-wlan0.conf -i wlan0 -D nl80211,wext
Restart=on-failure
RestartSec=5
WPADROP

  if [ "$AP_BAND" = "5" ]; then
    HWMODE=a
    CHANNEL="${AP_CHANNEL:-36}"
    cat >/etc/hostapd/hostapd.conf <<EOF
interface=wlan0
driver=nl80211
ssid=$AP_SSID
hw_mode=$HWMODE
channel=$CHANNEL
country_code=$COUNTRY_CODE
ieee80211n=1
ieee80211ac=1
wmm_enabled=1
auth_algs=1
ignore_broadcast_ssid=0
EOF
  else
    HWMODE=g
    CHANNEL="${AP_CHANNEL:-6}"
    cat >/etc/hostapd/hostapd.conf <<EOF
interface=wlan0
driver=nl80211
ssid=$AP_SSID
hw_mode=$HWMODE
channel=$CHANNEL
country_code=$COUNTRY_CODE
ieee80211n=1
wmm_enabled=1
auth_algs=1
ignore_broadcast_ssid=0
EOF
  fi
  echo "[stage] AP band=$AP_BAND channel=$CHANNEL"

  cat >/etc/default/hostapd <<EOF
DAEMON_CONF="/etc/hostapd/hostapd.conf"
EOF

  # dnsmasq: use .d drop-in so we don't break system config; bind range to wlan0 explicitly
  mkdir -p /etc/dnsmasq.d
  cat >/etc/dnsmasq.d/99-lumi.conf <<EOF
interface=wlan0
bind-interfaces
dhcp-range=wlan0,192.168.100.50,192.168.100.150,255.255.255.0,24h
address=/#/192.168.100.1
domain-needed
bogus-priv
no-resolv
EOF
  # Remove any conflicting global interface in main config (leave rest intact)
  if [ -f /etc/dnsmasq.conf ]; then
    sed -i 's/^interface=wlan0/#interface=wlan0  # use dnsmasq.d/99-lumi.conf/' /etc/dnsmasq.conf 2>/dev/null || true
  fi

  # dhcpcd: remove only the wlan0 block so eth0/other blocks are preserved
  sed -i '/^interface wlan0$/,/^$/d' /etc/dhcpcd.conf
  cat >>/etc/dhcpcd.conf <<EOF

interface wlan0
static ip_address=192.168.100.1/24
nohook wpa_supplicant
EOF

  # AP mode scripts
  mkdir -p /usr/local/bin

  cat >/usr/local/bin/device-ap-mode <<'EOF'
#!/bin/bash
set -e

echo "Switching to AP mode..."

# Check required commands
for cmd in ip iw systemctl hostapd dnsmasq rfkill; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "Missing required command: $cmd"; exit 1; }
done

# Ensure WiFi is unblocked
rfkill unblock wlan 2>/dev/null || true
rfkill unblock wlan0 2>/dev/null || true

# Stop STA services
systemctl stop wpa_supplicant@wlan0 2>/dev/null || true
systemctl disable wpa_supplicant@wlan0 2>/dev/null || true
systemctl mask wpa_supplicant@wlan0 2>/dev/null || true
killall wpa_supplicant 2>/dev/null || true

systemctl stop dhcpcd 2>/dev/null || true
systemctl disable dhcpcd 2>/dev/null || true

systemctl stop NetworkManager systemd-networkd 2>/dev/null || true

# Clear DHCP state
rm -f /var/lib/dhcpcd5/dhcpcd-wlan0 2>/dev/null || true
rm -f /var/lib/dhcpcd/dhcpcd-wlan0 2>/dev/null || true

# Set regulatory domain
REG=$(grep "^country_code=" /etc/hostapd/hostapd.conf 2>/dev/null | cut -d= -f2)
[ -z "$REG" ] && REG=US
iw reg set "$REG" 2>/dev/null || true

# Reset WiFi interface
ip link set wlan0 down
sleep 1

# switch to AP mode
iw dev wlan0 set type __ap
iw dev wlan0 set channel 6
sleep 1

# Bring interface up
ip link set wlan0 up
sleep 1

# Disable power saving
iw dev wlan0 set power_save off 2>/dev/null || true
iwconfig wlan0 power off 2>/dev/null || true

# Assign static IP
ip addr flush dev wlan0
ip addr add 192.168.100.1/24 dev wlan0

# Enable AP services
systemctl unmask hostapd dnsmasq 2>/dev/null || true
systemctl enable hostapd dnsmasq

systemctl restart hostapd
sleep 2

# Retry hostapd once if failed
if ! systemctl is-active --quiet hostapd; then
  echo "hostapd failed. Retrying..."
  systemctl restart hostapd
  sleep 2
fi

# If still failed → show debug
if ! systemctl is-active --quiet hostapd; then
  echo "ERROR: hostapd still not running"

  echo
  echo "Debug checks:"
  echo "rfkill status:"
  rfkill list || true

  echo
  echo "Regulatory domain:"
  iw reg get || true

  echo
  echo "wlan0 status:"
  ip addr show wlan0 || true

  echo
  echo "hostapd logs:"
  systemctl status hostapd --no-pager || true
  journalctl -u hostapd -n 50 --no-pager || true

  if [ -f /boot/firmware/config.txt ] && grep -q 'disable-wifi' /boot/firmware/config.txt 2>/dev/null; then
    echo
    echo "WiFi may be disabled in /boot/firmware/config.txt"
    echo "Remove dtoverlay=disable-wifi and reboot"
  fi

  exit 1
fi

# Restart DHCP server
systemctl restart dnsmasq

# Restart web service if using captive portal
systemctl restart nginx 2>/dev/null || true

echo "AP MODE ENABLED"
EOF

  chmod +x /usr/local/bin/device-ap-mode

  cat >/usr/local/bin/device-sta-mode <<'EOF'
#!/bin/bash
set -e

echo "Switching to STA mode..."

# Check required commands
for cmd in ip iw systemctl rfkill; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "Missing required command: $cmd"; exit 1; }
done

# Ensure WiFi is unblocked
rfkill unblock wlan 2>/dev/null || true
rfkill unblock wlan0 2>/dev/null || true

# Stop AP services
systemctl stop hostapd dnsmasq 2>/dev/null || true
systemctl disable hostapd dnsmasq 2>/dev/null || true

# Kill any leftover processes
killall hostapd 2>/dev/null || true
killall dnsmasq 2>/dev/null || true

# Reset interface
ip link set wlan0 down 2>/dev/null || true
sleep 1

# Ensure managed mode
iw dev wlan0 set type managed

ip link set wlan0 up
sleep 1

# Disable power saving (better stability)
iw dev wlan0 set power_save off 2>/dev/null || true
iwconfig wlan0 power off 2>/dev/null || true

# Remove any AP static IP
ip addr flush dev wlan0

# Remove AP static IP config from dhcpcd if exists
sed -i '/static ip_address=192.168.100.1\/24/d' /etc/dhcpcd.conf
sed -i '/nohook wpa_supplicant/d' /etc/dhcpcd.conf

# Enable STA services
systemctl unmask wpa_supplicant@wlan0 2>/dev/null || true
systemctl enable wpa_supplicant@wlan0
systemctl restart wpa_supplicant@wlan0

systemctl enable dhcpcd
systemctl restart dhcpcd

# Wait for DHCP
echo "Waiting for IP..."
sleep 5

if ip addr show wlan0 | grep -q "inet "; then
  IP=$(ip -4 addr show wlan0 | grep inet | awk '{print $2}')
  echo "Connected. IP address: $IP"
else
  echo "WARNING: wlan0 did not receive an IP address"
  echo "Check WiFi connection:"
  echo "  wpa_cli status"
  echo "  journalctl -u wpa_supplicant@wlan0 -n 50 --no-pager"
fi

echo "STA MODE ENABLED"
EOF

  chmod +x /usr/local/bin/device-sta-mode

  # connect-wifi: write wpa_supplicant config then switch to STA (used by backend /api/network/setup)
  cat >/usr/local/bin/connect-wifi <<'CONNECTWIFI'
#!/bin/bash
set -e
WPA_CONF="${WPA_CONF:-/etc/wpa_supplicant/wpa_supplicant-wlan0.conf}"
COUNTRY="${COUNTRY:-US}"
[ "$(id -u)" -ne 0 ] && { echo "Run as root or with sudo."; exit 1; }
if [ $# -eq 0 ]; then read -r -p "SSID: " SSID; read -r -s -p "Password (empty=open): " PASS; echo ""; [ -z "$SSID" ] && exit 1
elif [ $# -eq 1 ]; then SSID="$1"; PASS=""
else SSID="$1"; PASS="$2"; fi
ssid_esc="${SSID//\\/\\\\}"; ssid_esc="${ssid_esc//\"/\\\"}"
psk_esc="${PASS//\\/\\\\}"; psk_esc="${psk_esc//\"/\\\"}"
[ -f "$WPA_CONF" ] && existing_country=$(grep -E '^country=' "$WPA_CONF" 2>/dev/null | head -1 | cut -d= -f2) && [ -n "$existing_country" ] && COUNTRY="$existing_country"
mkdir -p "$(dirname "$WPA_CONF")"
if [ -z "$PASS" ]; then
  net_block="network={
	ssid=\"${ssid_esc}\"
	key_mgmt=NONE
	scan_ssid=1
}"
else
  net_block="network={
	ssid=\"${ssid_esc}\"
	psk=\"${psk_esc}\"
	scan_ssid=1
}"
fi
cat >"$WPA_CONF" <<EOF
ctrl_interface=DIR=/run/wpa_supplicant
update_config=1
country=${COUNTRY}
fast_reauth=1
ap_scan=1
${net_block}
EOF
chmod 600 "$WPA_CONF"
/usr/local/bin/device-sta-mode
CONNECTWIFI
  chmod +x /usr/local/bin/connect-wifi

  # software-update: read OTA metadata and update exactly the app given by argument (no bootstrap)
  cat >/usr/local/bin/software-update <<'SOFTWAREUPDATE'
#!/bin/bash
set -e
OTA_METADATA_URL="${OTA_METADATA_URL:-https://storage.googleapis.com/s3-autonomous-upgrade-3/lumi/ota/metadata.json}"
[ "$(id -u)" -ne 0 ] && { echo "Run as root."; exit 1; }
[ $# -ne 1 ] && { echo "Usage: software-update <lumi|openclaw|web>"; exit 1; }
APP="$1"
case "$APP" in
  lumi|openclaw|bootstrap|web|lelamp) ;;
  *) echo "Unknown app: $APP. Use lumi, openclaw, bootstrap, web, or lelamp."; exit 1 ;;
esac

METADATA_TMP=$(mktemp)
ZIP_TMP=""
DIR_TMP=""
trap 'rm -f "$METADATA_TMP" "$ZIP_TMP"; rm -rf "$DIR_TMP"' EXIT
curl -fsSL -H "Cache-Control: no-cache" -H "Pragma: no-cache" -o "$METADATA_TMP" "$OTA_METADATA_URL" || { echo "Failed to fetch metadata from $OTA_METADATA_URL"; exit 1; }
VERSION=$(jq -r --arg a "$APP" '.[$a].version // empty' "$METADATA_TMP")
URL=$(jq -r --arg a "$APP" '.[$a].url // empty' "$METADATA_TMP")
[ -z "$VERSION" ] && { echo "Metadata has no version for $APP"; exit 1; }

if [ "$APP" = "lumi" ]; then
  [ -z "$URL" ] && { echo "Metadata has no url for lumi"; exit 1; }
  ZIP_TMP=$(mktemp)
  DIR_TMP=$(mktemp -d)
  curl -fsSL -H "Cache-Control: no-cache" -o "$ZIP_TMP" "$URL" || { echo "Failed to download lumi"; exit 1; }
  unzip -o -q "$ZIP_TMP" -d "$DIR_TMP"
  BIN=$(find "$DIR_TMP" -type f -executable 2>/dev/null | head -1)
  [ -z "$BIN" ] && BIN=$(find "$DIR_TMP" -type f 2>/dev/null | head -1)
  [ -z "$BIN" ] || [ ! -f "$BIN" ] && { echo "No binary in lumi zip"; exit 1; }
  cp -f "$BIN" /usr/local/bin/lumi-server
  chmod +x /usr/local/bin/lumi-server
  systemctl restart lumi
  echo "lumi updated to $VERSION"
elif [ "$APP" = "bootstrap" ]; then
  [ -z "$URL" ] && { echo "Metadata has no url for bootstrap"; exit 1; }
  ZIP_TMP=$(mktemp)
  DIR_TMP=$(mktemp -d)
  curl -fsSL -H "Cache-Control: no-cache" -o "$ZIP_TMP" "$URL" || { echo "Failed to download bootstrap"; exit 1; }
  unzip -o -q "$ZIP_TMP" -d "$DIR_TMP"
  BIN=$(find "$DIR_TMP" -type f -executable 2>/dev/null | head -1)
  [ -z "$BIN" ] && BIN=$(find "$DIR_TMP" -type f 2>/dev/null | head -1)
  [ -z "$BIN" ] || [ ! -f "$BIN" ] && { echo "No binary in bootstrap zip"; exit 1; }
  cp -f "$BIN" /usr/local/bin/bootstrap-server
  chmod +x /usr/local/bin/bootstrap-server
  systemctl restart bootstrap
  echo "bootstrap updated to $VERSION"
elif [ "$APP" = "openclaw" ]; then
  VER="${VERSION:-latest}"
  npm install -g "openclaw@${VER}" || { echo "npm install openclaw failed"; exit 1; }
  systemctl restart openclaw
  echo "openclaw updated to $VER"
elif [ "$APP" = "web" ]; then
  [ -z "$URL" ] && { echo "Metadata has no url for web"; exit 1; }
  ZIP_TMP=$(mktemp)
  DIR_TMP=$(mktemp -d)
  curl -fsSL -H "Cache-Control: no-cache" -o "$ZIP_TMP" "$URL" || { echo "Failed to download web"; exit 1; }
  unzip -o -q "$ZIP_TMP" -d "$DIR_TMP"
  echo "$VERSION" > "$DIR_TMP/VERSION"
  WEB_ROOT="/usr/share/nginx/html/setup"
  rm -rf "${WEB_ROOT:?}"/*
  cp -a "$DIR_TMP"/* "$WEB_ROOT"
  systemctl restart nginx
  echo "web updated to $VERSION"
elif [ "$APP" = "lelamp" ]; then
  [ -z "$URL" ] && { echo "Metadata has no url for lelamp"; exit 1; }
  ZIP_TMP=$(mktemp)
  curl -fsSL -H "Cache-Control: no-cache" -o "$ZIP_TMP" "$URL" || { echo "Failed to download lelamp"; exit 1; }
  LELAMP_DIR="/opt/lelamp"
  unzip -o -q "$ZIP_TMP" -d "$LELAMP_DIR"
  if [ -f "$LELAMP_DIR/requirements.txt" ]; then
    "$LELAMP_DIR/.venv/bin/pip" install -r "$LELAMP_DIR/requirements.txt" --quiet
  fi
  systemctl restart lumi-lelamp
  echo "lelamp updated to $VERSION"
fi
SOFTWAREUPDATE
  chmod +x /usr/local/bin/software-update

  # start in AP mode
  /usr/local/bin/device-ap-mode
}

# ----------------------------------------------------------
# Main
# ----------------------------------------------------------
ensure_root
stage_locale
stage_prerequisites
stage_rpi5_wifi_stability
stage_enable_spi
stage_ota_metadata
stage_backend
stage_lelamp
stage_openclaw
stage_nginx
stage_ap

# Disable global wpa_supplicant; only wpa_supplicant@wlan0 is used in STA mode
systemctl stop wpa_supplicant.service 2>/dev/null || true
systemctl disable wpa_supplicant.service 2>/dev/null || true
systemctl mask wpa_supplicant.service 2>/dev/null || true

echo ""
echo "======================================"
echo "✅ Setup complete!"
echo "AP SSID: Lumi-XXXX (actual: $AP_SSID)"
echo "Setup page: http://192.168.100.1"
echo "Backends: systemctl status bootstrap lumi lumi-lelamp"
echo "Updates:  software-update <bootstrap|lumi|lelamp|web> [version]"
echo "======================================"

echo ""
echo "Rebooting in 10 seconds so SPI and WiFi firmware changes take effect..."
sleep 10
reboot