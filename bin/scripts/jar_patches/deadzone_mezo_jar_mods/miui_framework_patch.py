#!/usr/bin/env python3
"""DeadZone MEZO miui-framework.jar patch module.

Removes DRM/font classes and adds eu/xiaomi/util/* EU translation utilities.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..common.smali_utils import (
    find_smali_file, read_smali, write_smali,
    already_patched, add_smali_class,
)

# Assets directory relative to this file
_ASSETS = Path(__file__).parent.parent / "assets" / "miui_framework"

_REMOVE_CLASSES = [
    "miui/drm/DrmBroadcast",
    "miui/drm/ThemeReceiver",
    "miui/drm/ThemeReceiver$ValidateThemeTask",
    "miui/util/font/SymlinkUtils",
]

_ADD_CLASSES = [
    "eu/xiaomi/util/FileUtil",
    "eu/xiaomi/util/JSONTranslator",
    "eu/xiaomi/util/JSONTranslator$JSONState",
    "eu/xiaomi/util/JSONTranslator$SingletonHolder",
    "eu/xiaomi/util/JSONTranslator-IA",
    "eu/xiaomi/util/Translator",
    "eu/xiaomi/util/Translator$SingletonHolder",
    "eu/xiaomi/util/Translator$State",
    "eu/xiaomi/util/Translator-IA",
]


@dataclass
class ModResult:
    name:    str
    applied: bool  = False
    skipped: bool  = False
    error:   str   = ""
    note:    str   = ""


def _remove_class(workspace: Path, class_path: str, results: list) -> None:
    r = ModResult(name=f"Remove {class_path}")
    f = find_smali_file(workspace, "L" + class_path + ";")
    if not f:
        r.skipped = True
        r.note = "class not found in ROM"
        results.append(r)
        return
    f.unlink()
    r.applied = True
    results.append(r)


def remove_drm_broadcast(workspace: Path, results: list) -> None:
    _remove_class(workspace, "miui/drm/DrmBroadcast", results)


def remove_theme_receiver(workspace: Path, results: list) -> None:
    _remove_class(workspace, "miui/drm/ThemeReceiver", results)


def remove_theme_receiver_validate_task(workspace: Path, results: list) -> None:
    _remove_class(workspace, "miui/drm/ThemeReceiver$ValidateThemeTask", results)


def remove_symlink_utils(workspace: Path, results: list) -> None:
    _remove_class(workspace, "miui/util/font/SymlinkUtils", results)


def add_eu_xiaomi_util_classes(workspace: Path, results: list) -> None:
    r = ModResult(name="Add eu/xiaomi/util/* classes")
    added: list[str] = []
    skipped: list[str] = []
    errors: list[str] = []

    for class_path in _ADD_CLASSES:
        asset_file = _ASSETS / (class_path + ".smali")
        if not asset_file.is_file():
            errors.append(f"asset missing: {asset_file.name}")
            continue
        # Check if already present
        existing = find_smali_file(workspace, "L" + class_path + ";")
        if existing:
            skipped.append(class_path.split("/")[-1])
            continue
        content = asset_file.read_text(encoding="utf-8", errors="replace")
        try:
            add_smali_class(workspace, class_path, content)
            added.append(class_path.split("/")[-1])
        except Exception as exc:
            errors.append(f"{class_path}: {exc}")

    if errors:
        r.error = "; ".join(errors)
    elif added:
        r.applied = True
        r.note = f"added: {', '.join(added)}"
        if skipped:
            r.note += f"; already present: {', '.join(skipped)}"
    else:
        r.applied = True
        r.note = f"all already present: {', '.join(skipped)}"
    results.append(r)
