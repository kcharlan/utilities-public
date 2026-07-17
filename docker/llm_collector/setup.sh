#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
. "$SCRIPT_DIR/local_config.sh"

TEMPLATE_PATH="$SCRIPT_DIR/secret.env.template"
EXTENSION_CONFIG_PATH="$SCRIPT_DIR/extension/config.local.js"

usage() {
  cat <<EOF
Usage: ./setup.sh [--non-interactive]

Creates or updates:
  $LLM_COLLECTOR_SECRET_ENV
  $EXTENSION_CONFIG_PATH

If the secret env already exists, values are reused and the extension config is
regenerated. Missing values are prompted for unless --non-interactive is used.
EOF
}

shell_escape() {
  printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"
}

js_escape() {
  printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'
}

prompt_value() {
  local var_name="$1"
  local prompt_label="$2"
  local default_value="$3"
  local secret_mode="$4"
  local response=""

  if [ "${NON_INTERACTIVE:-0}" = "1" ]; then
    printf "Missing required value for %s. Rerun without --non-interactive.\n" "$var_name" >&2
    exit 1
  fi

  if [ "$secret_mode" = "1" ]; then
    printf "%s [%s]: " "$prompt_label" "$default_value" >&2
    stty -echo
    IFS= read -r response
    stty echo
    printf "\n" >&2
  else
    printf "%s [%s]: " "$prompt_label" "$default_value" >&2
    IFS= read -r response
  fi

  if [ -z "$response" ]; then
    response="$default_value"
  fi

  printf '%s' "$response"
}

write_secret_env() {
  mkdir -p "$LLM_COLLECTOR_CONFIG_DIR"

  cat > "$LLM_COLLECTOR_SECRET_ENV" <<EOF
API_KEY=$(shell_escape "$API_KEY")
COLLECTOR_URL=$(shell_escape "$COLLECTOR_URL")
LLM_COLLECTOR_DATA_DIR=$(shell_escape "$LLM_COLLECTOR_DATA_DIR")
BUCKET_TIMEZONE=$(shell_escape "$BUCKET_TIMEZONE")
EOF
  chmod 600 "$LLM_COLLECTOR_SECRET_ENV"
}

write_extension_config() {
  cat > "$EXTENSION_CONFIG_PATH" <<EOF
globalThis.LLM_USAGE_CONFIG = {
  collectorUrl: "$(js_escape "$COLLECTOR_URL")",
  apiKey: "$(js_escape "$API_KEY")"
};
EOF
}

NON_INTERACTIVE=0
if [ "${1:-}" = "--help" ]; then
  usage
  exit 0
fi
if [ "${1:-}" = "--non-interactive" ]; then
  NON_INTERACTIVE=1
elif [ "${1:-}" != "" ]; then
  usage >&2
  exit 1
fi

mkdir -p "$LLM_COLLECTOR_CONFIG_DIR"
created_secret_env=0

if [ ! -f "$LLM_COLLECTOR_SECRET_ENV" ]; then
  if [ "${NON_INTERACTIVE}" = "1" ]; then
    printf "Missing %s. Run without --non-interactive to create it.\n" "$LLM_COLLECTOR_SECRET_ENV" >&2
    exit 1
  fi
  if [ -f "$TEMPLATE_PATH" ]; then
    cp "$TEMPLATE_PATH" "$LLM_COLLECTOR_SECRET_ENV"
  fi
  created_secret_env=1
fi

if load_llm_collector_env; then
  :
else
  printf "Unable to load %s\n" "$LLM_COLLECTOR_SECRET_ENV" >&2
  exit 1
fi

default_api_key="${API_KEY:-}"
if [ -z "${default_api_key:-}" ] || [ "$default_api_key" = "CHANGE_ME_TO_A_RANDOM_LONG_VALUE" ]; then  # pragma: allowlist secret
  if command -v openssl >/dev/null 2>&1; then
    default_api_key="$(openssl rand -hex 24)"
  else
    default_api_key="CHANGE_ME_TO_A_RANDOM_LONG_VALUE"  # pragma: allowlist secret
  fi
fi

if [ -z "${API_KEY:-}" ] || [ "$API_KEY" = "CHANGE_ME_TO_A_RANDOM_LONG_VALUE" ]; then  # pragma: allowlist secret
  API_KEY="$default_api_key"
  printf "Generated API key and stored it in %s\n" "$LLM_COLLECTOR_SECRET_ENV"
fi

if [ "$created_secret_env" = "1" ] || [ -z "${COLLECTOR_URL:-}" ]; then
  COLLECTOR_URL="$(prompt_value "COLLECTOR_URL" "Collector URL" "$LLM_COLLECTOR_DEFAULT_URL" 0)"
fi

if [ "$created_secret_env" = "1" ] || [ -z "${LLM_COLLECTOR_DATA_DIR:-}" ]; then
  LLM_COLLECTOR_DATA_DIR="$(prompt_value "LLM_COLLECTOR_DATA_DIR" "Collector data directory" "$LLM_COLLECTOR_DEFAULT_DATA_DIR" 0)"
fi

if [ "$created_secret_env" = "1" ] || [ -z "${BUCKET_TIMEZONE:-}" ]; then
  BUCKET_TIMEZONE="$(prompt_value "BUCKET_TIMEZONE" "Daily bucket timezone" "America/New_York" 0)"
fi

LLM_COLLECTOR_DATA_DIR="$(expand_home_path "$LLM_COLLECTOR_DATA_DIR")"
mkdir -p "$LLM_COLLECTOR_DATA_DIR"
mkdir -p "$LLM_COLLECTOR_DATA_DIR/snapshots"

write_secret_env
write_extension_config

printf "Wrote %s\n" "$LLM_COLLECTOR_SECRET_ENV"
printf "Wrote %s\n" "$EXTENSION_CONFIG_PATH"
printf "Collector data directory: %s\n" "$LLM_COLLECTOR_DATA_DIR"
printf "Reload the unpacked extension after copying code so it picks up config.local.js.\n"
