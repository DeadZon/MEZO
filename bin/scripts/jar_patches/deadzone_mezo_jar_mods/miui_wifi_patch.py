#!/usr/bin/env python3
"""DeadZone MEZO miui-wifi-service.jar patch module.

Adds registerCountryCodeChangedObserver() to MiuiWifiService and the
companion MiuiWifiService$7 ContentObserver class.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..common.smali_utils import (
    find_smali_file, read_smali, write_smali,
    already_patched, get_method_bounds, add_smali_class,
)

_ASSETS = Path(__file__).parent.parent / "assets" / "miui_wifi"

_NEW_METHOD = '''
.method private registerCountryCodeChangedObserver()V
    .registers 5

    new-instance v0, Lcom/android/server/wifi/MiuiWifiService$7;

    new-instance v1, Landroid/os/Handler;

    invoke-direct {v1}, Landroid/os/Handler;-><init>()V

    invoke-direct {v0, p0, v1}, Lcom/android/server/wifi/MiuiWifiService$7;-><init>(Lcom/android/server/wifi/MiuiWifiService;Landroid/os/Handler;)V

    iget-object v1, p0, Lcom/android/server/wifi/MiuiWifiService;->mContext:Landroid/content/Context;

    invoke-virtual {v1}, Landroid/content/Context;->getContentResolver()Landroid/content/ContentResolver;

    move-result-object v1

    const-string v2, "wifi_country_code"

    invoke-static {v2}, Landroid/provider/Settings$Global;->getUriFor(Ljava/lang/String;)Landroid/net/Uri;

    move-result-object v2

    const/4 v3, 0x0

    invoke-virtual {v1, v2, v3, v0}, Landroid/content/ContentResolver;->registerContentObserver(Landroid/net/Uri;ZLandroid/database/ContentObserver;)V

    invoke-virtual {v0, v3}, Landroid/database/ContentObserver;->onChange(Z)V

    return-void
.end method
'''

_CALL_LINE = "    invoke-direct {p0}, Lcom/android/server/wifi/MiuiWifiService;->registerCountryCodeChangedObserver()V\n"


@dataclass
class ModResult:
    name:    str
    applied: bool  = False
    skipped: bool  = False
    error:   str   = ""
    note:    str   = ""


def patch_register_country_code_observer(workspace: Path, results: list) -> None:
    r = ModResult(name="MiuiWifiService → registerCountryCodeChangedObserver")
    f = find_smali_file(workspace, "Lcom/android/server/wifi/MiuiWifiService;")
    if not f:
        r.skipped = True
        r.note = "MiuiWifiService.smali not found"
        results.append(r)
        return
    text = read_smali(f)
    marker = "registerCountryCodeChangedObserver"
    if already_patched(text, marker):
        r.applied = True
        r.note = "already patched"
        results.append(r)
        return

    # Add the new method before .end class
    end_class = text.rfind(".end class")
    if end_class == -1:
        r.skipped = True
        r.note = ".end class not found"
        results.append(r)
        return
    new_text = text[:end_class] + _NEW_METHOD + "\n" + text[end_class:]

    # Add call in the init/start method near RssiDetailSceneReporter.makeInstance
    anchor = "Lcom/android/server/wifi/RssiDetailSceneReporter;->makeInstance(Landroid/content/Context;)V"
    if anchor in new_text:
        lines = new_text.split("\n")
        result_lines: list[str] = []
        for line in lines:
            result_lines.append(line)
            if anchor in line:
                result_lines.append("")
                result_lines.append(_CALL_LINE.rstrip("\n"))
        new_text = "\n".join(result_lines)

    write_smali(f, new_text)
    r.applied = True
    results.append(r)


def add_miui_wifi_service_7(workspace: Path, results: list) -> None:
    r = ModResult(name="Add MiuiWifiService$7 class")
    class_path = "com/android/server/wifi/MiuiWifiService$7"
    existing = find_smali_file(workspace, "L" + class_path + ";")
    if existing:
        r.applied = True
        r.note = "already present"
        results.append(r)
        return
    asset = _ASSETS / "com/android/server/wifi/MiuiWifiService$7.smali"
    if not asset.is_file():
        r.error = f"asset not found: {asset}"
        results.append(r)
        return
    content = asset.read_text(encoding="utf-8", errors="replace")
    try:
        add_smali_class(workspace, class_path, content)
        r.applied = True
    except Exception as exc:
        r.error = str(exc)
    results.append(r)
