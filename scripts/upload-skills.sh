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

# Local hash cache to skip unchanged skills (whole folder).
HASH_CACHE="${SCRIPT_DIR}/.skill-hashes"
touch "$HASH_CACHE"

count=0
skipped_skills=0

# Build metadata rows: `<name>|<version>|<json files array>` (one per line),
# emitted as a temp file to avoid quoting hell in Python.
ENTRIES_FILE="$(mktemp)"
trap 'rm -f "$ENTRIES_FILE"' EXIT

for skill_dir in "$SKILLS_DIR"/*/; do
  [[ -d "$skill_dir" ]] || continue
  skill_name="$(basename "$skill_dir")"

  # Collect all .md files in the skill folder (SKILL.md + any sibling
  # reference files like proactive-suggestion.md), sorted for stability.
  # macOS default bash 3.2 has no `mapfile`, so we read into an array the
  # portable way.
  md_files=()
  while IFS= read -r _path; do
    md_files+=("$_path")
  done < <(find "$skill_dir" -maxdepth 1 -name '*.md' | sort)
  [[ ${#md_files[@]} -gt 0 ]] || continue

  # Combined hash = sha256 of concatenated "<name>:<file-hash>" lines — if ANY
  # file changes, the skill's version changes and Pi devices refetch.
  combined_input=""
  file_list_json=""
  for f in "${md_files[@]}"; do
    fname="$(basename "$f")"
    fhash="$(shasum -a 256 "$f" | cut -d' ' -f1)"
    combined_input+="${fname}:${fhash}"$'\n'
    if [[ -z "$file_list_json" ]]; then
      file_list_json="\"${fname}\""
    else
      file_list_json="${file_list_json},\"${fname}\""
    fi
  done
  skill_hash="$(printf '%s' "$combined_input" | shasum -a 256 | cut -c1-12)"

  echo "${skill_name}|${skill_hash}|[${file_list_json}]" >> "$ENTRIES_FILE"

  # Skip whole skill if combined hash unchanged since last upload.
  cached_hash="$(grep "^${skill_name}:" "$HASH_CACHE" 2>/dev/null | cut -d: -f2)"
  if [[ "$cached_hash" == "$skill_hash" ]]; then
    skipped_skills=$((skipped_skills + 1))
    continue
  fi

  for f in "${md_files[@]}"; do
    fname="$(basename "$f")"
    gcs_path="${GCS_PREFIX}/${skill_name}/${fname}"
    echo "========== Upload ${skill_name}/${fname} (skill hash ${skill_hash}) to gs://${GCS_BUCKET}/${gcs_path} =========="
    gsutil -h "Cache-Control:no-cache, no-store, must-revalidate" cp "$f" "gs://${GCS_BUCKET}/${gcs_path}"
    count=$((count + 1))
  done

  grep -v "^${skill_name}:" "$HASH_CACHE" > "${HASH_CACHE}.tmp" 2>/dev/null || true
  echo "${skill_name}:${skill_hash}" >> "${HASH_CACHE}.tmp"
  mv "${HASH_CACHE}.tmp" "$HASH_CACHE"
done

echo "Done: uploaded ${count} file(s) across changed skills, skipped ${skipped_skills} unchanged skill(s). gs://${GCS_BUCKET}/${GCS_PREFIX}/"

# Update OTA metadata with per-skill { version, files[] }.
METADATA_GCS="gs://${GCS_BUCKET}/lumi/ota/metadata.json"
METADATA_TMP=$(mktemp)
trap 'rm -f "$METADATA_TMP" "$ENTRIES_FILE"' EXIT
if gsutil cp "$METADATA_GCS" "$METADATA_TMP" 2>/dev/null; then
  python3 - "$METADATA_TMP" "$ENTRIES_FILE" <<'PY'
import json, sys
metadata_path, entries_path = sys.argv[1], sys.argv[2]
d = json.load(open(metadata_path))
skills = {}
for line in open(entries_path):
    line = line.strip()
    if not line:
        continue
    name, version, files_json = line.split("|", 2)
    skills[name] = {"version": version, "files": json.loads(files_json)}
d["skills"] = skills
json.dump(d, open(metadata_path, "w"), indent=4)
PY
  gsutil -h "Cache-Control:no-cache, no-store, must-revalidate" -h "Content-Type:application/json" cp "$METADATA_TMP" "$METADATA_GCS"
  echo "Updated metadata.json with per-skill { version, files[] }"
else
  echo "Warning: could not update metadata.json"
fi
