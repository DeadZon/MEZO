#!/bin/bash
# MEZO ROM Builder — Fly.io entrypoint.
# Runs the same pipeline as GitHub Actions without cloning the repository.
# The repository is already present at /app (copied into the Docker image at build time).
set -euo pipefail

# ── Working directory ─────────────────────────────────────────────────────────
cd /app

# ── GitHub context helpers ────────────────────────────────────────────────────
# Export GITHUB_WORKFLOW so telegram.py _github_ctx() shows the right label.
export GITHUB_WORKFLOW="${GITHUB_WORKFLOW:-MEZO Fly ${SOC:-mtk}}"
# Export GITHUB_SERVER_URL so telegram.py builds a correct run URL.
export GITHUB_SERVER_URL="${GITHUB_SERVER_URL:-https://github.com}"

# Compute the run URL for display (no secrets — only public repo/run metadata).
GITHUB_RUN_URL=""
if [ -n "${GITHUB_REPOSITORY:-}" ] && [ -n "${GITHUB_RUN_ID:-}" ]; then
    GITHUB_RUN_URL="${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}"
fi

# ── Build info (no secrets printed) ──────────────────────────────────────────
echo "=========================================="
echo "  MEZO ROM Builder — Fly.io"
echo "  Directory : $(pwd)"
echo "  Commit    : $(git rev-parse --short HEAD 2>/dev/null || echo 'unknown')"
echo "  SOC       : ${SOC:-unknown}"
echo "  STYLE     : ${STYLE:-unknown}"
echo "  MODE      : ${MODE:-build}"
echo "  ROM_URL   : ${ROM_URL:+[SET]}"
echo "  PIXELDRAIN: ${UPLOAD_PIXELDRAIN:-false}"
echo "  TELEGRAM  : ${NOTIFY_TELEGRAM:-false}"
echo "  OVERSIZED : ${ALLOW_OVERSIZED_FINAL:-false}"
echo "  RUN URL   : ${GITHUB_RUN_URL:-N/A}"
echo "=========================================="

# ── Validate required inputs ──────────────────────────────────────────────────
if [ -z "${ROM_URL:-}" ]; then
    echo "[ERROR] ROM_URL is required but not set." >&2
    exit 1
fi

# ── Telegram SOC label ────────────────────────────────────────────────────────
export TG_SOC="${SOC:-mtk}"
export STYLE="${STYLE:-Lite}"
export MEZO_BACKEND="${MEZO_BACKEND:-Fly.io}"

# ── sudo handling — root in Docker runs commands directly ─────────────────────
if [ "$(id -u)" -eq 0 ]; then
    SUDO=""
else
    SUDO="sudo -E"
fi

# ── Exit trap — catch unexpected failures before pipeline error handling ──────
_NOTIFIED=0
_on_exit() {
    local code=$?
    if [ "$code" -ne 0 ] && [ "$_NOTIFIED" -eq 0 ] \
        && [ "${NOTIFY_TELEGRAM:-false}" = "true" ]; then
        echo "[TRAP] Unexpected exit (code $code) — sending failure notification..." >&2
        $SUDO python3 bin/scripts/telegram.py finish FAIL \
            --error "Unexpected container exit (code $code, line $(caller 2>/dev/null || echo unknown))" \
            2>/dev/null || true
    fi
}
trap '_on_exit' EXIT

# ── Live-log watch helpers (mirrors GitHub Actions tg_watch.py usage) ─────────
TG_WATCH_PID=""
_start_watch() {
    local logfile="$1" stage="$2"
    if [ "${NOTIFY_TELEGRAM:-false}" = "true" ]; then
        rm -f /tmp/tg_watch_stop
        $SUDO python3 bin/scripts/tg_watch.py "$logfile" "$stage" &
        TG_WATCH_PID=$!
    fi
}
_stop_watch() {
    if [ -n "${TG_WATCH_PID:-}" ]; then
        touch /tmp/tg_watch_stop
        sleep 3
        $SUDO kill "$TG_WATCH_PID" 2>/dev/null || true
        TG_WATCH_PID=""
    fi
}

# ── Swap setup on persistent Fly volume ───────────────────────────────────────
echo "[SWAP] Setting up swap on /mnt/mezo_data..."
mkdir -p /mnt/mezo_data

SWAP_FILE="/mnt/mezo_data/swapfile"
SWAP_TARGET_BYTES=51539607552  # 48 GiB

if [ -f "$SWAP_FILE" ]; then
    SWAP_CURRENT=$(stat -c%s "$SWAP_FILE" 2>/dev/null || echo 0)
    if [ "$SWAP_CURRENT" -ne "$SWAP_TARGET_BYTES" ]; then
        swapoff "$SWAP_FILE" 2>/dev/null || true
        rm -f "$SWAP_FILE"
    fi
fi

if [ ! -f "$SWAP_FILE" ]; then
    fallocate -l 48G "$SWAP_FILE" 2>/dev/null \
        || dd if=/dev/zero of="$SWAP_FILE" bs=1M count=49152 status=progress
    chmod 600 "$SWAP_FILE"
    mkswap "$SWAP_FILE"
fi
swapon "$SWAP_FILE" 2>/dev/null || true
echo "[SWAP] Ready."

# ── Python dependencies ───────────────────────────────────────────────────────
if [ -f requirements.txt ]; then
    pip3 install --no-cache-dir -q -r requirements.txt 2>/dev/null || true
fi

# ── Timing ────────────────────────────────────────────────────────────────────
BUILD_START=$(date +%s)
OVERALL_EXIT=0

# ── Telegram: build started ───────────────────────────────────────────────────
if [ "${NOTIFY_TELEGRAM:-false}" = "true" ]; then
    $SUDO python3 bin/scripts/telegram.py start "${TG_SOC}" 2>/dev/null || true
fi

# ── Step 1: setup.sh ─────────────────────────────────────────────────────────
echo ""
echo "[STEP 1/4] setup.sh — installing build dependencies..."
LOG_SETUP=/tmp/mezo_setup.log
: > "$LOG_SETUP"

set +e
$SUDO bash setup.sh 2>&1 | tee "$LOG_SETUP"
SETUP_EXIT=${PIPESTATUS[0]}
set -e

if [ "$SETUP_EXIT" -ne 0 ]; then
    echo "[ERROR] setup.sh failed (exit $SETUP_EXIT)" >&2
    OVERALL_EXIT=$SETUP_EXIT
fi

# ── Step 2: build.sh ─────────────────────────────────────────────────────────
if [ "$OVERALL_EXIT" -eq 0 ]; then
    echo ""
    echo "[STEP 2/4] build.sh — extracting and applying ROM modifications..."
    LOG_BUILD=/tmp/mezo_build.log
    : > "$LOG_BUILD"

    if [ "${NOTIFY_TELEGRAM:-false}" = "true" ]; then
        $SUDO python3 bin/scripts/telegram.py update unpack RUN 2>/dev/null || true
        _start_watch "$LOG_BUILD" unpack
    fi

    set +e
    $SUDO bash build.sh "${ROM_URL}" 2>&1 | tee "$LOG_BUILD"
    BUILD_EXIT=${PIPESTATUS[0]}
    set -e

    _stop_watch

    if [ "$BUILD_EXIT" -ne 0 ]; then
        echo "[ERROR] build.sh failed (exit $BUILD_EXIT)" >&2
        OVERALL_EXIT=$BUILD_EXIT
    elif [ "${NOTIFY_TELEGRAM:-false}" = "true" ]; then
        $SUDO python3 bin/scripts/telegram.py update unpack OK 2>/dev/null || true
        $SUDO python3 bin/scripts/telegram.py update mods OK 2>/dev/null || true
    fi
fi

# ── Step 3: packROM.sh ────────────────────────────────────────────────────────
if [ "$OVERALL_EXIT" -eq 0 ]; then
    echo ""
    echo "[STEP 3/4] packROM.sh — rebuilding partitions and packing..."
    LOG_PACK=/tmp/mezo_pack.log
    : > "$LOG_PACK"

    if [ "${NOTIFY_TELEGRAM:-false}" = "true" ]; then
        $SUDO python3 bin/scripts/telegram.py update rebuild RUN 2>/dev/null || true
        _start_watch "$LOG_PACK" rebuild
    fi

    set +e
    $SUDO bash packROM.sh 2>&1 | tee "$LOG_PACK"
    PACK_EXIT=${PIPESTATUS[0]}
    set -e

    _stop_watch

    if [ "$PACK_EXIT" -ne 0 ]; then
        echo "[ERROR] packROM.sh failed (exit $PACK_EXIT)" >&2
        OVERALL_EXIT=$PACK_EXIT
    elif [ "${NOTIFY_TELEGRAM:-false}" = "true" ]; then
        $SUDO python3 bin/scripts/telegram.py update rebuild OK 2>/dev/null || true
        $SUDO python3 bin/scripts/telegram.py update super OK 2>/dev/null || true
        $SUDO python3 bin/scripts/telegram.py update vbmeta OK 2>/dev/null || true
    fi
fi

# ── Step 4: package_rom.py ────────────────────────────────────────────────────
if [ "$OVERALL_EXIT" -eq 0 ]; then
    echo ""
    echo "[STEP 4/4] package_rom.py — creating final ROM ZIP..."
    LOG_PKG=/tmp/mezo_package.log
    : > "$LOG_PKG"

    if [ "${NOTIFY_TELEGRAM:-false}" = "true" ]; then
        $SUDO python3 bin/scripts/telegram.py update zip RUN 2>/dev/null || true
        _start_watch "$LOG_PKG" zip
    fi

    set +e
    $SUDO python3 bin/scripts/package_rom.py 2>&1 | tee "$LOG_PKG"
    PKG_EXIT=${PIPESTATUS[0]}
    set -e

    _stop_watch

    if [ "$PKG_EXIT" -ne 0 ]; then
        echo "[ERROR] package_rom.py failed (exit $PKG_EXIT)" >&2
        OVERALL_EXIT=$PKG_EXIT
    elif [ "${NOTIFY_TELEGRAM:-false}" = "true" ]; then
        $SUDO python3 bin/scripts/telegram.py update zip OK 2>/dev/null || true
    fi
fi

# ── Verify final ZIP path ─────────────────────────────────────────────────────
FINAL_ZIP=""
ZIP_NAME=""
ZIP_SIZE="0"

if [ "$OVERALL_EXIT" -eq 0 ]; then
    FINAL_ZIP_REPORT="bin/output/reports/final_zip_path.txt"
    if [ ! -f "$FINAL_ZIP_REPORT" ]; then
        echo "[ERROR] $FINAL_ZIP_REPORT was not created after packaging." >&2
        OVERALL_EXIT=1
    else
        FINAL_ZIP=$(cat "$FINAL_ZIP_REPORT")
        if [ -z "$FINAL_ZIP" ]; then
            echo "[ERROR] final_zip_path.txt is empty." >&2
            OVERALL_EXIT=1
        elif [ ! -f "$FINAL_ZIP" ]; then
            echo "[ERROR] Final ZIP not found at path: $FINAL_ZIP" >&2
            OVERALL_EXIT=1
        else
            ZIP_NAME=$(basename "$FINAL_ZIP")
            ZIP_SIZE=$(python3 -c \
                "import os; print(f'{os.path.getsize(\"$FINAL_ZIP\")/1024/1024:.1f}')" \
                2>/dev/null || echo "0")
            echo "[OK] Final ZIP: $ZIP_NAME (${ZIP_SIZE} MB)"
        fi
    fi
fi

# ── PixelDrain upload (ROM ZIP only — never sent to Telegram) ─────────────────
PIXELDRAIN_URL=""
if [ "$OVERALL_EXIT" -eq 0 ] \
    && [ "${UPLOAD_PIXELDRAIN:-false}" = "true" ] \
    && [ -n "$FINAL_ZIP" ] && [ -f "$FINAL_ZIP" ]; then

    echo ""
    echo "[UPLOAD] Uploading final ROM ZIP to PixelDrain..."

    if [ "${NOTIFY_TELEGRAM:-false}" = "true" ]; then
        $SUDO python3 bin/scripts/telegram.py update upload_pixeldrain RUN 2>/dev/null || true
    fi

    set +e
    $SUDO python3 bin/scripts/pixeldrain_upload.py "$FINAL_ZIP"
    PD_EXIT=$?
    set -e

    if [ "$PD_EXIT" -eq 0 ]; then
        PD_REPORT="bin/output/reports/pixeldrain_upload_report.json"
        if [ -f "$PD_REPORT" ]; then
            PIXELDRAIN_URL=$(python3 -c \
                "import json; d=json.load(open('$PD_REPORT')); print(d.get('url',''))" \
                2>/dev/null || echo "")
        fi
        echo "[OK] PixelDrain URL: ${PIXELDRAIN_URL:-unavailable}"
        if [ "${NOTIFY_TELEGRAM:-false}" = "true" ]; then
            $SUDO python3 bin/scripts/telegram.py update upload_pixeldrain OK 2>/dev/null || true
        fi
    else
        echo "[WARN] PixelDrain upload failed (exit $PD_EXIT)" >&2
    fi
fi

# ── Generate full mod report ──────────────────────────────────────────────────
echo ""
echo "[REPORT] Generating full mod report..."
$SUDO python3 bin/scripts/deadzone_full_mod_report.py \
    --work-dir "$(pwd)" \
    --style "${STYLE:-Plus}" 2>/dev/null || true

# ── Final Telegram status ─────────────────────────────────────────────────────
BUILD_END=$(date +%s)
BUILD_DIFF=$((BUILD_END - BUILD_START))
echo ""
echo "=========================================="
echo "  Build time : $((BUILD_DIFF / 60))m $((BUILD_DIFF % 60))s"

_NOTIFIED=1  # Prevent exit trap from sending a duplicate notification

if [ "$OVERALL_EXIT" -eq 0 ]; then
    echo "  Status     : SUCCESS"
    echo "=========================================="
    if [ "${NOTIFY_TELEGRAM:-false}" = "true" ]; then
        $SUDO python3 bin/scripts/telegram.py finish OK \
            --url "${PIXELDRAIN_URL:-}" \
            --zip "${ZIP_NAME:-}" \
            --size "${ZIP_SIZE:-0}" 2>/dev/null || true
    fi
else
    echo "  Status     : FAILED"
    echo "=========================================="

    # Create debug ZIP for failure analysis
    mkdir -p bin/output/reports bin/output/logs
    $SUDO python3 bin/scripts/debug_zip.py 2>/dev/null || true

    # Collect last useful error line from logs
    ERROR_TEXT=""
    if [ -f bin/output/reports/package_error_report.txt ]; then
        ERROR_TEXT=$(grep -m1 "^Reason:" bin/output/reports/package_error_report.txt \
            | sed 's/^Reason:[[:space:]]*//' | head -c 200 || true)
    fi
    for logf in /tmp/mezo_package.log /tmp/mezo_pack.log /tmp/mezo_build.log /tmp/mezo_setup.log; do
        if [ -z "$ERROR_TEXT" ] && [ -f "$logf" ]; then
            ERROR_TEXT=$(grep -i "error\|failed\|invalid" "$logf" 2>/dev/null \
                | tail -n3 | tr '\n' ' ' | head -c 200 || true)
        fi
    done

    DEBUG_ZIP_ARG=""
    if [ -f bin/output/reports/build_failure_debug.zip ]; then
        DEBUG_ZIP_ARG="build_failure_debug.zip"
    fi

    if [ "${NOTIFY_TELEGRAM:-false}" = "true" ]; then
        $SUDO python3 bin/scripts/telegram.py finish FAIL \
            ${ERROR_TEXT:+--error "$ERROR_TEXT"} \
            ${DEBUG_ZIP_ARG:+--debug-zip "$DEBUG_ZIP_ARG"} \
            2>/dev/null || true
    fi
fi

# ── Cleanup heavy intermediate directories (reports are preserved) ────────────
echo ""
echo "[CLEANUP] Removing heavy temporary directories..."
rm -rf bin/temp bin/work 2>/dev/null || true
rm -rf bin/output/images bin/output/system bin/output/vendor \
       bin/output/product bin/output/mi_ext 2>/dev/null || true
rm -f /tmp/tg_watch_stop /tmp/mezo_build.log /tmp/mezo_pack.log \
      /tmp/mezo_package.log /tmp/mezo_setup.log 2>/dev/null || true
echo "[CLEANUP] Done. Reports preserved at bin/output/reports/"

exit $OVERALL_EXIT
