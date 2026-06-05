#!/usr/bin/env python3
"""Smali manipulation helpers for the DeadZone JAR patch engine.

All functions operate on smali text (str) or file paths. They are
pattern-based — no hardcoded line numbers, no blind class replacement.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Optional

# ── 1. find_smali_file ────────────────────────────────────────────────────────

def find_smali_file(workspace_dir: Path, class_desc: str) -> Optional[Path]:
    """Find a .smali file in workspace_dir by class descriptor or path fragment.

    Accepts either descriptor form  (Landroid/os/Build;)
    or path form (android/os/Build or android/os/Build.smali).
    Searches all smali* subdirectories produced by apktool.
    """
    # Normalise to path form without extension
    class_path = class_desc.lstrip("L").rstrip(";").replace(".", "/")
    if class_path.endswith(".smali"):
        class_path = class_path[:-6]
    target_name = class_path.split("/")[-1] + ".smali"
    target_path = class_path + ".smali"

    for smali_dir in sorted(workspace_dir.glob("smali*")):
        candidate = smali_dir / target_path
        if candidate.is_file():
            return candidate

    # Fallback: recursive name search (handles renamed/nested dirs)
    for smali_dir in sorted(workspace_dir.glob("smali*")):
        for f in smali_dir.rglob(target_name):
            if target_path.replace("/", str(Path("/"))[-1]) in str(f).replace("\\", "/"):
                return f
            # Accept any match with correct name as last resort
            return f
    return None


# ── 2. read_smali ─────────────────────────────────────────────────────────────

def read_smali(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


# ── 3. write_smali ────────────────────────────────────────────────────────────

def write_smali(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


# ── 4. get_method_bounds ──────────────────────────────────────────────────────

def get_method_bounds(text: str, method_sig: str) -> Optional[tuple[int, int]]:
    """Return (start, end) character offsets of a complete method block.

    method_sig is matched as a substring of the .method declaration line.
    Returns None if not found.
    """
    pattern = re.compile(
        r"(^[ \t]*\.method\b[^\n]*" + re.escape(method_sig) + r"[^\n]*\n"
        r".*?"
        r"^[ \t]*\.end method[ \t]*(?:\n|$))",
        re.MULTILINE | re.DOTALL,
    )
    m = pattern.search(text)
    if m:
        return m.start(), m.end()
    return None


# ── 5. get_method_text ────────────────────────────────────────────────────────

def get_method_text(text: str, method_sig: str) -> Optional[str]:
    """Return the full text of a method block (decl through .end method)."""
    bounds = get_method_bounds(text, method_sig)
    if bounds:
        return text[bounds[0]:bounds[1]]
    return None


# ── 6. get_registers_val ─────────────────────────────────────────────────────

def get_registers_val(method_text: str) -> Optional[int]:
    """Return integer from the first .registers N line in method_text."""
    m = re.search(r"\.registers\s+(\d+)", method_text)
    return int(m.group(1)) if m else None


# ── 7. set_registers_val ─────────────────────────────────────────────────────

def set_registers_val(method_text: str, new_count: int) -> str:
    """Replace the first .registers N directive with the new count."""
    return re.sub(
        r"(\.registers\s+)\d+",
        lambda m: m.group(1) + str(new_count),
        method_text,
        count=1,
    )


# ── 8. insert_after_registers ────────────────────────────────────────────────

def insert_after_registers(method_text: str, code: str) -> str:
    """Insert code immediately after the .registers line."""
    m = re.search(r"(\.registers\s+\d+[ \t]*\n)", method_text)
    if not m:
        return method_text
    pos = m.end()
    return method_text[:pos] + code + method_text[pos:]


# ── 9. insert_before_return_object ───────────────────────────────────────────

def insert_before_return_object(method_text: str, code: str) -> str:
    """Insert code before every return-object line in method_text."""
    lines = method_text.split("\n")
    result: list[str] = []
    for line in lines:
        if re.match(r"[ \t]*return-object\b", line):
            indent = re.match(r"([ \t]*)", line).group(1)
            for code_line in code.splitlines():
                result.append(indent + code_line.strip())
        result.append(line)
    return "\n".join(result)


# ── 10. find_pattern ─────────────────────────────────────────────────────────

def find_pattern(text: str, pattern_lines: list[str]) -> Optional[int]:
    """Find contiguous lines matching pattern_lines (stripped comparison).

    Returns character offset of the start of the match, or None.
    """
    lines = text.split("\n")
    stripped_pattern = [p.strip() for p in pattern_lines]
    n = len(stripped_pattern)
    for i in range(len(lines) - n + 1):
        if [lines[i + j].strip() for j in range(n)] == stripped_pattern:
            # compute char offset
            offset = sum(len(l) + 1 for l in lines[:i])
            # compute end offset (after last matched line)
            end_offset = offset + sum(len(lines[i + j]) + 1 for j in range(n))
            return offset, end_offset
    return None


# ── 11. insert_after_pattern ─────────────────────────────────────────────────

def insert_after_pattern(text: str, pattern_lines: list[str], code: str) -> str:
    """Insert code after a contiguous pattern match. Returns unchanged text on miss."""
    result = find_pattern(text, pattern_lines)
    if result is None:
        return text
    _, end_offset = result
    return text[:end_offset] + code + text[end_offset:]


# ── 12. replace_method_body ──────────────────────────────────────────────────

def replace_method_body(text: str, method_sig: str, new_body: str) -> str:
    """Replace the body of a method (between decl and .end method) with new_body.

    new_body should not include the .method / .end method lines.
    Returns unchanged text if method not found.
    """
    bounds = get_method_bounds(text, method_sig)
    if bounds is None:
        return text
    old_block = text[bounds[0]:bounds[1]]
    # Extract decl line
    decl_line = old_block.split("\n")[0]
    new_block = decl_line + "\n" + new_body.rstrip("\n") + "\n.end method\n"
    return text[:bounds[0]] + new_block + text[bounds[1]:]


# ── 13. delete_method ────────────────────────────────────────────────────────

def delete_method(text: str, method_sig: str) -> str:
    """Remove a complete method block from text. Returns unchanged if not found."""
    bounds = get_method_bounds(text, method_sig)
    if bounds is None:
        return text
    return text[:bounds[0]] + text[bounds[1]:]


# ── 14. already_patched ──────────────────────────────────────────────────────

def already_patched(text: str, marker: str) -> bool:
    """Return True if marker string is already present in text."""
    return marker in text


# ── 15. add_smali_class ──────────────────────────────────────────────────────

def add_smali_class(workspace_dir: Path, class_path: str, content: str) -> Path:
    """Write a new smali class into smali/ (first smali dir).

    class_path: e.g. "eu/xiaomi/util/FileUtil" (no extension)
    Returns the written file path.
    """
    smali_dirs = sorted(workspace_dir.glob("smali*"))
    target_dir = smali_dirs[0] if smali_dirs else workspace_dir / "smali"
    out = target_dir / (class_path + ".smali")
    out.parent.mkdir(parents=True, exist_ok=True)
    write_smali(out, content)
    return out


# ── Bonus: remove_invoke_block ───────────────────────────────────────────────

def remove_invoke_block(text: str, invoke_fragment: str) -> str:
    """Remove a 3-line invoke block: invoke-static + move-result-object + invoke-virtual.

    Finds any invoke line containing invoke_fragment and removes it plus the
    immediately following move-result-* line and the next invoke-virtual on that result.
    This handles the syncFontForWebView / similar removal patterns.
    """
    lines = text.split("\n")
    result: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if invoke_fragment in line and re.match(r"[ \t]*invoke-", line):
            # Collect the block: current invoke + optional move-result + optional invoke
            block_start = i
            block_end = i + 1
            if block_end < len(lines) and re.match(r"[ \t]*move-result", lines[block_end]):
                block_end += 1
            if block_end < len(lines) and re.match(r"[ \t]*invoke-", lines[block_end]):
                block_end += 1
            i = block_end
            continue
        result.append(line)
        i += 1
    return "\n".join(result)


# ── add_method_after ─────────────────────────────────────────────────────────

def add_method_after(text: str, anchor_sig: str, new_method: str) -> str:
    """Insert new_method text after the .end method of anchor_sig method.

    Returns unchanged text if anchor not found.
    """
    bounds = get_method_bounds(text, anchor_sig)
    if bounds is None:
        return text
    pos = bounds[1]
    separator = "\n" if not new_method.startswith("\n") else ""
    return text[:pos] + separator + new_method + text[pos:]


# ── patch_method_decl_flag ────────────────────────────────────────────────────

def patch_method_decl_flag(text: str, method_sig: str, old_flags: str, new_flags: str) -> str:
    """Replace flags in a .method declaration line.

    Finds the .method line containing method_sig and replaces old_flags with new_flags.
    """
    def replacer(m: re.Match) -> str:
        line = m.group(0)
        return line.replace(old_flags, new_flags, 1)

    pattern = re.compile(
        r"^[ \t]*\.method\b[^\n]*" + re.escape(method_sig) + r"[^\n]*$",
        re.MULTILINE,
    )
    new_text, count = pattern.subn(replacer, text)
    return new_text
