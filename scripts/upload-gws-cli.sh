#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP_FILE="${SCRIPT_DIR}/setup-gws-cli.sh"

# Bucket and path matching https://storage.googleapis.com/s3-autonomous-upgrade-3/intern/setup-gws-cli.sh
GCS_BUCKET="${GCS_BUCKET:-s3-autonomous-upgrade-3}"
GCS_PATH="${GCS_PATH:-intern/setup-gws-cli.sh}"

if [[ ! -f "$SETUP_FILE" ]]; then
  echo "Error: setup-gws-cli.sh not found at $SETUP_FILE"
  exit 1
fi

echo "========== Upload setup-gws-cli.sh to Google Cloud Storage (no-cache) =========="
gsutil -h "Cache-Control:no-cache, no-store, must-revalidate" cp "$SETUP_FILE" "gs://${GCS_BUCKET}/${GCS_PATH}"
echo "Done: gs://${GCS_BUCKET}/${GCS_PATH}"
