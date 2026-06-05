#!/usr/bin/env python3
"""DeadZone MEZO miui-services.jar patch module.

Removes WMServiceConnection classes that are not present in EU ROMs.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..common.smali_utils import find_smali_file


@dataclass
class ModResult:
    name:    str
    applied: bool  = False
    skipped: bool  = False
    error:   str   = ""
    note:    str   = ""


_WM_CLASSES = [
    "com/miui/server/WMServiceConnection",
    "com/miui/server/WMServiceConnection$1",
    "com/miui/server/WMServiceConnection$2",
]


def remove_wm_service_connection(workspace: Path, results: list) -> None:
    r = ModResult(name="Remove com/miui/server/WMServiceConnection*")
    removed: list[str] = []
    skipped: list[str] = []

    for class_path in _WM_CLASSES:
        f = find_smali_file(workspace, "L" + class_path + ";")
        if not f:
            skipped.append(class_path.split("/")[-1])
            continue
        f.unlink()
        removed.append(class_path.split("/")[-1])

    if removed:
        r.applied = True
        r.note = f"removed: {', '.join(removed)}"
        if skipped:
            r.note += f"; not found: {', '.join(skipped)}"
    else:
        r.applied = True
        r.note = f"all already absent: {', '.join(skipped)}"
    results.append(r)
