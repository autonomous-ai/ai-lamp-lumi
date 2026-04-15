#!/bin/bash
# RunPod startup script — nginx (8888) → uvicorn (8000)

set -e

echo "=== Starting DL Backend ==="

# Install nginx if not present
if ! command -v nginx &> /dev/null; then
    apt-get update && apt-get install -y nginx
fi

# Install Python dependencies
pip install .

# Stop any existing nginx and start with our config only
nginx -s stop 2>/dev/null || true
pkill nginx 2>/dev/null || true
nginx -c nginx.conf

# Start uvicorn (foreground)
python server.py --host 127.0.0.1 --port 8000
