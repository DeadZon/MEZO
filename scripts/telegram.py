#!/usr/bin/env python3
"""Telegram live build notifications for MEZO ROM builder.
Ported from DeadZon/DeadZone factory/core/telegram.py.

Usage:
  telegram.py start
  telegram.py update <stage_id> <RUN|OK|FAIL>
  telegram.py finish <OK|FAIL> [pixeldrain_url]

Credentials (set as env vars, all optional — missing means disabled):
  TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID
  TELEGRAM_MTK_BOT_TOKEN / TELEGRAM_MTK_CHAT_ID
  TELEGRAM_SNAPDRAGON_BOT_TOKEN / TELEGRAM_SNAPDRAGON_CHAT_ID

State persisted to: output/reports/telegram_status.json
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

STATE_FILE = Path("output/reports/telegram_status.json")
MAX_TEXT_LEN = 4000

# Ordered pipeline stages shown in the timeline block.
STAGES: list[tuple[str, str, str]] = [
    ("build_rom",          "Building ROM",             "ROM built"),
    ("pack_rom",           "Packing ROM",              "ROM packed"),
    ("upload_pixeldrain",  "Uploading to PixelDrain",  "PixelDrain upload done"),
    ("upload_onedrive",    "Uploading to OneDrive",    "OneDrive upload done"),
]


# ── Helpers ──────────────────────────────────────────────────────────────────

def _read_device_info() -> dict:
    """Read device metadata from MEZO detection output files (best-effort)."""
    mapping = {
        "device_f":      "bin/ddevice/device_f.txt",
        "device_code":   "bin/ddevice/device_code.txt",
        "base_rom_code": "bin/ddevice/base_rom_code.txt",
        "rom_os":        "bin/ddevice/rom_os.txt",
        "os_type":       "bin/ddevice/os_type.txt",
        "androidver":    "bin/ddevice/androidver.txt",
    }
    info: dict = {}
    for key, fname in mapping.items():
        try:
            p = Path(fname)
            if p.is_file():
                val = p.read_text(encoding="utf-8", errors="replace").strip()
                if val:
                    info[key] = val
        except Exception:
            pass
    return info


def _collect_credentials() -> list[tuple[str, str]]:
    """Return all valid (token, chat_id) pairs from env vars, deduped."""
    candidates = [
        (os.environ.get("TELEGRAM_BOT_TOKEN", ""),          os.environ.get("TELEGRAM_CHAT_ID", "")),
        (os.environ.get("TELEGRAM_MTK_BOT_TOKEN", ""),      os.environ.get("TELEGRAM_MTK_CHAT_ID", "")),
        (os.environ.get("TELEGRAM_SNAPDRAGON_BOT_TOKEN", ""), os.environ.get("TELEGRAM_SNAPDRAGON_CHAT_ID", "")),
    ]
    seen: set[str] = set()
    result: list[tuple[str, str]] = []
    for token, chat_id in candidates:
        token = token.strip()
        chat_id = chat_id.strip()
        if token and chat_id and chat_id not in seen:
            seen.add(chat_id)
            result.append((token, chat_id))
    return result


def _load_state() -> dict:
    try:
        if STATE_FILE.is_file():
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"chats": {}, "events": [], "started_at": time.time()}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


# ── Telegram API ─────────────────────────────────────────────────────────────

def _post(token: str, method: str, payload: dict) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
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
        return {"ok": False, "error": f"HTTP {exc.code}: {body[:200]}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _send(token: str, chat_id: str, text: str) -> dict:
    return _post(token, "sendMessage", {
        "chat_id": chat_id,
        "text": text[:MAX_TEXT_LEN],
        "disable_web_page_preview": True,
    })


def _edit(token: str, chat_id: str, message_id: int, text: str) -> dict:
    return _post(token, "editMessageText", {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text[:MAX_TEXT_LEN],
        "disable_web_page_preview": True,
    })


# ── Message formatter ─────────────────────────────────────────────────────────

def _format_message(state: dict, build_status: str, upload_url: str = "") -> str:
    build_status = build_status.upper()
    is_running = build_status == "RUNNING"
    is_done    = build_status in ("OK", "DONE")
    is_failed  = not is_running and not is_done

    info = _read_device_info()
    elapsed_secs = int(max(0, time.time() - state.get("started_at", time.time())))
    mins, secs = divmod(elapsed_secs, 60)
    elapsed_str = f"{mins:02d}:{secs:02d}"

    device   = info.get("device_f") or info.get("device_code") or "Detecting..."
    rom_ver  = info.get("base_rom_code") or "Unknown"
    os_label = info.get("rom_os") or info.get("os_type") or "HyperOS"

    lines: list[str] = []

    if is_done:
        lines.append("✅ MEZO Build Completed")
    elif is_failed:
        lines.append("❌ MEZO Build Failed")
    else:
        lines.append("🔥 MEZO ROM Builder Live")

    lines.append("")
    lines.append(f"Device:  {device}")
    lines.append(f"ROM:     {rom_ver}")
    lines.append(f"OS:      {os_label}")
    lines.append(f"Status:  {'RUNNING' if is_running else ('DONE' if is_done else 'FAILED')}")
    lines.append(f"Elapsed: {elapsed_str}")

    # Collapse events: stage_id → latest status
    collapsed: dict[str, str] = {}
    for ev in state.get("events", []):
        name = ev.get("name", "")
        if name:
            collapsed[name] = ev.get("status", "")

    # Current active stage label (running only)
    if is_running:
        for sid, label, _ in STAGES:
            if collapsed.get(sid) == "RUN":
                lines.append("")
                lines.append(f"▶ {label}")
                break

    # Timeline block
    running_idx = -1
    for i, (sid, _, _) in enumerate(STAGES):
        if collapsed.get(sid) == "RUN":
            running_idx = i
            break

    timeline: list[str] = []
    for i, (sid, label, done_label) in enumerate(STAGES):
        st = collapsed.get(sid, "")
        if st == "OK":
            timeline.append(f"✅ {done_label}")
        elif st == "RUN":
            timeline.append(f"🔄 {label}")
        elif st == "FAIL":
            timeline.append(f"❌ {label}")
        elif running_idx >= 0 and i > running_idx:
            timeline.append(f"⏳ {label}")

    if timeline:
        lines.append("")
        lines.append("Timeline:")
        lines.extend(timeline)

    if is_done and upload_url:
        lines.append("")
        lines.append(f"PixelDrain: {upload_url}")

    if is_failed:
        failed = state.get("failed_stage", "")
        if failed:
            lines.append("")
            lines.append(f"Failed at: {failed}")

    return "\n".join(lines)


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_start() -> None:
    credentials = _collect_credentials()
    if not credentials:
        print("[TELEGRAM] No credentials found — notifications disabled", file=sys.stderr)
        return

    state: dict = {"chats": {}, "events": [], "started_at": time.time()}
    state["events"].append({"name": "started", "status": "RUN"})

    text = _format_message(state, "RUNNING")

    for token, chat_id in credentials:
        resp = _send(token, chat_id, text)
        if resp.get("ok"):
            result = resp.get("result") or {}
            msg_id = result.get("message_id") if isinstance(result, dict) else None
            state["chats"][chat_id] = {"token": token, "message_id": int(msg_id) if msg_id else None}
            print(f"[TELEGRAM] Started → chat ...{chat_id[-4:]} msg_id={msg_id}")
        else:
            print(f"[TELEGRAM] Send failed chat ...{chat_id[-4:]}: {resp.get('error', 'unknown')}", file=sys.stderr)

    _save_state(state)


def cmd_update(stage: str, status: str) -> None:
    state = _load_state()
    state.setdefault("events", []).append({"name": stage, "status": status.upper()})

    credentials = _collect_credentials()
    chats = state.get("chats", {})

    if not credentials or not chats:
        _save_state(state)
        return

    text = _format_message(state, "RUNNING")

    for token, chat_id in credentials:
        chat_info = chats.get(chat_id)
        if not chat_info:
            continue
        msg_id = chat_info.get("message_id")
        if msg_id is None:
            continue
        resp = _edit(token, chat_id, msg_id, text)
        if resp.get("ok"):
            result = resp.get("result") or {}
            if isinstance(result, dict) and result.get("message_id"):
                chats[chat_id]["message_id"] = int(result["message_id"])
            print(f"[TELEGRAM] Updated → chat ...{chat_id[-4:]} stage={stage} status={status}")
        else:
            # Fallback: send new message if edit fails
            fallback = _send(token, chat_id, text)
            if fallback.get("ok"):
                fresult = fallback.get("result") or {}
                if isinstance(fresult, dict) and fresult.get("message_id"):
                    chats[chat_id]["message_id"] = int(fresult["message_id"])
            else:
                print(f"[TELEGRAM] Update failed chat ...{chat_id[-4:]}: {resp.get('error', '')}", file=sys.stderr)

    _save_state(state)


def cmd_finish(status: str, upload_url: str = "") -> None:
    state = _load_state()
    final_status = status.upper()
    state.setdefault("events", []).append({"name": "final_status", "status": final_status})
    if upload_url:
        state["upload_url"] = upload_url

    credentials = _collect_credentials()
    if not credentials:
        _save_state(state)
        return

    text = _format_message(state, final_status, upload_url=upload_url)
    chats = state.setdefault("chats", {})

    for token, chat_id in credentials:
        chat_info = chats.get(chat_id, {})
        msg_id = chat_info.get("message_id")

        if msg_id:
            resp = _edit(token, chat_id, msg_id, text)
        else:
            resp = _send(token, chat_id, text)

        if resp.get("ok"):
            result = resp.get("result") or {}
            if isinstance(result, dict) and result.get("message_id"):
                if chat_id not in chats:
                    chats[chat_id] = {"token": token}
                chats[chat_id]["message_id"] = int(result["message_id"])
            print(f"[TELEGRAM] Finished '{final_status}' → chat ...{chat_id[-4:]}")
        else:
            print(f"[TELEGRAM] Finish failed chat ...{chat_id[-4:]}: {resp.get('error', 'unknown')}", file=sys.stderr)

    state["status"] = final_status
    _save_state(state)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    args = sys.argv[1:]
    if not args:
        print("Usage: telegram.py <start | update <stage> <status> | finish <OK|FAIL> [url]>")
        sys.exit(1)

    cmd = args[0]

    if cmd == "start":
        cmd_start()
    elif cmd == "update" and len(args) >= 3:
        cmd_update(args[1], args[2])
    elif cmd == "finish" and len(args) >= 2:
        cmd_finish(args[1], args[2] if len(args) >= 3 else "")
    else:
        print(f"[TELEGRAM] Unknown command: {' '.join(args)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
