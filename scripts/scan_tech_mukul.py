#!/usr/bin/env python3
"""TECH_MUKUL Telegram scanner for DeadZone Auto Stable Builder.

Fetches recent posts from https://t.me/s/TECH_MUKUL, extracts ROM info,
and adds valid OS3 CN/Global Stable ROMs to output/queue/auto_build_queue.json.

Usage:
  python3 scripts/scan_tech_mukul.py [--dry-run] [--max-posts N]

Outputs:
  output/queue/auto_build_queue.json   — updated queue
  output/reports/scan_report.txt       — scan summary
  output/logs/scan_tech_mukul.log      — detailed log
"""
from __future__ import annotations

import argparse
import sys
import urllib.error
import urllib.request
import re
import json
from datetime import datetime
from pathlib import Path
from html import unescape

# Add scripts/ dir so _common is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (
    QUEUE_FILE, REPORTS_DIR, LOGS_DIR,
    load_supported_codenames, get_soc_for_codename, get_device_display_name,
    load_queue, save_queue, is_duplicate, make_queue_id, _now_iso,
    detect_os3, detect_region, detect_stable,
    extract_version, extract_codename, extract_download_urls,
    detect_rom_type, extract_android_version,
    format_hyperos_version, format_os_tag, log,
)

TECH_MUKUL_URL = "https://t.me/s/TECH_MUKUL"
SOURCE_NAME    = "TECH_MUKUL"
USER_AGENT     = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


# ── Fetch ──────────────────────────────────────────────────────────────────────

def fetch_page(url: str = TECH_MUKUL_URL) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        log("SCAN_ERROR", f"fetch failed: {exc}")
        raise


# ── Parse ──────────────────────────────────────────────────────────────────────

def _strip_html(raw: str) -> str:
    """Remove HTML tags and decode entities."""
    text = re.sub(r'<br\s*/?>', '\n', raw, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = unescape(text)
    return re.sub(r' +', ' ', text).strip()


def parse_messages(html: str) -> list[dict]:
    """Extract post records from Telegram web HTML."""
    messages: list[dict] = []

    # Find positions of all posts by data-post attribute
    post_positions = [
        (m.start(), m.group(1))
        for m in re.finditer(r'data-post="TECH_MUKUL/(\d+)"', html)
    ]
    if not post_positions:
        return messages

    for idx, (pos, post_num) in enumerate(post_positions):
        end_pos = post_positions[idx + 1][0] if idx + 1 < len(post_positions) else len(html)
        chunk = html[pos:end_pos]

        # --- Post text ---
        text_raw = ""
        tm = re.search(
            r'class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
            chunk, re.DOTALL
        )
        if tm:
            text_raw = tm.group(1)
        text = _strip_html(text_raw)

        # --- All hrefs in chunk ---
        links = re.findall(r'href="([^"#][^"]*)"', chunk)

        # --- Post datetime ---
        dt_str = ""
        dtm = re.search(r'datetime="([^"]+)"', chunk)
        if dtm:
            dt_str = dtm.group(1)

        post_url = f"https://t.me/TECH_MUKUL/{post_num}"
        messages.append({
            "post_num": int(post_num),
            "post_url": post_url,
            "text":     text,
            "text_raw": text_raw,
            "links":    links,
            "datetime": dt_str,
        })

    return messages


# ── Filter / classify ──────────────────────────────────────────────────────────

REJECT_TAGS = {
    "beta":              "beta_release",
    "alpha":             "beta_release",
    "developer":         "beta_release",
    "preview":           "beta_release",
    "eu rom":            "unsupported_region",
    "eea":               "unsupported_region",
    "india":             "unsupported_region",
    "indonesia":         "unsupported_region",
    "legend":            "unsupported_style",
    "gaming":            "unsupported_style",
    "epic":              "unsupported_style",
    "paid":              "unsupported_style",
    "os1":               "non_os3",
    "os2":               "non_os3",
    "miui 14":           "non_os3",
    "miui 13":           "non_os3",
    "hyperos 1":         "non_os3",
    "hyperos 2":         "non_os3",
}


def classify_post(post: dict, supported: set[str]) -> tuple[str | None, str | None]:
    """
    Returns (reason_to_skip, None) if rejected, or (None, rom_url) if accepted.
    """
    text = post["text"]
    links = post["links"]

    # --- Early text-based reject ---
    text_lower = text.lower()
    for kw, reason in REJECT_TAGS.items():
        if kw in text_lower:
            return reason, None

    # --- Must be OS3 ---
    if not detect_os3(text):
        return "non_os3", None

    # --- Must be Stable ---
    if not detect_stable(text):
        return "beta_release", None

    # --- Version ---
    version = extract_version(text)
    if not version:
        return "missing_version", None

    # --- Region ---
    region = detect_region(text, version)
    if region is None:
        return "unsupported_region", None
    if region not in ("China", "Global"):
        return "unsupported_region", None

    # --- Codename ---
    codename = extract_codename(text, links, supported)
    if not codename:
        return "missing_codename", None
    if codename not in supported:
        return "unsupported_device", None

    # --- Download URL ---
    dl_urls = extract_download_urls(links)
    if not dl_urls:
        return "missing_rom_url", None

    return None, None  # accepted — caller will build item


def build_queue_item(post: dict, supported: set[str]) -> dict | None:
    """Return a queue item dict for a valid post, or None."""
    text  = post["text"]
    links = post["links"]

    version  = extract_version(text)
    region   = detect_region(text, version or "")
    codename = extract_codename(text, links, supported)

    if not all([version, region, codename]):
        return None

    dl_urls  = extract_download_urls(links)
    if not dl_urls:
        return None

    # Prefer fastboot URL; fall back to recovery
    rom_type = "recovery"
    rom_url  = dl_urls[0]
    for u in dl_urls:
        if "fastboot" in u.lower():
            rom_url  = u
            rom_type = "fastboot"
            break

    soc       = get_soc_for_codename(codename)
    dev_name  = get_device_display_name(codename)
    android   = extract_android_version(text)
    os_tag    = format_os_tag(version)
    hyperos_v = format_hyperos_version(version)

    return {
        "id":              make_queue_id(codename, version, region),
        "source":          SOURCE_NAME,
        "source_post_url": post["post_url"],
        "codename":        codename,
        "device_name":     dev_name,
        "soc":             soc,
        "version":         version,
        "region":          region,
        "android":         android,
        "os_tag":          os_tag,
        "hyperos_version": hyperos_v,
        "rom_type":        rom_type,
        "rom_url":         rom_url,
        "style":           "Stable",
        "queued_at":       _now_iso(),
        "status":          "queued",
    }


# ── Queue management ───────────────────────────────────────────────────────────

def _queue_item_exists(queue: list[dict], item: dict) -> bool:
    for q in queue:
        if q.get("id") == item["id"]:
            return True
        if (q.get("codename") == item["codename"]
                and q.get("version") == item["version"]
                and q.get("region") == item["region"]):
            return True
    return False


# ── Report ─────────────────────────────────────────────────────────────────────

def _write_report(lines: list[str]) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / "scan_report.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[SCAN] Report written to {path}")


def _write_log(lines: list[str]) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    path = LOGS_DIR / "scan_tech_mukul.log"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ── Main ───────────────────────────────────────────────────────────────────────

def run_scan(dry_run: bool = False, max_posts: int = 0) -> dict:
    log("SCAN_STARTED", source=SOURCE_NAME, url=TECH_MUKUL_URL)

    report_lines: list[str] = [
        "DeadZone Auto Stable Builder — Scan Report",
        "=" * 50,
        f"Source:     {SOURCE_NAME}",
        f"URL:        {TECH_MUKUL_URL}",
        f"Scanned at: {_now_iso()}",
        "",
    ]
    detail_log: list[str] = []

    # Load supported devices
    supported = load_supported_codenames()
    if not supported:
        log("SCAN_ERROR", "No supported devices found in bin/devices/")
        sys.exit(1)

    # Fetch page
    try:
        html = fetch_page()
    except Exception as exc:
        log("SCAN_ERROR", f"Could not fetch TECH_MUKUL: {exc}")
        sys.exit(1)

    # Parse messages
    messages = parse_messages(html)
    if max_posts and max_posts > 0:
        messages = messages[-max_posts:]  # most recent N

    total   = len(messages)
    skipped = 0
    found   = 0
    added   = 0
    dup     = 0
    already_built_count = 0

    report_lines.append(f"Posts parsed:  {total}")

    # Load current queue
    queue = load_queue()

    # Process each post
    for post in reversed(messages):  # oldest first
        post_url = post["post_url"]
        text     = post["text"]
        detail_log.append(f"\n--- {post_url} ---")
        detail_log.append(text[:300])

        # Check already built
        version  = extract_version(text)
        region   = detect_region(text, version or "")
        codename = extract_codename(text, post["links"], supported)

        if version and region and codename:
            rom_urls = extract_download_urls(post["links"])
            rom_url  = rom_urls[0] if rom_urls else ""
            if is_duplicate(codename, version, region, rom_url):
                log("SCAN_SKIPPED", post=post_url, reason="already_built")
                detail_log.append("  SKIP: already_built")
                already_built_count += 1
                skipped += 1
                continue

        # Classify
        reason, _ = classify_post(post, supported)
        if reason:
            log("SCAN_SKIPPED", post=post_url, reason=reason)
            detail_log.append(f"  SKIP: {reason}")
            skipped += 1
            continue

        # Build queue item
        item = build_queue_item(post, supported)
        if not item:
            log("SCAN_SKIPPED", post=post_url, reason="parse_error")
            detail_log.append("  SKIP: parse_error")
            skipped += 1
            continue

        found += 1
        log("SCAN_FOUND",
            codename=item["codename"],
            version=item["version"],
            region=item["region"],
            rom_type=item["rom_type"])
        detail_log.append(
            f"  FOUND: {item['codename']} {item['version']} {item['region']} {item['rom_type']}"
        )

        # Dedupe against existing queue
        if _queue_item_exists(queue, item):
            log("QUEUE_DUPLICATE_SKIPPED", id=item["id"])
            detail_log.append("  QUEUE_DUP: already queued")
            dup += 1
            continue

        if not dry_run:
            queue.append(item)
        log("QUEUE_ADDED", id=item["id"])
        detail_log.append(f"  QUEUED: {item['id']}")
        added += 1

    if not dry_run:
        save_queue(queue)

    # Write reports
    report_lines += [
        "",
        f"Valid ROMs found:    {found}",
        f"Skipped (total):     {skipped}",
        f"  already_built:     {already_built_count}",
        f"  other reasons:     {skipped - already_built_count}",
        f"Added to queue:      {added}",
        f"Duplicate queue:     {dup}",
        f"Queue total (now):   {len(queue)}",
        f"Dry run:             {dry_run}",
    ]
    _write_report(report_lines)
    _write_log(detail_log)

    if found == 0:
        log("QUEUE_EMPTY", msg="No new valid OS3 CN/Global Stable ROMs found")

    return {
        "total_scanned": total,
        "found":         found,
        "added":         added,
        "skipped":       skipped,
        "queue_size":    len(queue),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan TECH_MUKUL for new HyperOS 3 ROMs")
    parser.add_argument("--dry-run",   action="store_true", help="Do not modify queue")
    parser.add_argument("--max-posts", type=int, default=0, help="Limit number of posts to process")
    args = parser.parse_args()

    result = run_scan(dry_run=args.dry_run, max_posts=args.max_posts)

    print(
        f"\n[SCAN] Done. scanned={result['total_scanned']} "
        f"found={result['found']} added={result['added']} "
        f"skipped={result['skipped']} queue={result['queue_size']}"
    )


if __name__ == "__main__":
    main()
