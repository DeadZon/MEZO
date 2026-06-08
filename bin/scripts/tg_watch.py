#!/usr/bin/env python3
"""Background live-log watcher for MEZO Telegram notifications.
Adapted from DeadZon/DeadZone event-bus and stage-tracking patterns.

Follows a build log file in real time, parses MEZO log markers,
and drives live Telegram message edits via telegram.py.

Usage:
  tg_watch.py <log_file_path> <initial_stage_id>

Stop signals:
  - Touch /tmp/tg_watch_stop   (preferred — clean exit after current line)
  - SIGTERM / SIGINT           (sets running=False; exits after current poll)

Timing:
  - Polls log file every POLL_INTERVAL seconds
  - Sends a heartbeat (elapsed-time) update every HEARTBEAT_INTERVAL seconds
  - Stage changes and important lines are pushed immediately (force=True)
  - Normal log lines are throttled by telegram.MIN_EDIT_INTERVAL
"""
from __future__ import annotations

import os
import signal
import sys
import time
from pathlib import Path

# Import telegram.py from the same directory without relying on sys.path
import importlib.util as _ilu

_spec = _ilu.spec_from_file_location(
    "mezo_telegram",
    Path(__file__).parent / "telegram.py",
)
_mod = _ilu.module_from_spec(_spec)       # type: ignore[arg-type]
_spec.loader.exec_module(_mod)            # type: ignore[union-attr]
tg = _mod

# ── Tuning ────────────────────────────────────────────────────────────────────

POLL_INTERVAL     = 0.5   # seconds between log-file polls
HEARTBEAT_INTERVAL = 30.0 # seconds between forced elapsed-time updates
STOP_FILE         = Path("/tmp/tg_watch_stop")

# ── Stage-advancement rules ───────────────────────────────────────────────────
# When a log line contains the marker (first match wins), advance to that stage.
# Ordered from most-specific to least-specific.
_MARKER_STAGE: list[tuple[str, str]] = [
    ("[UNPACK - EROFS]",           "unpack"),
    ("[UNPACK - EXT4]",            "unpack"),
    ("[UNPACK]",                   "unpack"),
    ("[MODS]",                     "mods"),
    ("[PATCH]",                    "mods"),
    ("Fixing Delay Power Button",  "mods"),
    ("Patching miui-services.jar", "mods"),
    ("Remove Region Check",        "mods"),
    ("Add ROM Information",        "mods"),
    ("[REPACK]",                   "rebuild"),
    ("Rebuild",                    "rebuild"),
    ("Successfully packed super.img", "super"),
    ("Packing super.img",          "super"),
    ("[VBMETA]",                   "vbmeta"),
    ("vbmeta",                     "vbmeta"),
    ("[PACKAGE]",                  "zip"),
    ("[ZIP]",                      "zip"),
    ("Extracting template",        "zip"),
    ("Building: DeadZone_",        "zip"),
    ("[UPLOADING]",                "zip"),
    ("[UPLOAD]",                   "upload_pixeldrain"),
    ("PixelDrain",                 "upload_pixeldrain"),
]

# Lines that bypass the rate-limit and trigger an immediate Telegram edit.
_FORCE_KEYWORDS = (
    "[ERROR]",
    "[WARN]",
    "[VBMETA]",
    "[PACKAGE]",
    "Fixing Delay Power Button",
    "Patching miui-services.jar",
    "Remove Region Check",
    "Add ROM Information",
    "Updating getMiuiVersionInCard",
    "Updating getRoXmsVersion",
    "Updating getXmsVersion",
    "Updating getSimpleOSVersionCode",
    "Successfully packed super.img",
    "Extracting template",
    "Building: DeadZone_",
    "PixelDrain",
    "Build completed",
    "Packing super.img",
)


def _map_stage(line: str) -> str | None:
    for marker, stage_id in _MARKER_STAGE:
        if marker in line:
            return stage_id
    return None


def _is_force(line: str) -> bool:
    return any(kw in line for kw in _FORCE_KEYWORDS)


# ── Main loop ─────────────────────────────────────────────────────────────────

def run(log_file: Path, initial_stage: str) -> None:
    STOP_FILE.unlink(missing_ok=True)

    running        = [True]
    current_stage  = initial_stage
    last_heartbeat = time.time()
    file_pos       = 0
    _last_line     = ""       # for consecutive-duplicate suppression
    _dup_count     = 0        # how many times the current line repeated

    def _handle_signal(sig: int, frame: object) -> None:
        running[0] = False

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT,  _handle_signal)

    print(f"[TG_WATCH] Started — log={log_file}  stage={initial_stage}  pid={os.getpid()}")

    while running[0]:
        # ── Stop-file check ───────────────────────────────────────────────────
        if STOP_FILE.exists():
            print("[TG_WATCH] Stop file detected — exiting cleanly")
            break

        # ── Read new log lines ────────────────────────────────────────────────
        try:
            if log_file.is_file():
                with log_file.open("r", encoding="utf-8", errors="replace") as fh:
                    fh.seek(file_pos)
                    new_lines = fh.readlines()
                    file_pos  = fh.tell()

                for raw in new_lines:
                    line = raw.rstrip()
                    if not line:
                        continue

                    # ── Consecutive-duplicate suppression ─────────────────────
                    # If the same line repeats, collapse it into a count suffix
                    # and only forward once. Reset on any different line.
                    if line == _last_line:
                        _dup_count += 1
                        if _dup_count == 1:
                            # First repeat: replace buffer entry with "×2" suffix
                            collapsed = f"{line} ×2"
                            try:
                                tg.push_log_line(collapsed)
                            except Exception:
                                pass
                        # Subsequent identical repeats: skip entirely
                        continue
                    else:
                        _last_line = line
                        _dup_count = 0

                    # Advance stage if a known marker is found
                    new_stage = _map_stage(line)
                    if new_stage and new_stage != current_stage:
                        current_stage = new_stage
                        print(f"[TG_WATCH] Stage → {current_stage}")
                        try:
                            tg.update_stage(current_stage, "RUN", force=True)
                        except Exception as exc:
                            print(f"[TG_WATCH] update_stage error: {exc}", file=sys.stderr)
                        time.sleep(0.05)   # brief pause so the edit lands

                    # Push log line (handles buffer, action extraction, throttled edit)
                    try:
                        tg.push_log_line(line)
                    except Exception as exc:
                        print(f"[TG_WATCH] push_log_line error: {exc}", file=sys.stderr)

                    # Force an immediate re-edit for important lines
                    if _is_force(line):
                        try:
                            state = tg.load_state()
                            state["last_edit_at"] = 0   # reset throttle
                            tg.save_state(state)
                            tg.push_log_line(line)      # re-push with force
                        except Exception:
                            pass

        except Exception as exc:
            print(f"[TG_WATCH] Log read error: {exc}", file=sys.stderr)

        # ── Heartbeat ─────────────────────────────────────────────────────────
        now = time.time()
        if now - last_heartbeat >= HEARTBEAT_INTERVAL:
            try:
                tg.heartbeat()
                last_heartbeat = now
                print(f"[TG_WATCH] Heartbeat sent (elapsed update)")
            except Exception as exc:
                print(f"[TG_WATCH] Heartbeat error: {exc}", file=sys.stderr)

        time.sleep(POLL_INTERVAL)

    print("[TG_WATCH] Exited")


def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: tg_watch.py <log_file> <initial_stage>", file=sys.stderr)
        sys.exit(1)

    log_file      = Path(sys.argv[1])
    initial_stage = sys.argv[2]
    run(log_file, initial_stage)


if __name__ == "__main__":
    main()
