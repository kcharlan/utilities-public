#!/bin/bash

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LLM_COLLECTOR_CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/llm_collector"
LLM_COLLECTOR_SECRET_ENV="${LLM_COLLECTOR_SECRET_ENV:-$LLM_COLLECTOR_CONFIG_DIR/secret.env}"
LLM_COLLECTOR_DEFAULT_DATA_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/llm_collector"
LLM_COLLECTOR_DEFAULT_URL="http://127.0.0.1:9000"
LLM_COLLECTOR_DEFAULT_BUCKET_TIMEZONE="America/New_York"

expand_home_path() {
  case "$1" in
    "~")
      printf '%s\n' "$HOME"
      ;;
    "~/"*)
      printf '%s/%s\n' "$HOME" "${1#~/}"
      ;;
    *)
      printf '%s\n' "$1"
      ;;
  esac
}

load_llm_collector_env() {
  if [ ! -f "$LLM_COLLECTOR_SECRET_ENV" ]; then
    return 1
  fi

  set -a
  # shellcheck disable=SC1090
  . "$LLM_COLLECTOR_SECRET_ENV"
  set +a

  : "${COLLECTOR_URL:=$LLM_COLLECTOR_DEFAULT_URL}"
  : "${LLM_COLLECTOR_DATA_DIR:=$LLM_COLLECTOR_DEFAULT_DATA_DIR}"
  : "${BUCKET_TIMEZONE:=$LLM_COLLECTOR_DEFAULT_BUCKET_TIMEZONE}"
  LLM_COLLECTOR_DATA_DIR="$(expand_home_path "$LLM_COLLECTOR_DATA_DIR")"

  export PROJECT_ROOT
  export LLM_COLLECTOR_CONFIG_DIR
  export LLM_COLLECTOR_SECRET_ENV
  export COLLECTOR_URL
  export LLM_COLLECTOR_DATA_DIR
  export BUCKET_TIMEZONE

  return 0
}

llm_collector_setup_hint() {
  printf "Run '%s/setup.sh' to create or refresh local configuration.\n" "$PROJECT_ROOT" >&2
}
