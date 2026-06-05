#!/usr/bin/env python3
"""DeadZone Auto Stable Builder — build the next queued ROM.

Picks the first 'queued' item from output/queue/auto_build_queue.json,
runs the existing build pipeline (build.sh → packROM.sh → package_rom.py),
uploads the final ZIP to PixelDrain, and writes publish_payload.json.

Usage:
  python3 scripts/build_next_stable.py [--validate-only]

Required env:
  PIXELDRAIN_API_KEY

Optional env:
  DZ_REPO_ROOT   override repo root (defaults to script parent dir)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import hashlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (
    REPO_ROOT, QUEUE_FILE, STATE_FILE, REPORTS_DIR, LOGS_DIR,
    PUBLISH_PAYLOAD, PD_REPORT,
    load_supported_codenames, get_soc_for_codename, get_device_display_name,
    load_queue, save_queue, load_state, save_state,
    is_duplicate, mark_built, make_queue_id,
    detect_os3, detect_region, detect_stable,
    format_publish_date, format_hyperos_version, format_os_tag,
    _now_iso, log,
)

REPORT_FILE = REPORTS_DIR / "auto_stable_builder_report.txt"
BUILD_LOG   = LOGS_DIR / "build_next_stable.log"


# ── Validation ─────────────────────────────────────────────────────────────────

def validate_item(item: dict, supported: set[str]) -> tuple[bool, str]:
    """Return (ok, reason). reason is empty string on success."""
    if item.get("style", "").lower() != "stable":
        return False, "not_stable"
    if not detect_os3(item.get("os_tag", "") + " " + item.get("version", "")):
        return False, "not_os3"
    region = item.get("region", "")
    if region not in ("China", "Global"):
        return False, f"unsupported_region:{region}"
    codename = item.get("codename", "")
    if not codename or codename not in supported:
        return False, f"unsupported_device:{codename}"
    if not item.get("rom_url"):
        return False, "missing_rom_url"
    if is_duplicate(codename, item.get("version", ""), region, item.get("rom_url", "")):
        return False, "already_built"
    return True, ""


# ── Build pipeline ─────────────────────────────────────────────────────────────

def _run(cmd: list[str], env: dict, label: str) -> int:
    print(f"[BUILD] Running: {' '.join(cmd[:3])} …")
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        cmd,
        env=env,
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    # Tee output to log and stdout
    output = proc.stdout.decode("utf-8", errors="replace") if proc.stdout else ""
    for line in output.splitlines():
        print(line)
    with BUILD_LOG.open("a", encoding="utf-8") as fh:
        fh.write(f"\n=== {label} ===\n")
        fh.write(output)
    return proc.returncode


def run_build_pipeline(item: dict, env: dict) -> bool:
    rom_url = item["rom_url"]
    log("BUILD_STARTED",
        codename=item["codename"],
        version=item["version"],
        region=item["region"])

    # 1 — build.sh
    rc = _run(["sudo", "bash", "build.sh", rom_url], env, "build.sh")
    if rc != 0:
        log("BUILD_FAILED", reason="build_sh_failed", exit_code=rc)
        return False

    # 2 — packROM.sh
    rc = _run(["sudo", "bash", "packROM.sh"], env, "packROM.sh")
    if rc != 0:
        log("BUILD_FAILED", reason="packROM_sh_failed", exit_code=rc)
        return False

    # 3 — package_rom.py
    rc = _run(
        ["sudo", "-E", "python3", "bin/scripts/package_rom.py"],
        env, "package_rom.py"
    )
    if rc != 0:
        log("BUILD_FAILED", reason="package_rom_py_failed", exit_code=rc)
        return False

    log("BUILD_SUCCESS",
        codename=item["codename"],
        version=item["version"])
    return True


# ── PixelDrain upload ──────────────────────────────────────────────────────────

def run_pixeldrain_upload(env: dict) -> tuple[str, str, str]:
    """Return (url, zip_name, zip_size_str). url='' on failure."""
    zip_path_file = REPORTS_DIR / "final_zip_path.txt"
    if not zip_path_file.is_file():
        log("BUILD_FAILED", reason="final_zip_path_missing")
        return "", "", ""

    zip_path = Path(zip_path_file.read_text(encoding="utf-8").strip())
    if not zip_path.is_file():
        log("BUILD_FAILED", reason=f"zip_not_found:{zip_path}")
        return "", "", ""

    zip_name = zip_path.name
    size_bytes = zip_path.stat().st_size
    if size_bytes >= 1_073_741_824:
        zip_size = f"{size_bytes / 1_073_741_824:.1f} GB"
    else:
        zip_size = f"{size_bytes / 1_048_576:.1f} MB"

    api_key = env.get("PIXELDRAIN_API_KEY", "")
    if not api_key:
        log("BUILD_FAILED", reason="PIXELDRAIN_API_KEY_missing")
        return "", zip_name, zip_size

    rc = _run(
        ["sudo", "-E", "python3", "bin/scripts/pixeldrain_upload.py", str(zip_path)],
        env, "pixeldrain_upload.py"
    )
    if rc != 0:
        log("BUILD_FAILED", reason="pixeldrain_upload_failed")
        return "", zip_name, zip_size

    # Read report
    if PD_REPORT.is_file():
        try:
            pd = json.loads(PD_REPORT.read_text(encoding="utf-8"))
            url = pd.get("url", "")
            if url:
                log("PIXELDRAIN_UPLOADED", url=url)
                return url, zip_name, zip_size
        except Exception:
            pass

    log("BUILD_FAILED", reason="pixeldrain_url_missing_in_report")
    return "", zip_name, zip_size


# ── SHA256 ─────────────────────────────────────────────────────────────────────

def _sha256_of_zip() -> str:
    zip_path_file = REPORTS_DIR / "final_zip_path.txt"
    if not zip_path_file.is_file():
        return ""
    try:
        zip_path = Path(zip_path_file.read_text(encoding="utf-8").strip())
        if not zip_path.is_file():
            return ""
        h = hashlib.sha256()
        with zip_path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


# ── Publish payload ────────────────────────────────────────────────────────────

def write_publish_payload(
    item: dict,
    download_url: str,
    zip_name: str,
    zip_size: str,
    sha256: str = "",
) -> None:
    version   = item["version"]
    android   = item.get("android", "A16")
    os_tag    = item.get("os_tag") or format_os_tag(version)
    hyperos_v = item.get("hyperos_version") or format_hyperos_version(version)

    payload = {
        "publish":          True,
        "style":            "Stable",
        "source":           item.get("source", "TECH_MUKUL"),
        "source_post_url":  item.get("source_post_url", ""),
        "device_name":      item.get("device_name", item["codename"]),
        "codename":         item["codename"],
        "version":          version,
        "hyperos_version":  hyperos_v,
        "region":           item["region"],
        "android":          android,
        "android_tag":      f"Android{android.lstrip('A')}",
        "os_tag":           os_tag,
        "publish_date":     format_publish_date(),
        "download_url":     download_url,
        "changelog_url":    "https://t.me/xDeadZone/430",
        "screenshots_url":  "https://t.me/DeadZoneCloud/572",
        "discussion_url":   "https://t.me/DeadZoneDiscussion",
        "image":            "assets/telegram/stable_release.jpg",
        "zip_name":         zip_name,
        "zip_size":         zip_size,
        "sha256":           sha256,
    }

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    PUBLISH_PAYLOAD.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    log("PUBLISH_PAYLOAD_WRITTEN", path=str(PUBLISH_PAYLOAD))


# ── Report ─────────────────────────────────────────────────────────────────────

def _write_final_report(
    item: dict | None,
    build_ok: bool,
    download_url: str,
    queue_size: int,
    fail_reason: str = "",
) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    lines = [
        "DeadZone Auto Stable Builder — Build Report",
        "=" * 50,
        f"Run at:       {_now_iso()}",
        "",
    ]
    if item:
        lines += [
            f"Selected:     {item.get('codename')} {item.get('version')} {item.get('region')}",
            f"Source post:  {item.get('source_post_url', '')}",
            f"ROM URL:      {item.get('rom_url', '')}",
            f"ROM type:     {item.get('rom_type', '')}",
            f"SoC:          {item.get('soc', '')}",
            "",
            f"Build result: {'SUCCESS' if build_ok else 'FAILED'}",
        ]
        if not build_ok and fail_reason:
            lines.append(f"Fail reason:  {fail_reason}")
        if download_url:
            lines.append(f"PixelDrain:   {download_url}")
    else:
        lines.append(f"No item selected. reason={fail_reason}")
    lines += [
        "",
        f"Queue size:   {queue_size}",
    ]
    REPORT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ── Main ───────────────────────────────────────────────────────────────────────

def run_build(validate_only: bool = False) -> int:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    BUILD_LOG.parent.mkdir(parents=True, exist_ok=True)

    supported = load_supported_codenames()
    if not supported:
        log("BUILD_FAILED", reason="no_supported_devices")
        return 1

    queue = load_queue()
    if not queue:
        log("QUEUE_EMPTY")
        _write_final_report(None, False, "", 0, fail_reason="queue_empty")
        return 0

    # Find first valid queued item
    selected_item: dict | None = None
    for item in queue:
        if item.get("status") != "queued":
            continue
        ok, reason = validate_item(item, supported)
        if ok:
            selected_item = item
            break
        else:
            log("BUILD_SELECTED", skipped=item.get("id"), reason=reason)
            item["status"] = "skipped"

    if not selected_item:
        log("QUEUE_EMPTY", msg="No valid queued items found")
        save_queue(queue)
        _write_final_report(None, False, "", len(queue), fail_reason="no_valid_queue_item")
        return 0

    log("BUILD_SELECTED",
        codename=selected_item["codename"],
        version=selected_item["version"],
        region=selected_item["region"])

    if validate_only:
        print(f"[BUILD] --validate-only: would build {selected_item['id']}")
        return 0

    # Mark as building
    selected_item["status"] = "building"
    selected_item["build_started_at"] = _now_iso()
    save_queue(queue)

    # Prepare environment
    env = os.environ.copy()
    env["DZ_STYLE"]        = "Stable"
    env["DZ_STYLE_ID"]     = "stable"
    env["DZ_STYLE_NAME"]   = "DeadZone Stable"
    env["DZ_STYLE_TIER"]   = "Free"
    env["INPUT_URL"]       = selected_item["rom_url"]
    env["TG_SOC"]          = selected_item.get("soc", "snapdragon")
    # Disable live Telegram build dashboard in auto mode
    env["TELEGRAM_BOT_TOKEN"] = env.get("TELEGRAM_BOT_TOKEN", "")

    # Run build pipeline
    build_ok = run_build_pipeline(selected_item, env)

    if not build_ok:
        selected_item["status"] = "failed"
        selected_item["failed_at"] = _now_iso()
        save_queue(queue)
        _write_final_report(selected_item, False, "", len(queue), fail_reason="build_pipeline_failed")
        return 1

    # Upload to PixelDrain
    download_url, zip_name, zip_size = run_pixeldrain_upload(env)
    if not download_url:
        selected_item["status"] = "failed"
        selected_item["failed_at"] = _now_iso()
        save_queue(queue)
        _write_final_report(selected_item, False, "", len(queue), fail_reason="pixeldrain_upload_failed")
        return 1

    # Compute SHA256
    sha256 = _sha256_of_zip()

    # Write publish payload
    write_publish_payload(selected_item, download_url, zip_name, zip_size, sha256)

    # Mark item as built
    selected_item["status"] = "built"
    selected_item["built_at"] = _now_iso()
    selected_item["download_url"] = download_url
    save_queue(queue)

    # Update state (dedupe tracker)
    mark_built(selected_item)

    # Write final report
    _write_final_report(selected_item, True, download_url, len(queue))

    print(f"[BUILD] Complete. ROM ready at: {download_url}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the next queued Stable ROM")
    parser.add_argument(
        "--validate-only", action="store_true",
        help="Validate queue and print what would be built, without running build"
    )
    args = parser.parse_args()
    sys.exit(run_build(validate_only=args.validate_only))


if __name__ == "__main__":
    main()
