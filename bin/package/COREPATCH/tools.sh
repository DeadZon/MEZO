#!/usr/bin/env bash
# scripts/core/tools.sh

# Environment initialization and tool checks
init_env() {
  # Allow overriding from environment before calling init_env
  # MEZO: WORK_DIR/TOOLS_DIR inherit from build environment (set by build.sh via patchpackage.sh)
  : "${WORK_DIR:=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)}"
  : "${TOOLS_DIR:=${WORK_DIR}/bin/apktool}"
  : "${BACKUP_DIR:=${WORK_DIR}/backup}"
  mkdir -p "$BACKUP_DIR"
}

ensure_tools() {
  local HOME="/home/runner"
  # Checks for java, baksmali/smali v2 and 7z (optional)
  if ! command -v java > /dev/null 2>&1; then
    err "java not found in PATH"
    return 1
  fi

  if [ ! -f "${TOOLS_DIR}/baksmaliv2.jar" ]; then
    err "baksmaliv2.jar not found at ${TOOLS_DIR}/baksmaliv2.jar"
    return 1
  fi

  if [ ! -f "${TOOLS_DIR}/smaliv2.jar" ]; then
    err "smaliv2.jar not found at ${TOOLS_DIR}/smaliv2.jar"
    return 1
  fi

  if ! command -v 7z > /dev/null 2>&1; then
    warn "7z not found in PATH — will try to use zip as fallback"
  fi

  if ! command -v unzip > /dev/null 2>&1; then
    err "unzip not found in PATH"
    return 1
  fi

  return 0
}
