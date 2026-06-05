#!/usr/bin/env python3
"""TECH_MUKUL Telegram scanner for DeadZone Auto Stable Builder.

Fetches recent posts from https://t.me/s/TECH_MUKUL, extracts ROM info,
and adds valid OS3 CN/Global Stable ROMs to output/queue/auto_build_queue.json.

Usage:
  python3 scripts/scan_tech_mukul.py [--dry-run] [--max-posts N] [--scan-pages N]

Outputs:
  output/queue/auto_build_queue.json   — updated queue
  output/reports/scan_report.txt       — scan summary
  output/logs/scan_tech_mukul.log      — detailed log
"""
from __future__ import annotations

import argparse
import os
import sys
import time
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

# Recovery pipeline gate: set RECOVERY_PIPELINE=true to queue recovery-only ROMs
RECOVERY_PIPELINE_ENABLED = os.environ.get("RECOVERY_PIPELINE", "true").lower() == "true"

# Stop paginating after this many new queue additions per run
_PAGINATION_STOP_THRESHOLD = 20

# Region suffix codes for logging (includes unsupported regions)
_SUFFIX_TO_REGION_NAME: dict[str, str] = {
    "CN": "China",
    "MI": "Global",
    "GL": "Global",
    "EU": "Europe",
    "IN": "India",
    "ID": "Indonesia",
    "TW": "Taiwan",
    "TR": "Turkey",
    "RU": "Russia",
}

_HASHTAG_REGION_MAP: dict[str, str] = {
    "taiwan": "Taiwan",
    "china": "China",
    "global": "Global",
    "india": "India",
    "indonesia": "Indonesia",
    "europe": "Europe",
    "turkey": "Turkey",
    "russia": "Russia",
    "eu": "Europe",
    "cn": "China",
    "eea": "Europe",
}


# ── Fetch ──────────────────────────────────────────────────────────────────────

def fetch_page(url: str = TECH_MUKUL_URL) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        log("SCAN_ERROR", f"fetch failed: {exc}")
        raise


def fetch_pages(num_pages: int = 5) -> list[dict]:
    """Fetch up to `num_pages` pages from TECH_MUKUL and return all parsed messages."""
    all_messages: list[dict] = []
    seen_ids: set[int] = set()
    url = TECH_MUKUL_URL

    for page_idx in range(num_pages):
        log("SCAN_FETCH_PAGE", page=page_idx + 1, url=url)
        try:
            html = fetch_page(url)
        except Exception as exc:
            log("SCAN_WARN", f"Page {page_idx + 1} fetch failed: {exc}")
            break

        msgs = parse_messages(html)
        if not msgs:
            log("SCAN_INFO", f"No messages on page {page_idx + 1} — stopping")
            break

        new_msgs = [m for m in msgs if m["post_num"] not in seen_ids]
        for m in new_msgs:
            seen_ids.add(m["post_num"])
        all_messages.extend(new_msgs)

        if not new_msgs:
            log("SCAN_INFO", "No new messages after dedup — stopping pagination")
            break

        oldest_id = min(m["post_num"] for m in msgs)
        url = f"{TECH_MUKUL_URL}?before={oldest_id}"

        if page_idx < num_pages - 1:
            time.sleep(1.5)

    return all_messages


# ── Parse ──────────────────────────────────────────────────────────────────────

def _strip_html(raw: str) -> str:
    """Remove HTML tags and decode entities."""
    text = re.sub(r'<br\s*/?>', '\n', raw, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = unescape(text)
    return re.sub(r' +', ' ', text).strip()


def _normalize_post_text(text: str) -> str:
    """Normalize hashtag spacing and strip Telegram formatting artifacts."""
    # Remove zero-width / formatting-only Unicode
    text = re.sub(r'[​-‏  ﻿­]', '', text)
    # Normalize "# Tag" → "#Tag" (space after hash)
    text = re.sub(r'#\s+(\w)', r'#\1', text)
    # Collapse multiple spaces
    return re.sub(r' {2,}', ' ', text).strip()


def parse_messages(html: str) -> list[dict]:
    """Extract post records from Telegram web HTML."""
    messages: list[dict] = []

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
        text = _normalize_post_text(_strip_html(text_raw))

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


# ── TECH_MUKUL-specific helpers ────────────────────────────────────────────────

def _extract_post_after_pipe(text: str) -> tuple[str | None, str | None]:
    """
    Parse TECH_MUKUL title format: '... Update Released | #Codename #Region'
    Returns (codename_hint, region_hint) both lowercased.

    Example: '#Xiaomi14T #HyperOS3 Update Released | #Degas #Taiwan'
             → ('degas', 'taiwan')
    """
    m = re.search(r'\|\s*#(\w+)(?:\s+#(\w+))?', text)
    if m:
        codename = m.group(1).lower()
        region   = m.group(2).lower() if m.group(2) else None
        return codename, region
    return None, None


def _get_raw_region(text: str, version: str = "") -> str | None:
    """
    Return region name for logging (including unsupported: Taiwan, Turkey, etc.).
    Does NOT apply allowed-regions filter.
    """
    # 1. Version suffix (most reliable)
    v_match = re.search(
        r'os3\.\d+\.\d+\.\d+\.([A-Z0-9]{4,})',
        text + " " + version,
        re.IGNORECASE,
    )
    if v_match:
        code = v_match.group(1).upper()
        if code.endswith("XM") and len(code) >= 4:
            rc = code[-4:-2]
            if rc in _SUFFIX_TO_REGION_NAME:
                return _SUFFIX_TO_REGION_NAME[rc]

    # 2. Hashtag after pipe: '| #Codename #Region'
    _, region_tag = _extract_post_after_pipe(text)
    if region_tag and region_tag in _HASHTAG_REGION_MAP:
        return _HASHTAG_REGION_MAP[region_tag]

    # 3. Explicit region hashtag anywhere in text
    for tag in re.findall(r'#(\w+)', text.lower()):
        if tag in _HASHTAG_REGION_MAP:
            r = _HASHTAG_REGION_MAP[tag]
            # Skip generic OS tags that overlap with region names (none currently)
            return r

    # 4. Text keyword fallback
    t = text.lower()
    for name, kw in [
        ("Taiwan", "taiwan"), ("China", "china"), ("Global", "global"),
        ("India", "india"), ("Indonesia", "indonesia"), ("Turkey", "turkey"),
        ("Russia", "russia"),
    ]:
        if kw in t:
            return name

    return None


def _resolve_codename(text: str, links: list[str], supported: set[str]) -> str | None:
    """
    Codename extraction with TECH_MUKUL-specific '| #Codename' support,
    falling back to generic extract_codename.
    """
    # 1. Explicit pipe-separated codename (most reliable for TECH_MUKUL)
    codename_hint, _ = _extract_post_after_pipe(text)
    if codename_hint and codename_hint in supported:
        return codename_hint

    # 2. Generic fallback (brackets, all hashtags, URL patterns, standalone word)
    return extract_codename(text, links, supported)


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
    Returns (reason_to_skip, None) if rejected, or (None, None) if accepted.

    Checks download links FIRST so short alert posts (no links) are not
    misclassified as missing_version or missing_codename.
    """
    text  = post["text"]
    links = post["links"]

    # --- Download links first: short alert posts have no links ---
    dl_urls = extract_download_urls(links)
    if not dl_urls:
        return "no_download_links", None

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
    codename = _resolve_codename(text, links, supported)
    if not codename:
        return "missing_codename", None
    if codename not in supported:
        return "unsupported_device", None

    return None, None  # accepted — caller will build item


def build_queue_item(post: dict, supported: set[str]) -> dict | None:
    """Return a queue item dict for a valid post, or None."""
    text  = post["text"]
    links = post["links"]

    version  = extract_version(text)
    region   = detect_region(text, version or "")
    codename = _resolve_codename(text, links, supported)

    if not all([version, region, codename]):
        return None

    dl_urls = extract_download_urls(links)
    if not dl_urls:
        return None

    # Prefer fastboot URL
    rom_type = None
    rom_url  = None
    for u in dl_urls:
        if "fastboot" in u.lower():
            rom_url  = u
            rom_type = "fastboot"
            break

    # Fall back to recovery only when pipeline is enabled
    if rom_type is None:
        if not RECOVERY_PIPELINE_ENABLED:
            log("SCAN_SKIPPED", reason="recovery_pipeline_disabled", post=post["post_url"])
            return None
        rom_url  = dl_urls[0]
        rom_type = "recovery"

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

def _write_report(summary_lines: list[str], post_details: list[dict]) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / "scan_report.txt"

    lines = list(summary_lines)

    if post_details:
        lines += ["", "─" * 50, "Post Details", "─" * 50]
        for d in post_details:
            lines.append(f"\nPOST: {d['post_url']}")
            if d.get("title"):
                lines.append(f"  Title:    {d['title'][:120]}")
            for field in ("codename", "region", "version", "android", "rom_type"):
                val = d.get(field)
                if val:
                    lines.append(f"  {field.capitalize():<10}{val}")
            if d.get("rom_url"):
                lines.append(f"  ROM URL:  {d['rom_url']}")
            status = d.get("status", "")
            reason = d.get("reason", "")
            if reason:
                lines.append(f"  Status:   SKIPPED reason={reason}")
            else:
                lines.append(f"  Status:   {status}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[SCAN] Report written to {path}")


def _write_log(lines: list[str]) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    path = LOGS_DIR / "scan_tech_mukul.log"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ── Main ───────────────────────────────────────────────────────────────────────

def run_scan(dry_run: bool = False, max_posts: int = 0, scan_pages: int = 5) -> dict:
    log("SCAN_STARTED", source=SOURCE_NAME, url=TECH_MUKUL_URL, pages=scan_pages)

    summary_lines: list[str] = [
        "DeadZone Auto Stable Builder — Scan Report",
        "=" * 50,
        f"Source:     {SOURCE_NAME}",
        f"URL:        {TECH_MUKUL_URL}",
        f"Scanned at: {_now_iso()}",
        f"Pages:      {scan_pages}",
        "",
    ]
    detail_log: list[str] = []
    post_details: list[dict] = []

    # Load supported devices
    supported = load_supported_codenames()
    if not supported:
        log("SCAN_ERROR", "No supported devices found in bin/devices/")
        sys.exit(1)

    # Fetch pages
    try:
        messages = fetch_pages(scan_pages)
    except Exception as exc:
        log("SCAN_ERROR", f"Could not fetch TECH_MUKUL: {exc}")
        sys.exit(1)

    if max_posts and max_posts > 0:
        messages = messages[-max_posts:]

    total   = len(messages)
    skipped = 0
    found   = 0
    added   = 0
    dup     = 0
    already_built_count = 0

    summary_lines.append(f"Posts parsed:  {total}")

    # Load current queue
    queue = load_queue()

    # Process each post (oldest first)
    for post in sorted(messages, key=lambda m: m["post_num"]):
        post_url = post["post_url"]
        text     = post["text"]
        detail_log.append(f"\n--- {post_url} ---")
        detail_log.append(text[:300])

        # Title line for report (first non-empty line)
        title_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")

        # Pre-parse for already-built check and report detail
        version  = extract_version(text)
        region   = detect_region(text, version or "")
        codename = _resolve_codename(text, post["links"], supported)
        raw_region = _get_raw_region(text, version or "")

        pdetail: dict = {
            "post_url": post_url,
            "title":    title_line,
            "codename": codename,
            "region":   raw_region or region,
            "version":  version,
            "android":  extract_android_version(text),
        }

        # Check already built
        if version and region and codename:
            rom_urls = extract_download_urls(post["links"])
            rom_url  = rom_urls[0] if rom_urls else ""
            if is_duplicate(codename, version, region, rom_url):
                log("SCAN_SKIPPED", post=post_url, reason="already_built")
                detail_log.append("  SKIP: already_built")
                pdetail["reason"] = "already_built"
                pdetail["status"] = "SKIPPED"
                post_details.append(pdetail)
                already_built_count += 1
                skipped += 1
                continue

        # Classify
        reason, _ = classify_post(post, supported)
        if reason:
            log_kwargs: dict = {"post": post_url, "reason": reason}
            if reason == "unsupported_region" and raw_region:
                log_kwargs["region"] = raw_region
            log("SCAN_SKIPPED", **log_kwargs)
            detail_log.append(f"  SKIP: {reason}")
            pdetail["reason"] = reason
            pdetail["status"] = "SKIPPED"
            post_details.append(pdetail)
            skipped += 1
            continue

        # Build queue item
        item = build_queue_item(post, supported)
        if not item:
            log("SCAN_SKIPPED", post=post_url, reason="parse_error")
            detail_log.append("  SKIP: parse_error")
            pdetail["reason"] = "parse_error"
            pdetail["status"] = "SKIPPED"
            post_details.append(pdetail)
            skipped += 1
            continue

        pdetail["rom_type"] = item["rom_type"]
        pdetail["rom_url"]  = item["rom_url"]
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
            pdetail["status"] = "DUPLICATE"
            post_details.append(pdetail)
            dup += 1
            continue

        if not dry_run:
            queue.append(item)
        log("QUEUE_ADDED", id=item["id"])
        detail_log.append(f"  QUEUED: {item['id']}")
        pdetail["status"] = "QUEUED"
        post_details.append(pdetail)
        added += 1

        # Early stop when enough items added
        if added >= _PAGINATION_STOP_THRESHOLD:
            log("SCAN_INFO", f"Reached {_PAGINATION_STOP_THRESHOLD} new queue items — stopping early")
            break

    if not dry_run:
        save_queue(queue)

    # Summary
    summary_lines += [
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
    _write_report(summary_lines, post_details)
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
    parser.add_argument("--dry-run",    action="store_true", help="Do not modify queue")
    parser.add_argument("--max-posts",  type=int, default=0, help="Limit total posts to process")
    parser.add_argument("--scan-pages", type=int, default=5, help="Number of pages to fetch (default 5)")
    args = parser.parse_args()

    result = run_scan(
        dry_run=args.dry_run,
        max_posts=args.max_posts,
        scan_pages=args.scan_pages,
    )

    print(
        f"\n[SCAN] Done. scanned={result['total_scanned']} "
        f"found={result['found']} added={result['added']} "
        f"skipped={result['skipped']} queue={result['queue_size']}"
    )


if __name__ == "__main__":
    main()
