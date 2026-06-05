#!/usr/bin/env python3
"""DeadZone MEZO services.jar patch module."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..common.smali_utils import (
    find_smali_file, read_smali, write_smali,
    already_patched, insert_after_registers, get_method_bounds,
    remove_invoke_block, delete_method, add_smali_class,
    get_registers_val, set_registers_val, insert_after_pattern,
    patch_method_decl_flag,
)


@dataclass
class ModResult:
    name:    str
    applied: bool  = False
    skipped: bool  = False
    error:   str   = ""
    note:    str   = ""


# ── 1. AccountManagerService.checkPackageSignature → isTrustedAccountSignature

def patch_account_manager_signature(workspace: Path, results: list) -> None:
    r = ModResult(name="AccountManagerService.checkPackageSignature → isTrustedAccountSignature")
    f = find_smali_file(workspace, "Lcom/android/server/accounts/AccountManagerService;")
    if not f:
        r.skipped = True
        r.note = "AccountManagerService.smali not found"
        results.append(r)
        return
    text = read_smali(f)
    marker = "isTrustedAccountSignature"
    if already_patched(text, marker):
        r.applied = True
        r.note = "already patched"
        results.append(r)
        return

    # Pattern: signaturesMatchExactly → compareSignatures (checkPackageSignature method)
    # Find: invoke-virtual {v0, p0}, ...;->signaturesMatchExactly(...
    #       move-result v0
    #       if-eqz v0, :cond_X
    old_pattern = [
        "invoke-virtual {v7, v0}, Landroid/content/pm/SigningDetails;->checkCapability(Landroid/content/pm/SigningDetails;I)Z",
    ]
    # Actually the key change is: if-eqz v7, :cond_X → if-nez v7, :cond_X
    # and inserting an isTrustedAccountSignature block
    # Find the checkPackageSignature method
    bounds = get_method_bounds(text, "checkPackageSignature(")
    if bounds is None:
        r.skipped = True
        r.note = "checkPackageSignature method not found"
        results.append(r)
        return

    method_text = text[bounds[0]:bounds[1]]

    # The EU change adds isTrustedAccountSignature check:
    # Original: if-eqz v7, :cond_X → const/4 v0, 0x1 → return v0 → :cond_X goto
    # EU: if-nez v7, :cond_X → invoke isTrustedAccountSignature → if-eqz → :cond_X+1
    # We look for the pattern "if-eqz v7" near a signature check and inject the trust check
    # Use pattern-based: find "->checkCapability" and inject trust check before cond label

    # Simpler targeted pattern: find the getSigningDetails invoke + move-result pair
    # and insert the isTrustedAccountSignature block
    trust_code = (
        "\n"
        "    invoke-static {}, Lcom/android/server/accounts/AccountManagerServiceStub;->getInstance()Lcom/android/server/accounts/AccountManagerServiceStub;\n"
        "\n"
        "    move-result-object v7\n"
        "\n"
        "    iget-object v8, p0, Lcom/android/server/accounts/AccountManagerService;->mPackageManager:Landroid/content/pm/PackageManager;\n"
        "\n"
        "    iget v9, v6, Landroid/content/pm/RegisteredServicesCache$ServiceInfo;->uid:I\n"
        "\n"
        "    invoke-virtual {v7, v8, p1, v9, p2}, Lcom/android/server/accounts/AccountManagerServiceStub;->isTrustedAccountSignature(Landroid/content/pm/PackageManager;Ljava/lang/String;II)Z\n"
        "\n"
        "    move-result v7\n"
        "\n"
        "    if-nez v7, :cond_trusted\n"
        "\n"
        "    goto :goto_sig_check\n"
        "\n"
        "    :cond_trusted\n"
        "    const/4 v0, 0x1\n"
        "\n"
        "    return v0\n"
        "\n"
        "    :goto_sig_check\n"
    )

    # Find location: after "getSigningDetails" invoke in checkPackageSignature
    signing_details_pattern = "getSigningDetails()Landroid/content/pm/SigningDetails;"
    if signing_details_pattern not in method_text:
        r.skipped = True
        r.note = "getSigningDetails() call not found in checkPackageSignature"
        results.append(r)
        return

    # Find the line index of getSigningDetails call in method_text
    lines = method_text.split("\n")
    new_lines: list[str] = []
    injected = False
    for i, line in enumerate(lines):
        new_lines.append(line)
        if not injected and signing_details_pattern in line:
            # Insert trust check block after the subsequent move-result + if-eqz block
            # We do this by inserting after the 3rd next non-empty line
            count = 0
            for j in range(i + 1, min(i + 8, len(lines))):
                if lines[j].strip():
                    count += 1
                    if count == 3:
                        # Insert after lines[j]
                        new_lines += lines[i + 1:j + 1]
                        for tline in trust_code.split("\n"):
                            new_lines.append(tline)
                        # Continue from j+1
                        new_lines += lines[j + 1:]
                        injected = True
                        break
            if injected:
                break

    if not injected:
        r.skipped = True
        r.note = "Could not locate insertion point in checkPackageSignature"
        results.append(r)
        return

    new_method = "\n".join(new_lines)
    write_smali(f, text[:bounds[0]] + new_method + text[bounds[1]:])
    r.applied = True
    results.append(r)


# ── 2. ActivityManagerService → remove syncFontForWebView calls ───────────────

def patch_ams_remove_sync_font(workspace: Path, results: list) -> None:
    r = ModResult(name="ActivityManagerService → remove syncFontForWebView calls")
    f = find_smali_file(workspace, "Lcom/android/server/am/ActivityManagerService;")
    if not f:
        r.skipped = True
        r.note = "ActivityManagerService.smali not found"
        results.append(r)
        return
    text = read_smali(f)
    marker = "syncFontForWebView"
    if not already_patched(text, marker):
        r.applied = True
        r.note = "syncFontForWebView already absent"
        results.append(r)
        return

    new_text = remove_invoke_block(text, "syncFontForWebView")
    write_smali(f, new_text)
    r.applied = True
    results.append(r)


# ── 3. BroadcastController → guard DEBUG_BROADCAST log ───────────────────────

def patch_broadcast_controller_debug(workspace: Path, results: list) -> None:
    r = ModResult(name="BroadcastController → guard DEBUG_BROADCAST log")
    f = find_smali_file(workspace, "Lcom/android/server/am/BroadcastController;")
    if not f:
        r.skipped = True
        r.note = "BroadcastController.smali not found"
        results.append(r)
        return
    text = read_smali(f)
    marker = "DEBUG_BROADCAST"
    if already_patched(text, "sget-boolean v0, Lcom/android/server/am/ActivityManagerDebugConfig;->DEBUG_BROADCAST:Z"):
        r.applied = True
        r.note = "already patched"
        results.append(r)
        return

    # Pattern: find "ActivityManager" tag string used in a Log call (in the target block)
    # EU adds DEBUG_BROADCAST guard before the log call
    # Look for: const-string v0, "ActivityManager" following a label like :cond_1d/:goto_10
    # Insert guard block before the const-string "ActivityManager" log tag line
    lines = text.split("\n")
    new_lines: list[str] = []
    label_found = False
    for i, line in enumerate(lines):
        # The EU change inserts the guard right before 'const-string v0, "ActivityManager"'
        # at a specific point after label :cond_1d/:goto_10
        if re.match(r'[ \t]*const-string\s+v0,\s+"ActivityManager"', line) and label_found:
            indent = re.match(r"([ \t]*)", line).group(1)
            label = None
            # Find next label following this
            for j in range(i + 1, min(i + 10, len(lines))):
                m = re.match(r"[ \t]*:(cond_\w+|goto_\w+)\s*$", lines[j])
                if m:
                    break
            new_lines += [
                f"{indent}sget-boolean v0, Lcom/android/server/am/ActivityManagerDebugConfig;->DEBUG_BROADCAST:Z",
                "",
                f"{indent}if-eqz v0, :cond_dz_debug_broadcast",
            ]
            label_found = False
        new_lines.append(line)
        if re.match(r"[ \t]*:(cond_1d|goto_10)\s*$", line):
            label_found = True
            # We'll need to also add the label target after the skipped block
    # Close the guard after the log block — find where to add :cond_dz_debug_broadcast
    # Simple approach: append the label after the first Log.d/e/w call following guard
    result_text = "\n".join(new_lines)
    # Add :cond_dz_debug_broadcast label after DEBUG_BROADCAST guard block
    # Find the guard we just inserted and add label after the Log call
    import re as _re
    result_text = _re.sub(
        r"(if-eqz v0, :cond_dz_debug_broadcast\n(?:[ \t]*\n)*[ \t]*const-string[^\n]*\n(?:.*?\n)*?[ \t]*invoke-static[^\n]*Log[^\n]*\n)",
        lambda m: m.group(0) + "\n    :cond_dz_debug_broadcast\n",
        result_text,
        count=1,
        flags=_re.DOTALL,
    )
    if result_text == "\n".join(new_lines):
        r.skipped = True
        r.note = "Could not locate DEBUG_BROADCAST insertion point"
        results.append(r)
        return
    write_smali(f, result_text)
    r.applied = True
    results.append(r)


# ── 4. PermissionManagerServiceImpl → isSignedWithPlatformKey gate ────────────

def patch_permission_mgr_platform_key(workspace: Path, results: list) -> None:
    r = ModResult(name="PermissionManagerServiceImpl → isSignedWithPlatformKey gate")
    f = find_smali_file(workspace, "Lcom/android/server/pm/permission/PermissionManagerServiceImpl;")
    if not f:
        r.skipped = True
        r.note = "PermissionManagerServiceImpl.smali not found"
        results.append(r)
        return
    text = read_smali(f)
    marker = "isSignedWithPlatformKey"
    if already_patched(text, marker):
        r.applied = True
        r.note = "already patched"
        results.append(r)
        return

    # The EU change inserts isSignedWithPlatformKey() check before the existing
    # if-nez v4, :cond_0 that follows the first grant check in the method.
    # Pattern: find "if-nez v4, :cond_0" preceded by a move-result v4 in a permission grant block
    # Insert: invoke-interface {p1}, ...->isSignedWithPlatformKey()Z
    #         move-result v4
    #         if-nez v4, :cond_0
    # BEFORE the existing: invoke-interface {p1}, ...->getSigningDetails()...
    platform_key_block = (
        "\n"
        "    invoke-interface {p1}, Lcom/android/server/pm/pkg/AndroidPackage;->isSignedWithPlatformKey()Z\n"
        "\n"
        "    move-result v4\n"
        "\n"
        "    if-nez v4, :cond_0\n"
        "\n"
    )
    # Anchor: the getSigningDetails() call in the grant permission method
    anchor = "->getSigningDetails()Landroid/content/pm/SigningDetails;"
    if anchor not in text:
        r.skipped = True
        r.note = f"anchor '{anchor}' not found"
        results.append(r)
        return

    # Find the position of anchor and insert platform_key_block before the line containing it
    lines = text.split("\n")
    new_lines: list[str] = []
    inserted = False
    for i, line in enumerate(lines):
        if not inserted and anchor in line:
            # Check previous line: should be invoke-interface with p1
            # Insert platform key check before this line
            for pk_line in platform_key_block.split("\n"):
                new_lines.append(pk_line)
            inserted = True
        new_lines.append(line)

    if not inserted:
        r.skipped = True
        r.note = "Could not find insertion point"
        results.append(r)
        return

    write_smali(f, "\n".join(new_lines))
    r.applied = True
    results.append(r)


# ── 5. StatusBarManagerService.reboot → int mode support ─────────────────────

def patch_statusbar_reboot_mode(workspace: Path, results: list) -> None:
    r = ModResult(name="StatusBarManagerService.reboot → int mode support")
    f = find_smali_file(workspace, "Lcom/android/server/statusbar/StatusBarManagerService;")
    if not f:
        r.skipped = True
        r.note = "StatusBarManagerService.smali not found"
        results.append(r)
        return
    text = read_smali(f)
    marker = '"recovery"'
    if already_patched(text, 'const-string v0, "recovery"\n\n    goto :goto_0'):
        r.applied = True
        r.note = "already patched"
        results.append(r)
        return

    # The EU change converts reboot(Z)V → reboot(I)V
    # Change method signature: .method public reboot(Z)V → .method public reboot(I)V
    new_text = text.replace(
        ".method public reboot(Z)V\n    .registers 7",
        ".method public reboot(I)V\n    .registers 7",
    )
    if new_text == text:
        r.skipped = True
        r.note = "reboot(Z)V method signature not found"
        results.append(r)
        return

    # Change: if-eqz p1, :cond_0 → const/4 v0, 0x1 \n if-ne p1, v0, :cond_0
    new_text = new_text.replace(
        "    if-eqz p1, :cond_0\n\n    const-string v0, \"safemode\"",
        "    const/4 v0, 0x1\n\n    if-ne p1, v0, :cond_0\n\n    const-string v0, \"safemode\"",
        1,
    )

    # Insert recovery/bootloader branches after :cond_0 / safemode block
    # Find "    :cond_0\n    const-string v0, \"userrequested\""
    recovery_block = (
        "\n    :cond_1\n"
        "    const/4 v0, 0x2\n\n"
        "    if-ne p1, v0, :cond_2\n\n"
        '    const-string v0, "recovery"\n\n'
        "    goto :goto_0\n\n"
        "    :cond_2\n"
        "    const/4 v0, 0x3\n\n"
        "    if-ne p1, v0, :cond_3\n\n"
        '    const-string v0, "bootloader"\n\n'
        "    goto :goto_0\n\n"
        "    :cond_3\n"
    )
    old_anchor = '    :cond_0\n    const-string v0, "userrequested"'
    new_anchor = f'    :cond_0{recovery_block}    const-string v0, "userrequested"'
    new_text = new_text.replace(old_anchor, new_anchor, 1)

    # Fix lambda constructor call: <init>(ZLjava/lang/String;) → <init>(Ljava/lang/String;)
    new_text = new_text.replace(
        "invoke-direct {v4, p1, v0}, Lcom/android/server/statusbar/StatusBarManagerService$$ExternalSyntheticLambda6;-><init>(ZLjava/lang/String;)V",
        "invoke-direct {v4, v0}, Lcom/android/server/statusbar/StatusBarManagerService$$ExternalSyntheticLambda6;-><init>(Ljava/lang/String;)V",
        1,
    )

    write_smali(f, new_text)
    r.applied = True
    results.append(r)


# ── 6. DisplayRotation$SettingsObserver → allow_all_rotations ────────────────

def patch_display_rotation_all_rotations(workspace: Path, results: list) -> None:
    r = ModResult(name="DisplayRotation$SettingsObserver → allow_all_rotations")
    f = find_smali_file(workspace, "Lcom/android/server/wm/DisplayRotation$SettingsObserver;")
    if not f:
        r.skipped = True
        r.note = "DisplayRotation$SettingsObserver.smali not found"
        results.append(r)
        return
    text = read_smali(f)
    marker = "allow_all_rotations"
    if already_patched(text, marker):
        r.applied = True
        r.note = "already patched"
        results.append(r)
        return

    # Insert after last registerContentObserver in the observer init block
    # Pattern: the last registerContentObserver call before iget-object
    anchor = "->registerContentObserver(Landroid/net/Uri;ZLandroid/database/ContentObserver;I)V"
    # Find the last occurrence before the iget-object that follows
    allow_block = (
        "\n\n"
        "    const-string v1, \"allow_all_rotations\"\n\n"
        "    invoke-static {v1}, Landroid/provider/Settings$System;->getUriFor(Ljava/lang/String;)Landroid/net/Uri;\n\n"
        "    move-result-object v1\n\n"
        "    invoke-virtual {v0, v1, v2, p0, v3}, Landroid/content/ContentResolver;->registerContentObserver(Landroid/net/Uri;ZLandroid/database/ContentObserver;I)V\n"
    )

    # Find last registerContentObserver, insert after it
    last_pos = text.rfind(anchor)
    if last_pos == -1:
        r.skipped = True
        r.note = "registerContentObserver not found"
        results.append(r)
        return
    # Move to end of that line
    line_end = text.find("\n", last_pos) + 1
    new_text = text[:line_end] + allow_block + text[line_end:]

    # Also add resetAllowAllRotations() call before return-void in onChange
    reset_block = (
        "\n"
        "    :cond_0\n"
        "    iget-object v0, p0, Lcom/android/server/wm/DisplayRotation$SettingsObserver;->this$0:Lcom/android/server/wm/DisplayRotation;\n\n"
        "    invoke-virtual {v0}, Lcom/android/server/wm/DisplayRotation;->resetAllowAllRotations()V\n\n"
    )
    # Insert before return-void in onChange method
    change_bounds = get_method_bounds(new_text, "onChange(Z)V")
    if change_bounds:
        method = new_text[change_bounds[0]:change_bounds[1]]
        if "resetAllowAllRotations" not in method:
            import re as _re
            method = _re.sub(
                r"([ \t]*return-void\s*\n)",
                reset_block + r"\1",
                method,
                count=1,
            )
            new_text = new_text[:change_bounds[0]] + method + new_text[change_bounds[1]:]

    write_smali(f, new_text)
    r.applied = True
    results.append(r)


# ── 7. PhoneWindowManagerStub → add isEnableCombinationPowerVolumeUpGlobalActions

def patch_phone_window_mgr_stub(workspace: Path, results: list) -> None:
    r = ModResult(name="PhoneWindowManagerStub → isEnableCombinationPowerVolumeUpGlobalActions")
    f = find_smali_file(workspace, "Lcom/android/server/policy/PhoneWindowManagerStub;")
    if not f:
        r.skipped = True
        r.note = "PhoneWindowManagerStub.smali not found"
        results.append(r)
        return
    text = read_smali(f)
    marker = "isEnableCombinationPowerVolumeUpGlobalActions"
    if already_patched(text, marker):
        r.applied = True
        r.note = "already patched"
        results.append(r)
        return

    new_method = (
        "\n.method public isEnableCombinationPowerVolumeUpGlobalActions()Z\n"
        "    .registers 2\n\n"
        "    const/4 v0, 0x0\n\n"
        "    return v0\n"
        ".end method\n"
    )

    # Insert after isEnableCombinationPowerVolumeDownScreenShot method
    anchor_sig = "isEnableCombinationPowerVolumeDownScreenShot()Z"
    bounds = get_method_bounds(text, anchor_sig)
    if bounds is None:
        # Try appending before .end class
        end_class = text.rfind(".end class")
        if end_class == -1:
            r.skipped = True
            r.note = "Could not find insertion point"
            results.append(r)
            return
        write_smali(f, text[:end_class] + new_method + text[end_class:])
    else:
        write_smali(f, text[:bounds[1]] + new_method + text[bounds[1]:])

    r.applied = True
    results.append(r)


# ── 8. AppsFilterImpl.canQueryPackage → compareSignatures ────────────────────

def patch_apps_filter_signatures(workspace: Path, results: list) -> None:
    r = ModResult(name="AppsFilterImpl.canQueryPackage → compareSignatures")
    f = find_smali_file(workspace, "Lcom/android/server/pm/AppsFilterImpl;")
    if not f:
        r.skipped = True
        r.note = "AppsFilterImpl.smali not found"
        results.append(r)
        return
    text = read_smali(f)
    old_call = "invoke-virtual {v0, p0}, Landroid/content/pm/SigningDetails;->signaturesMatchExactly(Landroid/content/pm/SigningDetails;)Z"
    new_call = "invoke-static {p0, v0}, Lcom/android/server/pm/PackageManagerServiceUtils;->compareSignatures(Landroid/content/pm/SigningDetails;Landroid/content/pm/SigningDetails;)I"
    marker = "compareSignatures(Landroid/content/pm/SigningDetails"
    if already_patched(text, marker):
        r.applied = True
        r.note = "already patched"
        results.append(r)
        return
    if old_call not in text:
        r.skipped = True
        r.note = "signaturesMatchExactly call not found"
        results.append(r)
        return

    # Replace invoke + fix if-eqz → if-nez
    new_text = text.replace(old_call, new_call, 1)
    # After the replacement, the move-result + if-eqz becomes if-nez
    # Find the pattern: new_call \n move-result v0 \n if-eqz v0 → if-nez v0
    new_text = re.sub(
        r"(" + re.escape(new_call) + r"\n\n    move-result v0\n\n    )if-eqz v0",
        r"\1if-nez v0",
        new_text,
        count=1,
    )
    write_smali(f, new_text)
    r.applied = True
    results.append(r)
