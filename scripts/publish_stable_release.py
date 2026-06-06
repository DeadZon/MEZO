#!/usr/bin/env python3
"""DeadZone Telegram publisher for Stable ROM releases.

Reads output/reports/publish_payload.json and publishes to @xDeadZone.

Usage:
  python3 scripts/publish_stable_release.py [--dry-run]

Required env:
  TELEGRAM_BOT_TOKEN
  TELEGRAM_PUBLISH_CHANNEL_ID   (e.g., @xDeadZone or numeric chat id)
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.request
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (
    REPO_ROOT, REPORTS_DIR, PUBLISH_PAYLOAD, LOGS_DIR,
    log, _now_iso,
)

TELEGRAM_API = "https://api.telegram.org"
MAX_CAPTION  = 1024  # Telegram photo caption limit


# ── Post template (HTML, parse_mode="HTML") ────────────────────────────────────
# Dynamic fields are escaped with html.escape before insertion.
# Link hrefs are hardcoded except download_url which is URL-safe from PixelDrain.

POST_TEMPLATE = """\
DeadZone v1.1 {hyperos_version} {region}Stable {android} {os_tag}

Devices:
{device_name}
Code Name: #{codename}

Date: {publish_date}

Based on pure Global, China, Indian, Indonesian ROMs

Style:
DeadZone Stable

Developer:
MEZO

Changelog: <a href="https://t.me/xDeadZone/430">Here</a>

Downloads: <a href="{download_url}">Here</a>

Screenshots: <a href="https://t.me/DeadZoneCloud/572">Here</a>

Discussion: <a href="https://t.me/DeadZoneDiscussion">Here</a>

#{codename} #OS3 #HyperOS3 #{android_tag} #DeadZone #MEZO"""


def render_post(payload: dict) -> str:
    return POST_TEMPLATE.format(
        hyperos_version = escape(payload["hyperos_version"]),
        region          = escape(payload["region"]),
        android         = escape(payload["android"]),
        os_tag          = escape(payload["os_tag"]),
        device_name     = escape(payload["device_name"]),
        codename        = escape(payload["codename"]),
        publish_date    = escape(payload["publish_date"]),
        android_tag     = escape(payload["android_tag"]),
        download_url    = escape(payload["download_url"]),
    )


# ── Validation ─────────────────────────────────────────────────────────────────

def validate_payload(payload: dict, image_path: Path) -> tuple[bool, str]:
    """Return (ok, reason). reason is '' on success."""
    if not payload.get("publish"):
        return False, "publish_flag_false"
    if payload.get("style", "").lower() != "stable":
        return False, "not_stable"
    os_tag = payload.get("os_tag", "").upper()
    if not os_tag.startswith("OS3"):
        return False, "not_os3"
    region = payload.get("region", "")
    if region not in ("China", "Global"):
        return False, f"unsupported_region:{region}"
    if not payload.get("download_url"):
        return False, "missing_download_url"
    if not image_path.is_file():
        return False, f"image_not_found:{image_path}"
    return True, ""


# ── Telegram HTTP helpers ──────────────────────────────────────────────────────

def _tg_url(token: str, method: str) -> str:
    return f"{TELEGRAM_API}/bot{token}/{method}"


def _multipart_encode(fields: dict, files: dict) -> tuple[bytes, str]:
    """Build multipart/form-data body."""
    boundary = "----DeadZoneBoundary7c4a2b3f"
    body_parts: list[bytes] = []

    for name, value in fields.items():
        body_parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )

    for name, (filename, data, mime) in files.items():
        header = (
            f'--{boundary}\r\n'
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
            f'Content-Type: {mime}\r\n\r\n'
        )
        body_parts.append(header.encode() + data + b'\r\n')

    body_parts.append(f'--{boundary}--\r\n'.encode())
    body = b"".join(body_parts)
    content_type = f"multipart/form-data; boundary={boundary}"
    return body, content_type


def _tg_send_photo(
    token: str,
    chat_id: str,
    image_path: Path,
    caption: str,
    parse_mode: str = "HTML",
) -> dict:
    """Send a photo with caption via Bot API. Returns API response dict."""
    image_data = image_path.read_bytes()
    mime = mimetypes.guess_type(image_path.name)[0] or "image/jpeg"

    body, content_type = _multipart_encode(
        fields={"chat_id": str(chat_id), "caption": caption, "parse_mode": parse_mode},
        files={"photo": (image_path.name, image_data, mime)},
    )

    req = urllib.request.Request(
        _tg_url(token, "sendPhoto"),
        data=body,
        headers={"Content-Type": content_type},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _tg_send_message(
    token: str,
    chat_id: str,
    text: str,
    parse_mode: str = "HTML",
) -> dict:
    """Send an HTML message via Bot API."""
    payload_bytes = json.dumps({
        "chat_id":                  str(chat_id),
        "text":                     text,
        "parse_mode":               parse_mode,
        "disable_web_page_preview": True,
    }).encode("utf-8")
    req = urllib.request.Request(
        _tg_url(token, "sendMessage"),
        data=payload_bytes,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


# ── Publish logic ──────────────────────────────────────────────────────────────

def publish(
    token: str,
    channel_id: str,
    image_path: Path,
    post_text: str,
    dry_run: bool = False,
) -> bool:
    """Send the post to Telegram. Returns True on success."""
    if dry_run:
        print("[PUBLISH] --dry-run: would send the following post:")
        print("-" * 60)
        print(f"Image: {image_path}")
        print(post_text)
        print("-" * 60)
        return True

    # If caption fits in the Telegram limit, send as one photo+caption (HTML)
    if len(post_text.encode("utf-8")) <= MAX_CAPTION:
        try:
            resp = _tg_send_photo(token, channel_id, image_path, post_text, parse_mode="HTML")
            if not resp.get("ok"):
                log("PUBLISH_ERROR", details=str(resp))
                return False
        except Exception as exc:
            log("PUBLISH_ERROR", details=str(exc))
            return False
    else:
        # Caption too long: send photo with plain fallback caption, then full HTML post
        short_caption = "DeadZone Stable ROM Released"
        try:
            resp = _tg_send_photo(token, channel_id, image_path, short_caption, parse_mode="")
            if not resp.get("ok"):
                log("PUBLISH_ERROR", step="photo", details=str(resp))
                return False
        except Exception as exc:
            log("PUBLISH_ERROR", step="photo", details=str(exc))
            return False

        try:
            resp = _tg_send_message(token, channel_id, post_text, parse_mode="HTML")
            if not resp.get("ok"):
                log("PUBLISH_ERROR", step="text", details=str(resp))
                return False
        except Exception as exc:
            log("PUBLISH_ERROR", step="text", details=str(exc))
            return False

    return True


# ── Report ─────────────────────────────────────────────────────────────────────

def _write_publish_log(lines: list[str]) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    path = LOGS_DIR / "publish_stable_release.log"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ── Main ───────────────────────────────────────────────────────────────────────

def run_publish(dry_run: bool = False) -> int:
    log_lines: list[str] = [f"publish_stable_release run at {_now_iso()}"]

    # Load payload
    if not PUBLISH_PAYLOAD.is_file():
        log("PUBLIC_PUBLISH_SKIPPED", reason="publish_payload_not_found")
        log_lines.append("SKIP: publish_payload.json not found")
        _write_publish_log(log_lines)
        return 1

    try:
        payload = json.loads(PUBLISH_PAYLOAD.read_text(encoding="utf-8"))
    except Exception as exc:
        log("PUBLIC_PUBLISH_SKIPPED", reason=f"payload_parse_error:{exc}")
        log_lines.append(f"SKIP: payload parse error: {exc}")
        _write_publish_log(log_lines)
        return 1

    image_path = REPO_ROOT / payload.get("image", "assets/telegram/stable_release.jpg")

    # Validate
    ok, reason = validate_payload(payload, image_path)
    if not ok:
        log("PUBLIC_PUBLISH_SKIPPED", reason=reason)
        log_lines.append(f"SKIP: {reason}")
        _write_publish_log(log_lines)
        return 1

    # Credentials
    token      = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    channel_id = os.environ.get("TELEGRAM_PUBLISH_CHANNEL_ID", "").strip()

    if not token:
        log("PUBLIC_PUBLISH_SKIPPED", reason="TELEGRAM_BOT_TOKEN_not_set")
        log_lines.append("SKIP: TELEGRAM_BOT_TOKEN not set")
        _write_publish_log(log_lines)
        return 1

    if not channel_id:
        log("PUBLIC_PUBLISH_SKIPPED", reason="TELEGRAM_PUBLISH_CHANNEL_ID_not_set")
        log_lines.append("SKIP: TELEGRAM_PUBLISH_CHANNEL_ID not set")
        _write_publish_log(log_lines)
        return 1

    # Render post text
    post_text = render_post(payload)

    log_lines.append(f"Channel:    {channel_id}")
    log_lines.append(f"Image:      {image_path}")
    log_lines.append(f"Codename:   {payload['codename']}")
    log_lines.append(f"Version:    {payload['version']}")
    log_lines.append(f"Region:     {payload['region']}")
    log_lines.append(f"Download:   {payload['download_url']}")
    log_lines.append("")
    log_lines.append("Post preview:")
    log_lines.append("-" * 60)
    log_lines.append(post_text)
    log_lines.append("-" * 60)

    # Publish
    success = publish(token, channel_id, image_path, post_text, dry_run=dry_run)

    if success:
        log("PUBLIC_PUBLISH_SENT",
            codename=payload["codename"],
            version=payload["version"],
            channel=channel_id)
        log_lines.append("RESULT: SENT")
        _write_publish_log(log_lines)

        # Update queue item status to published
        _mark_queue_published(payload.get("codename"), payload.get("version"))
        return 0
    else:
        log("PUBLIC_PUBLISH_SKIPPED", reason="telegram_send_failed")
        log_lines.append("RESULT: FAILED")
        _write_publish_log(log_lines)
        return 1


def _mark_queue_published(codename: str | None, version: str | None) -> None:
    if not codename or not version:
        return
    from _common import load_queue, save_queue
    queue = load_queue()
    for item in queue:
        if item.get("codename") == codename and item.get("version") == version:
            item["status"] = "published"
            break
    save_queue(queue)


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish Stable ROM to Telegram")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print post preview without actually sending")
    args = parser.parse_args()
    sys.exit(run_publish(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
