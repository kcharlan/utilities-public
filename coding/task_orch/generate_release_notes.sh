#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# Release Notes Generator
#
# Scans execution/done/ for completed plan files, extracts Operator Actions
# sections and metadata, and produces an aggregated RELEASE_NOTES.md.
#
# Usage:
#   ./generate_release_notes.sh              # scan done/ directory
#   ./generate_release_notes.sh plan1.plan.md plan2.plan.md  # specific files
#
# Output: task_orch/RELEASE_NOTES.md (overwritten each run)
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DONE_DIR="$SCRIPT_DIR/execution/done"
OUTPUT="$SCRIPT_DIR/RELEASE_NOTES.md"

# Collect plan files — either from args or by scanning done/
if [ $# -gt 0 ]; then
  PLAN_FILES=("$@")
else
  PLAN_FILES=()
  while IFS= read -r f; do
    PLAN_FILES+=("$f")
  done < <(find "$DONE_DIR" -name '*.plan.md' 2>/dev/null | sort)
fi

if [ ${#PLAN_FILES[@]} -eq 0 ]; then
  echo "No plan files found. Nothing to generate."
  exit 0
fi

# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------

# Extract the first H1 title from a plan file
extract_title() {
  sed -n 's/^# \(.*\)/\1/p' "$1" | head -1
}

# Extract plan ID from YAML front matter
extract_plan_id() {
  sed -n '/^---$/,/^---$/{ s/^PLAN_ID:[[:space:]]*//p; }' "$1" | head -1
}

# Extract a markdown section by H2 heading, returning everything between
# that heading and the next H2 (or EOF). Strips the heading itself.
extract_section() {
  local file="$1"
  local heading="$2"
  awk -v h="## $heading" '
    BEGIN { found=0 }
    $0 == h { found=1; next }
    found && /^## / { exit }
    found { print }
  ' "$file"
}

# Extract a subsection (H3) from within a section body (passed via stdin)
extract_subsection() {
  local heading="$1"
  awk -v h="### $heading" '
    BEGIN { found=0 }
    $0 == h { found=1; next }
    found && /^### / { exit }
    found { print }
  ' | sed '/^[[:space:]]*$/d'  # strip blank lines
}

# Read a field from a status sidecar file
read_status_field() {
  local file="$1"
  local field="$2"
  [ -f "$file" ] && sed -n "s/^${field}:[[:space:]]*//p" "$file" | head -1
}

# ---------------------------------------------------------------------------
# Build aggregated content
# ---------------------------------------------------------------------------

# Accumulators for each category
infra_items=""
migration_items=""
config_items=""
breaking_items=""
rollback_items=""
plan_table=""
detail_sections=""
has_actions=false

for plan_file in "${PLAN_FILES[@]}"; do
  [ -f "$plan_file" ] || continue

  basename_md=$(basename "$plan_file")
  plan_id=$(extract_plan_id "$plan_file")
  title=$(extract_title "$plan_file")
  [ -z "$plan_id" ] && plan_id="${basename_md%%_*}"
  [ -z "$title" ] && title="$basename_md"

  # Find matching status file
  status_file="${plan_file%.plan.md}.status"
  # Also check with .plan.md.status naming (older convention)
  [ -f "$status_file" ] || status_file="${plan_file}.status"
  commits=$(read_status_field "$status_file" "COMMITS")
  test_result=$(read_status_field "$status_file" "TEST_RESULT")
  notes=$(read_status_field "$status_file" "NOTES")
  [ -z "$commits" ] && commits="—"
  [ -z "$test_result" ] && test_result="—"

  # Plan summary table row
  plan_table="${plan_table}| ${plan_id} | ${title} | \`${commits}\` | ${test_result} |
"

  # Extract Operator Actions section
  actions_body=$(extract_section "$plan_file" "Operator Actions")

  # Check if the plan has meaningful actions (not "None" or empty)
  if [ -n "$actions_body" ] && ! echo "$actions_body" | grep -qi '^None'; then
    has_actions=true

    # Extract each subsection
    infra=$(echo "$actions_body" | extract_subsection "Infrastructure")
    migration=$(echo "$actions_body" | extract_subsection "Data Migration")
    config=$(echo "$actions_body" | extract_subsection "Configuration")
    breaking=$(echo "$actions_body" | extract_subsection "Breaking Changes")
    rollback=$(echo "$actions_body" | extract_subsection "Rollback Notes")

    # Append with plan attribution
    if [ -n "$infra" ]; then
      infra_items="${infra_items}
**From ${plan_id} — ${title}:**
${infra}
"
    fi
    if [ -n "$migration" ]; then
      migration_items="${migration_items}
**From ${plan_id} — ${title}:**
${migration}
"
    fi
    if [ -n "$config" ]; then
      config_items="${config_items}
**From ${plan_id} — ${title}:**
${config}
"
    fi
    if [ -n "$breaking" ]; then
      breaking_items="${breaking_items}
**From ${plan_id} — ${title}:**
${breaking}
"
    fi
    if [ -n "$rollback" ]; then
      rollback_items="${rollback_items}
**From ${plan_id} — ${title}:**
${rollback}
"
    fi
  fi

  # Extract Overview for detailed changes
  overview=$(extract_section "$plan_file" "Overview")
  if [ -n "$overview" ]; then
    detail_sections="${detail_sections}
### ${plan_id} — ${title}

${overview}
"
  fi
done

# ---------------------------------------------------------------------------
# Write RELEASE_NOTES.md
# ---------------------------------------------------------------------------

{
  echo "# Release Notes — $(date '+%Y-%m-%d')"
  echo ""
  echo "> Auto-generated by \`generate_release_notes.sh\` from completed plans"
  echo "> in \`execution/done/\`. Regenerate anytime: \`./generate_release_notes.sh\`"
  echo ""

  # Operator Action Items
  echo "## Operator Action Items"
  echo ""

  if ! $has_actions; then
    echo "_No operator actions required — all plans are standard image deployments._"
    echo ""
  else
    if [ -n "$infra_items" ]; then
      echo "### Infrastructure"
      echo "$infra_items"
    fi
    if [ -n "$migration_items" ]; then
      echo "### Data Migration"
      echo "$migration_items"
    fi
    if [ -n "$config_items" ]; then
      echo "### Configuration"
      echo "$config_items"
    fi
    if [ -n "$breaking_items" ]; then
      echo "### Breaking Changes"
      echo "$breaking_items"
    fi
    if [ -n "$rollback_items" ]; then
      echo "### Rollback Notes"
      echo "$rollback_items"
    fi
  fi

  # Plans summary table
  echo "## Plans Included"
  echo ""
  echo "| Plan | Title | Commits | Tests |"
  echo "|------|-------|---------|-------|"
  echo -n "$plan_table"
  echo ""

  # Detailed changes
  echo "## Detailed Changes"
  echo "$detail_sections"

  echo ""
  echo "_Generated: $(date '+%Y-%m-%d %H:%M:%S')_"
} > "$OUTPUT"

echo "Release notes written to $OUTPUT"
