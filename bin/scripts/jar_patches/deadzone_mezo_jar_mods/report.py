#!/usr/bin/env python3
"""Report writer for DeadZone MEZO JAR mods."""
from __future__ import annotations

import time
from pathlib import Path

from ..common.report_utils import section, bullet, write_report, ts


def write_jar_mods_report(run_data: dict, reports_dir: Path) -> None:
    """Write output/reports/jar_patches/deadzone_mezo_jar_mods_report.txt."""
    lines: list[str] = []

    lines.append("DeadZone MEZO JAR Mods Report")
    lines.append("=" * 60)
    lines.append(f"Generated : {ts()}")
    lines.append(f"Style     : {run_data.get('style', '?')}")
    lines.append(f"Codename  : {run_data.get('codename', '?')}")
    lines.append("")

    jar_results = run_data.get("jar_results", {})
    total_applied = 0
    total_skipped = 0
    total_failed  = 0

    for jar_name, jar_data in jar_results.items():
        lines.append(section(f"JAR: {jar_name}", width=56))
        lines.append(f"  Path    : {jar_data.get('path', 'not found')}")
        lines.append(f"  Found   : {'YES' if jar_data.get('found') else 'NO'}")
        lines.append(f"  Backup  : {jar_data.get('backup', '-')}")
        lines.append(f"  Rebuilt : {'YES' if jar_data.get('rebuilt') else 'NO'}")
        if jar_data.get("error"):
            lines.append(f"  Error   : {jar_data['error']}")
        lines.append("")

        mods = jar_data.get("mods", [])
        for mod in mods:
            if mod.get("error"):
                status = f"FAILED  ({mod['error']})"
                total_failed += 1
            elif mod.get("skipped"):
                status = f"SKIPPED ({mod.get('note', 'pattern not found')})"
                total_skipped += 1
            else:
                status = f"APPLIED{' — ' + mod['note'] if mod.get('note') else ''}"
                total_applied += 1
            lines.append(f"  [{status[:7]:7s}] {mod['name']}")

        if not mods:
            lines.append("  (no mods registered for this JAR)")
        lines.append("")

    lines.append(section("Summary", width=56))
    lines.append(f"  Applied : {total_applied}")
    lines.append(f"  Skipped : {total_skipped} (ROM may not need these patches)")
    lines.append(f"  Failed  : {total_failed}")
    lines.append("")

    out = reports_dir / "jar_patches" / "deadzone_mezo_jar_mods_report.txt"
    write_report(out, "\n".join(lines) + "\n")
    return out


def write_jar_error_report(message: str, reports_dir: Path) -> None:
    """Write output/reports/jar_patches/deadzone_mezo_jar_mods_error.txt."""
    out = reports_dir / "jar_patches" / "deadzone_mezo_jar_mods_error.txt"
    content = f"DeadZone MEZO JAR Mods — Error Report\n{'=' * 60}\n{ts()}\n\n{message}\n"
    write_report(out, content)
