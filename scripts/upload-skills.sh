#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
SKILLS_DIR="${ROOT_DIR}/resources/openclaw-skills"

GCS_BUCKET="${GCS_BUCKET:-s3-autonomous-upgrade-3}"
GCS_PREFIX="${GCS_PREFIX:-intern/skills}"

if [[ ! -d "$SKILLS_DIR" ]]; then
  echo "Error: skills directory not found at $SKILLS_DIR"
  exit 1
fi

count=0
for f in "$SKILLS_DIR"/*/SKILL.md; do
  [[ -f "$f" ]] || continue
  skill_name="$(basename "$(dirname "$f")")"
  gcs_path="${GCS_PREFIX}/${skill_name}/SKILL.md"
  echo "========== Upload ${skill_name}/SKILL.md to gs://${GCS_BUCKET}/${gcs_path} =========="
  gsutil -h "Cache-Control:no-cache, no-store, must-revalidate" cp "$f" "gs://${GCS_BUCKET}/${gcs_path}"
  count=$((count + 1))
done

echo "Done: uploaded ${count} skill(s) to gs://${GCS_BUCKET}/${GCS_PREFIX}/"
