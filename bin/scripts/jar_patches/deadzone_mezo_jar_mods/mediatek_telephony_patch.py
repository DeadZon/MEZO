#!/usr/bin/env python3
"""DeadZone MEZO mediatek-telephony-common.jar patch module.

Converts Miui IS_GLOBAL_BUILD checks to ro.boot.hwc != CN pattern.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..common.smali_utils import (
    find_smali_file, read_smali, write_smali,
    already_patched, replace_method_body,
)


@dataclass
class ModResult:
    name:    str
    applied: bool  = False
    skipped: bool  = False
    error:   str   = ""
    note:    str   = ""


# Canonical EU replacement body for isNeeded()Z using ro.boot.hwc check
_HWC_BODY = (
    "    .registers 2\n\n"
    '    const-string v0, "ro.boot.hwc"\n\n'
    "    invoke-static {v0}, Landroid/os/SystemProperties;->get(Ljava/lang/String;)Ljava/lang/String;\n\n"
    "    move-result-object v0\n\n"
    '    const-string v1, "CN"\n\n'
    "    invoke-virtual {v0, v1}, Ljava/lang/Object;->equals(Ljava/lang/Object;)Z\n\n"
    "    move-result v0\n\n"
    "    xor-int/lit8 v0, v0, 0x1\n\n"
    "    return v0\n"
)

_MARKER = "ro.boot.hwc"


def patch_bluetooth_is_needed(workspace: Path, results: list) -> None:
    r = ModResult(name="BluetoothAdapterCompatible.isNeeded → ro.boot.hwc check")
    f = find_smali_file(workspace, "Lcom/mediatek/internal/telephony/BluetoothAdapterCompatible;")
    if not f:
        r.skipped = True
        r.note = "BluetoothAdapterCompatible.smali not found"
        results.append(r)
        return
    text = read_smali(f)
    if already_patched(text, _MARKER):
        r.applied = True
        r.note = "already patched"
        results.append(r)
        return
    new_text = replace_method_body(text, "isNeeded()Z", _HWC_BODY)
    if new_text == text:
        r.skipped = True
        r.note = "isNeeded()Z method not found"
        results.append(r)
        return
    write_smali(f, new_text)
    r.applied = True
    results.append(r)


def patch_wifi_is_needed(workspace: Path, results: list) -> None:
    r = ModResult(name="WifiManagerCompatible.isNeeded → ro.boot.hwc check")
    f = find_smali_file(workspace, "Lcom/mediatek/internal/telephony/WifiManagerCompatible;")
    if not f:
        r.skipped = True
        r.note = "WifiManagerCompatible.smali not found"
        results.append(r)
        return
    text = read_smali(f)
    if already_patched(text, _MARKER):
        r.applied = True
        r.note = "already patched"
        results.append(r)
        return
    new_text = replace_method_body(text, "isNeeded()Z", _HWC_BODY)
    if new_text == text:
        r.skipped = True
        r.note = "isNeeded()Z method not found"
        results.append(r)
        return
    write_smali(f, new_text)
    r.applied = True
    results.append(r)
