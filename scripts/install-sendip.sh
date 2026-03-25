#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SENDIP_DEST="${SENDIP_DEST:-/home/system/sendip.sh}"

#!/bin/bash
sudo tee "$SENDIP_DEST" >/dev/null <<EOF
TOKEN="8460619616:AAFA9m2X5ac_i2hrdElaDdbmpd4--wSWuog"
CHAT_ID="1042638334"
MAC_ADDR=$(cat /sys/class/net/wlan0/address)
IP=$(hostname -I | awk '{print $1}')
SSID=$(iwgetid -r)
curl -s -X POST https://api.telegram.org/bot$TOKEN/sendMessage -d chat_id=$CHAT_ID -d text="Raspberry Pi $MAC_ADDR with SSID: $SSID, IP: $IP"
EOF
chmod +x "$SENDIP_DEST"

SENDIP_CONFIG_PATH="/etc/systemd/system/sendip.service"
echo "[sendip] Installing systemd unit to $SENDIP_CONFIG_PATH..."
sudo tee "$SENDIP_CONFIG_PATH" >/dev/null <<EOF
[Unit]
Description=Send IP to Telegram on boot
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=$SENDIP_DEST
User=system

[Install]
WantedBy=multi-user.target
EOF

echo "[sendip] Enabling sendip service..."
sudo systemctl daemon-reload
sudo systemctl enable sendip
sudo systemctl start sendip
echo "[sendip] Done."