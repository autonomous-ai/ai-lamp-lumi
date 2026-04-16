#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
SKILLS_DIR="${ROOT_DIR}/lumi/resources/openclaw-skills"

GCS_BUCKET="${GCS_BUCKET:-s3-autonomous-upgrade-3}"
GCS_PREFIX="${GCS_PREFIX:-lumi/skills}"

if [[ ! -d "$SKILLS_DIR" ]]; then
  echo "Error: skills directory not found at $SKILLS_DIR"
  exit 1
fi

count=0
SKILL_VERSIONS=""
for f in "$SKILLS_DIR"/*/SKILL.md; do
  [[ -f "$f" ]] || continue
  skill_name="$(basename "$(dirname "$f")")"
  gcs_path="${GCS_PREFIX}/${skill_name}/SKILL.md"
  # Hash content as version — only changes when file content changes
  skill_hash="$(shasum -a 256 "$f" | cut -c1-12)"
  echo "========== Upload ${skill_name}/SKILL.md (${skill_hash}) to gs://${GCS_BUCKET}/${gcs_path} =========="
  gsutil -h "Cache-Control:no-cache, no-store, must-revalidate" cp "$f" "gs://${GCS_BUCKET}/${gcs_path}"
  SKILL_VERSIONS="${SKILL_VERSIONS}${skill_name}:${skill_hash},"
  count=$((count + 1))
done

echo "Done: uploaded ${count} skill(s) to gs://${GCS_BUCKET}/${GCS_PREFIX}/"

# Update per-skill versions in OTA metadata so Pi devices detect changes
METADATA_GCS="gs://${GCS_BUCKET}/lumi/ota/metadata.json"
METADATA_TMP=$(mktemp)
trap 'rm -f "$METADATA_TMP"' EXIT
if gsutil cp "$METADATA_GCS" "$METADATA_TMP" 2>/dev/null; then
  python3 -c "
import json
d = json.load(open('$METADATA_TMP'))
versions = {}
for pair in '${SKILL_VERSIONS}'.strip(',').split(','):
    if ':' in pair:
        name, ver = pair.split(':', 1)
        versions[name] = {'version': ver}
d['skills'] = versions
json.dump(d, open('$METADATA_TMP', 'w'), indent=4)
"
  gsutil -h "Cache-Control:no-cache, no-store, must-revalidate" -h "Content-Type:application/json" cp "$METADATA_TMP" "$METADATA_GCS"
  echo "Updated metadata.json with per-skill versions"
else
  echo "Warning: could not update metadata.json"
fi
