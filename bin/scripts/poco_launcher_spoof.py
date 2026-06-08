#!/usr/bin/env python3
"""DeadZone MEZO — POCO Launcher to MiuiHome Spoofing.

Scans vendor/ and odm/ prop files for ro.product.vendor.brand=POCO and
replaces ONLY that key's value with Redmi.  All other keys are untouched.

Usage:
  python3 bin/scripts/poco_launcher_spoof.py --work-dir <root> [--style lite]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

WORK_DIR    = Path(__file__).resolve().parent.parent.parent
REPORTS_DIR = WORK_DIR / "bin" / "output" / "reports"

_TARGET_KEY   = "ro.product.vendor.brand"
_TARGET_VALUE = "POCO"
_REPLACE_WITH = "Redmi"

# Prop files live under these top-level partition dirs relative to work_dir
_SCAN_DIRS = ("vendor", "odm")

# Additional base paths searched when direct partitions are absent
_EXTRA_BASES = ("build/baserom/images",)


# ── prop helpers ───────────────────────────────────────────────────────────────

def _parse_prop_line(line: str) -> tuple[str | None, str | None]:
    """Return (key, value) for a valid prop line, else (None, None)."""
    stripped = line.rstrip("\n\r")
    if stripped.startswith("#") or "=" not in stripped:
        return None, None
    key, _, value = stripped.partition("=")
    return key.strip(), value.strip()


def _replace_brand_in_file(prop_path: Path) -> dict:
    """Scan a single prop file.  Replace ro.product.vendor.brand if value==POCO.

    Returns an entry dict with keys: target_file, found, modified, status, detail.
    """
    entry: dict = {
        "target_file": str(prop_path),
        "found":       False,
        "modified":    False,
        "status":      "skipped",
        "detail":      "",
    }
    try:
        lines = prop_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    except OSError as exc:
        entry["status"] = "failed"
        entry["detail"] = str(exc)
        return entry

    new_lines: list[str] = []
    changed = False
    for line in lines:
        key, value = _parse_prop_line(line)
        if key == _TARGET_KEY:
            entry["found"] = True
            if value == _TARGET_VALUE:
                # Replace value; preserve any trailing newline character(s)
                trail = line[len(line.rstrip("\n\r")):]
                new_line = f"{_TARGET_KEY}={_REPLACE_WITH}{trail}"
                new_lines.append(new_line)
                changed = True
                continue
        new_lines.append(line)

    if changed:
        prop_path.write_text("".join(new_lines), encoding="utf-8")
        entry["modified"] = True
        entry["status"]   = "changed"
        entry["detail"]   = f"{_TARGET_KEY} POCO → Redmi"
    elif entry["found"]:
        entry["status"] = "skipped"
        entry["detail"] = f"{_TARGET_KEY} found but value is not POCO"
    else:
        entry["status"] = "skipped"
        entry["detail"] = f"{_TARGET_KEY} not present"

    return entry


# ── main spoof logic ───────────────────────────────────────────────────────────

def _candidate_partition_dirs(work_dir: Path) -> list[tuple[str, Path]]:
    """Return (partition_name, path) pairs covering direct, nested, and extra-base locations.

    For each base (work_dir, work_dir/build/baserom/images) and each partition
    (vendor, odm) yields:
      base/partition          — direct
      base/partition/partition — nested (HyperURBuild pattern)
    Plus odm/etc as a supplemental prop location.
    """
    seen: set[Path] = set()
    candidates: list[tuple[str, Path]] = []

    def _add(label: str, path: Path) -> None:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            candidates.append((label, path))

    for base_rel in ("",) + _EXTRA_BASES:
        base = work_dir / base_rel if base_rel else work_dir
        for part in _SCAN_DIRS:
            _add(part,                   base / part)            # direct
            _add(f"{part}/{part}",       base / part / part)     # nested
        # odm/etc — additional prop location inside odm
        _add("odm/etc", base / "odm" / "etc")

    return candidates


def run_poco_spoof(work_dir: Path) -> dict:
    """Scan vendor/ and odm/ (and build/baserom/images equivalents) for POCO brand."""
    results: list[dict] = []
    poco_detected = False

    for partition, part_dir in _candidate_partition_dirs(work_dir):
        if not part_dir.is_dir():
            results.append({
                "target_file": str(part_dir),
                "found":       False,
                "modified":    False,
                "status":      "skipped",
                "detail":      f"{partition}/ not found",
            })
            continue

        prop_files = sorted(part_dir.rglob("*.prop"))
        if not prop_files:
            results.append({
                "target_file": str(part_dir),
                "found":       False,
                "modified":    False,
                "status":      "skipped",
                "detail":      f"no *.prop files in {partition}/",
            })
            continue

        for pf in prop_files:
            entry = _replace_brand_in_file(pf)
            results.append(entry)
            if entry["found"] and entry["modified"]:
                poco_detected = True

    # If nothing was changed and none of the found entries had POCO value,
    # determine whether any file even contained the key
    any_found = any(r["found"] for r in results)

    overall_status = "changed" if poco_detected else ("skipped" if not any_found else "skipped")

    report: dict = {
        "mod":          "poco_launcher_to_miuihome_spoofing",
        "generated":    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "work_dir":     str(work_dir),
        "poco_rom":     poco_detected,
        "overall_status": overall_status,
        "totals": {
            "scanned":  sum(1 for r in results if r["status"] != "skipped" or r["found"]),
            "modified": sum(1 for r in results if r["modified"]),
            "skipped":  sum(1 for r in results if r["status"] == "skipped"),
            "failed":   sum(1 for r in results if r["status"] == "failed"),
        },
        "results": results,
    }
    return report


# ── report writers ─────────────────────────────────────────────────────────────

def _write_reports(report: dict, reports_dir: Path) -> None:
    reports_dir.mkdir(parents=True, exist_ok=True)

    json_path = reports_dir / "poco_launcher_spoof_report.json"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    txt_lines = [
        "DeadZone MEZO — POCO Launcher to MiuiHome Spoofing Report",
        "=" * 55,
        f"Generated : {report['generated']}",
        f"Work dir  : {report['work_dir']}",
        f"POCO ROM  : {'YES' if report['poco_rom'] else 'NO'}",
        f"Status    : {report['overall_status'].upper()}",
        "",
        "Totals:",
        f"  Scanned : {report['totals']['scanned']}",
        f"  Modified: {report['totals']['modified']}",
        f"  Skipped : {report['totals']['skipped']}",
        f"  Failed  : {report['totals']['failed']}",
        "",
        "Results:",
    ]
    for r in report["results"]:
        tag = {"changed": "[CHANGED]", "skipped": "[SKIP   ]", "failed": "[FAILED ]"}.get(r["status"], "[???    ]")
        txt_lines.append(f"  {tag} {Path(r['target_file']).name} — {r['detail']}")

    (reports_dir / "poco_launcher_spoof_report.txt").write_text(
        "\n".join(txt_lines) + "\n", encoding="utf-8"
    )
    print(f"[POCO_SPOOF] Reports written → {json_path.parent}")


# ── CLI ────────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="POCO Launcher to MiuiHome Spoofing")
    parser.add_argument("--work-dir", default=str(WORK_DIR), help="Project root directory")
    parser.add_argument("--style",    default="lite",         help="Active build style")
    args = parser.parse_args(argv)

    enabled = os.environ.get("ENABLE_POCO_MIUIHOME_SPOOFING", "true").lower()
    if enabled not in ("1", "true", "yes"):
        print("[POCO_SPOOF] ENABLE_POCO_MIUIHOME_SPOOFING=false — skipped")
        return 0

    work_dir = Path(args.work_dir).resolve()
    reports_dir = work_dir / "bin" / "output" / "reports"

    print(f"[POCO_SPOOF] Scanning vendor/ and odm/ in {work_dir} ...")
    report = run_poco_spoof(work_dir)

    if report["poco_rom"]:
        print(f"[POCO_SPOOF] POCO ROM detected — {_TARGET_KEY} replaced with Redmi")
    else:
        print("[POCO_SPOOF] Not a POCO ROM or key not present — no changes made")

    _write_reports(report, reports_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
