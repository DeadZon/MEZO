#!/usr/bin/env python3
"""
DeadZone MEZO Path Layout Report
Generates bin/output/reports/path_layout_report.{txt,json}

Reports the resolved locations of key directories and whether the
bin-centred layout is in effect (primary) or the legacy root-output
fallback is being used.

Usage:
  python3 bin/scripts/path_layout_report.py [--style STYLE]
  python3 bin/scripts/path_layout_report.py  # style defaults to 'stable'
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR   = Path(__file__).resolve().parent      # bin/scripts
BIN_DIR      = SCRIPT_DIR.parent                    # bin
REPO_ROOT    = BIN_DIR.parent                       # project root

# Primary output location (bin-centred)
OUTPUT_DIR   = BIN_DIR / "output"
REPORTS_DIR  = OUTPUT_DIR / "reports"

# Legacy fallback (root-level output/)
LEGACY_OUTPUT = REPO_ROOT / "output"


def _check(path: Path) -> str:
    if path.exists():
        return "exists"
    return "missing"


def build_report(style: str = "stable") -> dict:
    using_legacy = not OUTPUT_DIR.exists() and LEGACY_OUTPUT.exists()

    effective_output = LEGACY_OUTPUT if using_legacy else OUTPUT_DIR
    effective_reports = effective_output / "reports"

    styles_dir    = BIN_DIR / "modfile" / "Styles"
    style_dir_map = {
        "lite":   styles_dir / "Lite",
        "stable": styles_dir / "Stable",
        "legend": styles_dir / "Legend",
        "ninja":  styles_dir / "Ninja",
    }
    active_style_dir = style_dir_map.get(style.lower(), styles_dir / "Stable")

    return {
        "generated":            datetime.now(timezone.utc).isoformat(),
        "active_style":         style,
        "legacy_output_used":   using_legacy,
        "paths": {
            "repo_root":    {"path": str(REPO_ROOT),        "status": _check(REPO_ROOT)},
            "bin_dir":      {"path": str(BIN_DIR),          "status": _check(BIN_DIR)},
            "scripts_dir":  {"path": str(SCRIPT_DIR),       "status": _check(SCRIPT_DIR)},
            "output_dir":   {"path": str(effective_output),  "status": _check(effective_output)},
            "reports_dir":  {"path": str(effective_reports), "status": _check(effective_reports)},
            "style_dir":    {"path": str(active_style_dir),  "status": _check(active_style_dir)},
            "styles_root":  {"path": str(styles_dir),        "status": _check(styles_dir)},
        },
        "style_dirs": {
            name: {"path": str(d), "status": _check(d)}
            for name, d in style_dir_map.items()
        },
    }


def write_reports(report: dict) -> None:
    out_dir = Path(report["paths"]["reports_dir"]["path"])
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "path_layout_report.json"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    txt_path = out_dir / "path_layout_report.txt"
    lines = [
        "=" * 64,
        "DeadZone MEZO Path Layout Report",
        f"Generated         : {report['generated']}",
        f"Active style      : {report['active_style']}",
        f"Legacy output used: {report['legacy_output_used']}",
        "=" * 64,
        "",
        "Resolved Paths:",
    ]
    for key, info in report["paths"].items():
        lines.append(f"  {key:<16} [{info['status'].upper():<7}] {info['path']}")
    lines += [
        "",
        "Style Directories:",
    ]
    for name, info in report["style_dirs"].items():
        lines.append(f"  {name:<10} [{info['status'].upper():<7}] {info['path']}")
    lines += ["", "=" * 64, ""]
    txt_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"[PATH_LAYOUT] Report: {json_path}")
    print(f"[PATH_LAYOUT] Report: {txt_path}")


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="DeadZone MEZO Path Layout Report")
    parser.add_argument("--style", default=os.environ.get("DZ_STYLE_ID", "stable"),
                        help="Active style (lite/stable/legend/ninja)")
    args = parser.parse_args()

    report = build_report(args.style)
    write_reports(report)

    paths = report["paths"]
    print(f"[PATH_LAYOUT] repo_root   = {paths['repo_root']['path']}")
    print(f"[PATH_LAYOUT] bin_dir     = {paths['bin_dir']['path']}")
    print(f"[PATH_LAYOUT] output_dir  = {paths['output_dir']['path']}")
    print(f"[PATH_LAYOUT] style       = {report['active_style']}")
    if report["legacy_output_used"]:
        print("[PATH_LAYOUT] WARNING: using legacy root-level output/ as fallback")


if __name__ == "__main__":
    main()
