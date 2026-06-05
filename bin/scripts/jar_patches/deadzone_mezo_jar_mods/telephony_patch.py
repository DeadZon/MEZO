#!/usr/bin/env python3
"""DeadZone MEZO telephony-common.jar patch module."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..common.smali_utils import (
    find_smali_file, read_smali, write_smali,
    already_patched, get_method_bounds, insert_after_pattern,
)


@dataclass
class ModResult:
    name:    str
    applied: bool  = False
    skipped: bool  = False
    error:   str   = ""
    note:    str   = ""


def patch_notification_channel_blockable(workspace: Path, results: list) -> None:
    r = ModResult(name="NotificationChannelController → setBlockable(true)")
    f = find_smali_file(workspace, "Lcom/android/internal/telephony/util/NotificationChannelController;")
    if not f:
        r.skipped = True
        r.note = "NotificationChannelController.smali not found"
        results.append(r)
        return
    text = read_smali(f)
    marker = "->setBlockable(Z)V"
    if already_patched(text, marker):
        r.applied = True
        r.note = "already patched"
        results.append(r)
        return

    # Pattern: after NotificationChannel;-><init>(...) insert setBlockable(true)
    # Find: invoke-direct {v0, v3, v1, v2}, Landroid/app/NotificationChannel;-><init>(...)V
    # Insert after that line:
    #   const/4 v1, 0x1
    #   invoke-virtual {v0, v1}, Landroid/app/NotificationChannel;->setBlockable(Z)V
    anchor = "Landroid/app/NotificationChannel;-><init>(Ljava/lang/String;Ljava/lang/CharSequence;I)V"
    if anchor not in text:
        r.skipped = True
        r.note = "NotificationChannel <init> call not found"
        results.append(r)
        return

    blockable_block = (
        "\n\n"
        "    const/4 v1, 0x1\n\n"
        "    invoke-virtual {v0, v1}, Landroid/app/NotificationChannel;->setBlockable(Z)V\n"
    )

    # Insert after each occurrence of the <init> call (voicemail channels)
    lines = text.split("\n")
    new_lines: list[str] = []
    for line in lines:
        new_lines.append(line)
        if anchor in line:
            for bl in blockable_block.split("\n"):
                new_lines.append(bl)
    new_text = "\n".join(new_lines)
    write_smali(f, new_text)
    r.applied = True
    results.append(r)
