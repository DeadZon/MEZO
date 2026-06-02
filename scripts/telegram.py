#!/usr/bin/env python3
"""Rich live Telegram dashboard for MEZO ROM Builder.
Ported and adapted from DeadZon/DeadZone factory/core/telegram.py.

Public API (importable by tg_watch.py):
  start_build(soc)
  update_stage(stage_id, status, action="", force=True)
  push_log_line(line)
  heartbeat()
  finish_build(status, upload_url="", final_zip_name="", final_zip_size_mib=0.0,
               error_text="", failed_stage="")

CLI:
  telegram.py start [soc]
  telegram.py update <stage_id> <RUN|OK|FAIL> [action]
  telegram.py heartbeat
  telegram.py finish <OK|FAIL> [--url U] [--zip Z] [--size S] [--error E] [--failed-stage F]

State:  output/reports/telegram_status.json
Report: output/reports/telegram_live_report.txt
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# ── Constants ─────────────────────────────────────────────────────────────────

STATE_FILE        = Path("output/reports/telegram_status.json")
REPORT_FILE       = Path("output/reports/telegram_live_report.txt")
MAX_TEXT          = 4000
MIN_EDIT_INTERVAL = 5.0   # minimum seconds between edits (rate-limit buffer)
LOG_BUFFER_MAX    = 5     # how many log lines to keep visible in message

# ── Pipeline stage definitions ────────────────────────────────────────────────
#   (id, icon, display label)
STAGES: list[tuple[str, str, str]] = [
    ("setup",             "🚀", "Setup & Checkout"),
    ("unpack",            "📦", "Extract / Unpack"),
    ("mods",              "🧩", "Mods & Patches"),
    ("rebuild",           "🛠",  "Rebuild Partitions"),
    ("super",             "💾", "Build Super Image"),
    ("vbmeta",            "🔐", "vbmeta"),
    ("zip",               "🗜",  "Create Final ZIP"),
    ("upload_pixeldrain", "☁️",  "PixelDrain Upload"),
]

_STAGE_ICON  = {s[0]: s[1] for s in STAGES}
_STAGE_LABEL = {s[0]: s[2] for s in STAGES}

# Progress-bar percentage reached when each stage completes or starts running.
_STAGE_DONE_PCT: dict[str, int] = {
    "setup":             10,
    "unpack":            20,
    "mods":              50,
    "rebuild":           60,
    "super":             70,
    "vbmeta":            80,
    "zip":               90,
    "upload_pixeldrain": 100,
}


# ── Device / GitHub context readers ──────────────────────────────────────────

def _read_device() -> dict:
    """Read MEZO ddevice output files (best-effort; empty if not yet written)."""
    mapping = {
        "device": "bin/ddevice/device_f.txt",
        "code":   "bin/ddevice/device_code.txt",
        "rom":    "bin/ddevice/base_rom_code.txt",
        "os":     "bin/ddevice/rom_os.txt",
        "ostype": "bin/ddevice/os_type.txt",
        "ver":    "bin/ddevice/androidver.txt",
    }
    info: dict = {}
    for key, fname in mapping.items():
        p = Path(fname)
        if p.is_file():
            val = p.read_text(encoding="utf-8", errors="replace").strip()
            if val:
                info[key] = val
    return info


def _github_ctx() -> dict:
    """Read GitHub Actions environment variables."""
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repo   = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    return {
        "workflow": os.environ.get("GITHUB_WORKFLOW", "MEZO"),
        "run":      os.environ.get("GITHUB_RUN_NUMBER", ""),
        "actor":    os.environ.get("GITHUB_ACTOR", ""),
        "sha":      (os.environ.get("GITHUB_SHA", "") or "")[:7],
        "branch":   os.environ.get("GITHUB_REF_NAME", ""),
        "url":      f"{server}/{repo}/actions/runs/{run_id}" if run_id else "",
        "soc":      os.environ.get("TG_SOC", ""),
    }


# ── Credentials ───────────────────────────────────────────────────────────────

def _collect_credentials() -> list[tuple[str, str]]:
    """Return all valid (token, chat_id) pairs from env, deduplicated by chat_id."""
    candidates = [
        (os.environ.get("TELEGRAM_BOT_TOKEN", ""),            os.environ.get("TELEGRAM_CHAT_ID", "")),
        (os.environ.get("TELEGRAM_MTK_BOT_TOKEN", ""),        os.environ.get("TELEGRAM_MTK_CHAT_ID", "")),
        (os.environ.get("TELEGRAM_SNAPDRAGON_BOT_TOKEN", ""), os.environ.get("TELEGRAM_SNAPDRAGON_CHAT_ID", "")),
    ]
    seen: set[str] = set()
    result: list[tuple[str, str]] = []
    for tok, cid in candidates:
        tok, cid = tok.strip(), cid.strip()
        if tok and cid and cid not in seen:
            seen.add(cid)
            result.append((tok, cid))
    return result


# ── State helpers ─────────────────────────────────────────────────────────────

def _empty_state() -> dict:
    return {
        "chats":               {},
        "started_at":          time.time(),
        "soc":                 "",
        "current_stage_id":    "setup",
        "current_stage_label": "Setup & Checkout",
        "current_action":      "",
        "log_buffer":          [],
        "events":              [],
        "failed_stage":        "",
        "error_text":          "",
        "upload_url":          "",
        "final_zip_name":      "",
        "final_zip_size_mib":  0.0,
        "last_edit_at":        0.0,
        "status":              "running",
    }


def load_state() -> dict:
    try:
        if STATE_FILE.is_file():
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return _empty_state()


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def _write_report(state: dict) -> None:
    try:
        REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "MEZO Telegram Live Report",
            "=" * 40,
            f"status:  {state.get('status', '')}",
            f"stage:   {state.get('current_stage_id', '')} — {state.get('current_stage_label', '')}",
            f"action:  {state.get('current_action', '')}",
            "",
            "events:",
        ]
        for ev in state.get("events", []):
            lines.append(f"  [{ev.get('status','?'):4s}] {ev.get('id','')}: {ev.get('label','')}")
        if state.get("upload_url"):
            lines.append(f"\nPixelDrain: {state['upload_url']}")
        REPORT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception:
        pass


# ── Telegram API ──────────────────────────────────────────────────────────────

def _post(token: str, method: str, payload: dict) -> dict:
    url  = f"https://api.telegram.org/bot{token}/{method}"
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req  = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        if "message is not modified" in body.lower():
            return {"ok": True}
        if "too many requests" in body.lower():
            return {"ok": False, "rate_limit": True, "error": f"HTTP {exc.code}: rate limited"}
        return {"ok": False, "error": f"HTTP {exc.code}: {body[:200]}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _send(token: str, chat_id: str, text: str) -> dict:
    return _post(token, "sendMessage", {
        "chat_id": chat_id,
        "text": text[:MAX_TEXT],
        "disable_web_page_preview": True,
    })


def _edit(token: str, chat_id: str, message_id: int, text: str) -> dict:
    return _post(token, "editMessageText", {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text[:MAX_TEXT],
        "disable_web_page_preview": True,
    })


# ── Message formatter ─────────────────────────────────────────────────────────

def _elapsed_str(started_at: float) -> str:
    secs = int(max(0, time.time() - started_at))
    h, rem = divmod(secs, 3600)
    m, s   = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _calc_progress(events: list[dict]) -> int:
    """Return 0-100 progress percentage based on stage events."""
    status_map: dict[str, str] = {}
    for ev in events:
        sid = ev.get("id", "")
        if sid in _STAGE_DONE_PCT:
            status_map[sid] = ev.get("status", "")

    pct = 0
    for sid, _, _ in STAGES:
        st = status_map.get(sid, "")
        if st in ("OK", "DONE", "RUN"):
            pct = _STAGE_DONE_PCT.get(sid, pct)
        if st == "RUN":
            break   # stop advancing at the currently running stage
    return pct


def _progress_bar(pct: int) -> str:
    filled = round(pct / 10)
    bar    = "█" * filled + "░" * (10 - filled)
    return f"📈 Progress: {bar} {pct}%"


def _progress_block(events: list[dict]) -> list[str]:
    """Return stage timeline lines (✅ / 🟡 / ❌ / ⚪) without OneDrive."""
    status_map: dict[str, str] = {}
    for ev in events:
        sid = ev.get("id", "")
        if sid:
            status_map[sid] = ev.get("status", "")

    lines: list[str] = []
    for sid, _icon, label in STAGES:
        st = status_map.get(sid, "")
        if st in ("OK", "DONE"):
            lines.append(f"✅ {label}")
        elif st == "RUN":
            lines.append(f"🟡 {label}")
        elif st in ("FAIL", "ERROR"):
            lines.append(f"❌ {label}")
        else:
            lines.append(f"⚪ {label}")
    return lines


def format_message(state: dict, build_status: str, upload_url: str = "") -> str:
    status = build_status.upper()
    is_running = status == "RUNNING"
    is_done    = status in ("OK", "DONE")
    is_failed  = not is_running and not is_done

    dev = _read_device()
    gh  = _github_ctx()

    soc       = state.get("soc") or gh.get("soc") or ""
    soc_label = {"mtk": "MTK", "snapdragon": "Snapdragon"}.get(soc.lower(), soc.upper() or "—")
    device    = dev.get("device") or dev.get("code") or "Detecting…"
    rom_ver   = dev.get("rom") or "—"
    android   = dev.get("ver") or ""
    rom_os    = dev.get("os") or dev.get("ostype") or "HyperOS"
    os_label  = f"{rom_os} / Android {android}" if android else rom_os
    branch    = gh.get("branch") or "—"
    sha       = gh.get("sha") or "—"

    elapsed     = _elapsed_str(state.get("started_at", time.time()))
    stage_id    = state.get("current_stage_id", "")
    stage_label = state.get("current_stage_label") or _STAGE_LABEL.get(stage_id, stage_id)
    stage_icon  = _STAGE_ICON.get(stage_id, "📍")
    cur_action  = state.get("current_action", "")
    log_buf     = state.get("log_buffer", [])
    events      = state.get("events", [])
    pct         = _calc_progress(events)
    bar_line    = _progress_bar(pct)

    out: list[str] = []

    # ── Header ────────────────────────────────────────────────────────────────
    if is_done:
        out.append("✅ MEZO Build Finished")
    elif is_failed:
        out.append("❌ MEZO Build Failed")
    else:
        out.append("🚀 MEZO Build Live")
    out.append("━━━━━━━━━━━━━━━━━━━━━━")
    out.append("")

    # ── Build metadata ────────────────────────────────────────────────────────
    out.append(f"📱 Device:  {device}")
    out.append(f"🧩 SoC:     {soc_label}")
    out.append(f"💿 ROM:     {rom_ver}")
    out.append(f"🤖 OS:      {os_label}")
    out.append(f"🌿 Branch:  {branch}")
    out.append(f"🔖 Commit:  {sha}")
    out.append("")

    # ── Status block ──────────────────────────────────────────────────────────
    if is_done:
        out.append("📊 Status:  ✅ SUCCESS")
        out.append(f"⏱ Total:   {elapsed}")
        out.append(bar_line)
    elif is_failed:
        out.append("📊 Status:  ❌ FAILED")
        out.append(f"⏱ Elapsed: {elapsed}")
        failed = state.get("failed_stage", "")
        err    = state.get("error_text", "")
        if failed:
            out.append(f"📍 Failed Stage: {_STAGE_LABEL.get(failed, failed)}")
        if err:
            out.append(f"💥 Cause:  {err[:150]}")
        out.append(bar_line)
    else:
        out.append("📊 Status:  🟡 RUNNING")
        out.append(f"⏱ Elapsed: {elapsed}")
        out.append(f"📍 Stage:   {stage_icon} {stage_label}")
        if cur_action:
            out.append(f"🔧 Now:     {cur_action[:65]}")
        out.append(bar_line)

    # ── Live log (running only) ───────────────────────────────────────────────
    if log_buf and is_running:
        out.append("")
        out.append("📝 Live Log:")
        for ln in log_buf[-LOG_BUFFER_MAX:]:
            out.append(f"  {ln[:72]}")

    # ── Progress timeline (running + done only) ───────────────────────────────
    if not is_failed:
        out.append("")
        out.append("Progress:")
        out.extend(_progress_block(events))

    # ── Success details ───────────────────────────────────────────────────────
    if is_done:
        actual_url = upload_url or state.get("upload_url", "")
        zip_name   = state.get("final_zip_name", "")
        zip_mib    = state.get("final_zip_size_mib", 0.0)
        if actual_url or zip_name or zip_mib:
            out.append("")
        if actual_url:
            out.append(f"☁️ PixelDrain: {actual_url}")
        if zip_name:
            out.append(f"📦 ZIP:  {zip_name}")
        if zip_mib:
            out.append(f"📏 Size: {zip_mib:.1f} MiB")

    # ── Failure: last log lines ───────────────────────────────────────────────
    if is_failed and log_buf:
        out.append("")
        out.append("📝 Last Log:")
        for ln in log_buf[-LOG_BUFFER_MAX:]:
            out.append(f"  {ln[:72]}")

    return "\n".join(out)


# ── Core push helper ──────────────────────────────────────────────────────────

def push_update(state: dict, text: str, *, force: bool = False) -> bool:
    """Edit the live message for all tracked chats.
    Returns True if at least one chat was updated.
    Respects MIN_EDIT_INTERVAL unless force=True.
    """
    now     = time.time()
    elapsed = now - state.get("last_edit_at", 0)

    if not force and elapsed < MIN_EDIT_INTERVAL:
        return False

    chats  = state.get("chats", {})
    any_ok = False

    for chat_id, info in chats.items():
        token  = info.get("token", "")
        msg_id = info.get("message_id")
        if not token or not msg_id:
            continue

        resp = _edit(token, chat_id, msg_id, text)
        if resp.get("ok"):
            result = resp.get("result") or {}
            if isinstance(result, dict) and result.get("message_id"):
                info["message_id"] = int(result["message_id"])
            any_ok = True
        elif resp.get("rate_limit"):
            print("[TELEGRAM] Rate limited — skipping edit", file=sys.stderr)
            return False
        else:
            # Fallback: send a new message to this chat
            fb = _send(token, chat_id, text)
            if fb.get("ok"):
                result = fb.get("result") or {}
                if isinstance(result, dict) and result.get("message_id"):
                    info["message_id"] = int(result["message_id"])
                any_ok = True
            else:
                err = resp.get("error") or fb.get("error") or "unknown"
                print(f"[TELEGRAM] Edit+fallback failed ...{chat_id[-4:]}: {err}", file=sys.stderr)

    if any_ok:
        state["last_edit_at"] = now
    return any_ok


# ── Public API ────────────────────────────────────────────────────────────────

def start_build(soc: str = "") -> None:
    """Send the initial live Telegram message and persist state."""
    credentials = _collect_credentials()
    if not credentials:
        print("[TELEGRAM] No credentials — notifications disabled", file=sys.stderr)
        save_state(_empty_state())
        return

    gh  = _github_ctx()
    soc = soc or gh.get("soc") or ""

    state = _empty_state()
    state["soc"] = soc
    state["events"].append({"id": "setup", "status": "OK", "label": "Setup & Checkout"})

    text = format_message(state, "RUNNING")

    for token, chat_id in credentials:
        resp = _send(token, chat_id, text)
        if resp.get("ok"):
            result = resp.get("result") or {}
            msg_id = result.get("message_id") if isinstance(result, dict) else None
            state["chats"][chat_id] = {
                "token":      token,
                "message_id": int(msg_id) if msg_id else None,
            }
            print(f"[TELEGRAM] Started → ...{chat_id[-4:]} msg_id={msg_id}")
        else:
            print(f"[TELEGRAM] Start failed ...{chat_id[-4:]}: {resp.get('error','?')}", file=sys.stderr)

    state["last_edit_at"] = time.time()
    save_state(state)
    _write_report(state)


def update_stage(stage_id: str, status: str, action: str = "", *, force: bool = True) -> None:
    """Record a stage status change and push an edit."""
    state  = load_state()
    status = status.upper()
    label  = _STAGE_LABEL.get(stage_id, stage_id)

    state.setdefault("events", []).append({"id": stage_id, "status": status, "label": label})

    if status == "RUN":
        state["current_stage_id"]    = stage_id
        state["current_stage_label"] = label
        if action:
            state["current_action"] = action

    if status in ("FAIL", "ERROR"):
        state["failed_stage"] = stage_id
        state["status"]       = "failed"

    build_status = "FAILED" if status in ("FAIL", "ERROR") else "RUNNING"
    text = format_message(state, build_status)
    push_update(state, text, force=force)
    save_state(state)
    _write_report(state)


def push_log_line(line: str) -> None:
    """Append a log line to the buffer and conditionally push a Telegram edit."""
    state = load_state()
    buf   = state.setdefault("log_buffer", [])
    line  = line.strip()
    if not line:
        return

    # Map to emoji-prefixed entry
    if "[MODS]"      in line: icon = "🧩"
    elif "[PATCH]"   in line: icon = "🔧"
    elif "[UNPACK"   in line: icon = "📦"
    elif "[REPACK]"  in line: icon = "🛠"
    elif "[UPLOADING]" in line: icon = "☁️"
    elif "[ERROR]"   in line: icon = "❌"
    elif "[WARN]"    in line: icon = "⚠️"
    elif "[INFO]"    in line: icon = "ℹ️"
    else:                      icon = "▸"

    buf.append(f"{icon} {line}")
    if len(buf) > LOG_BUFFER_MAX:
        buf.pop(0)
    state["log_buffer"] = buf

    # Extract current action from known prefixes
    for pfx in ("[MODS] - ", "[PATCH] - ", "[UNPACK] - ", "[REPACK] - ",
                "[UPLOADING] - ", "[INFO] - ", "[UNPACK - EROFS] - ", "[UNPACK - EXT4] - "):
        if pfx in line:
            state["current_action"] = line.split(pfx, 1)[1].strip()[:80]
            break

    important = any(kw in line for kw in (
        "[ERROR]", "[WARN]",
        "Fixing Delay Power Button",
        "Patching miui-services.jar",
        "Remove Region Check",
        "Add ROM Information",
        "Updating getMiuiVersionInCard",
        "Updating getRoXmsVersion",
        "Updating getXmsVersion",
        "Updating getSimpleOSVersionCode",
        "PixelDrain",
        "Build completed",
        "Packing super.img",
    ))

    text = format_message(state, "RUNNING")
    push_update(state, text, force=important)
    save_state(state)


def heartbeat() -> None:
    """Force an elapsed-time update (ignores rate-limit interval)."""
    state = load_state()
    text  = format_message(state, "RUNNING")
    push_update(state, text, force=True)
    save_state(state)


def finish_build(
    status: str,
    upload_url: str = "",
    final_zip_name: str = "",
    final_zip_size_mib: float = 0.0,
    error_text: str = "",
    failed_stage: str = "",
) -> None:
    """Push the final success or failure message."""
    state  = load_state()
    final  = status.upper()

    if upload_url:         state["upload_url"]          = upload_url
    if final_zip_name:     state["final_zip_name"]       = final_zip_name
    if final_zip_size_mib: state["final_zip_size_mib"]   = final_zip_size_mib
    if error_text:         state["error_text"]           = error_text[:200]
    if failed_stage:       state["failed_stage"]         = failed_stage

    if final in ("OK", "DONE"):
        # Mark every stage OK so progress shows 100% and all stages show ✅
        existing_ok = {
            ev["id"] for ev in state.get("events", [])
            if ev.get("status") in ("OK", "DONE")
        }
        for sid, _icon, label in STAGES:
            if sid not in existing_ok:
                state["events"].append({"id": sid, "status": "OK", "label": label})

    state["status"] = "done" if final in ("OK", "DONE") else "failed"
    state.setdefault("events", []).append({"id": "final", "status": final, "label": "Build complete"})

    text = format_message(state, final, upload_url=upload_url)
    push_update(state, text, force=True)
    save_state(state)
    _write_report(state)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    argv = sys.argv[1:]
    if not argv:
        print("Usage: telegram.py <start|update|heartbeat|finish> [args...]")
        sys.exit(1)

    cmd  = argv[0]
    rest = argv[1:]

    if cmd == "start":
        soc = rest[0] if rest else os.environ.get("TG_SOC", "")
        start_build(soc=soc)

    elif cmd == "update" and len(rest) >= 2:
        update_stage(rest[0], rest[1], action=rest[2] if len(rest) >= 3 else "")

    elif cmd == "heartbeat":
        heartbeat()

    elif cmd == "finish" and rest:
        status       = rest[0]
        url          = ""
        zip_name     = ""
        zip_mib      = 0.0
        error_text   = ""
        failed_stage = ""
        i = 1
        while i < len(rest):
            flag = rest[i]
            val  = rest[i + 1] if i + 1 < len(rest) else ""
            if flag == "--url":           url = val;            i += 2
            elif flag == "--zip":         zip_name = val;       i += 2
            elif flag == "--size":
                try: zip_mib = float(val)
                except ValueError: pass
                i += 2
            elif flag == "--error":       error_text = val;     i += 2
            elif flag == "--failed-stage": failed_stage = val;  i += 2
            else:                         i += 1
        finish_build(status, upload_url=url, final_zip_name=zip_name,
                     final_zip_size_mib=zip_mib, error_text=error_text,
                     failed_stage=failed_stage)

    else:
        print(f"[TELEGRAM] Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
