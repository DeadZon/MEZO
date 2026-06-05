#!/usr/bin/env python3
"""Report formatting utilities for the DeadZone JAR patch engine."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any


def ts() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())


def section(title: str, width: int = 60) -> str:
    return f"\n{'=' * width}\n{title}\n{'=' * width}\n"


def bullet(label: str, value: Any) -> str:
    return f"  {label:<35s} {value}\n"


def write_report(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def mod_status(applied: bool, skipped: bool = False, error: str = "") -> str:
    if error:
        return f"FAILED  ({error})"
    if skipped:
        return "SKIPPED (pattern not found — ROM may not need this patch)"
    if applied:
        return "APPLIED"
    return "NOT APPLIED"
