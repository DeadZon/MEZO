#!/usr/bin/env python3
"""Check: .gitignore has required MTCR / reference folder exclusions."""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
CHECKS_FAILED: list[str] = []


def fail(msg: str) -> None:
    CHECKS_FAILED.append(msg)
    print(f"  FAIL: {msg}")


def ok(msg: str) -> None:
    print(f"  OK  : {msg}")


print("=== check_jar_gitignore ===")

gitignore = ROOT / ".gitignore"
if not gitignore.is_file():
    fail(".gitignore not found at repo root")
    print("FAILED")
    sys.exit(1)

text = gitignore.read_text(encoding="utf-8")

REQUIRED = [
    "*.mtcr",
    "MyMezo.zip",
    "_DeadZoneRefs/",
    "*_mtcr/",
    "bin/third_party/mymezo_mtcr/",
    "__pycache__/",
    "*.pyc",
    ".tmp_deadzone_refs/",
]

for entry in REQUIRED:
    if entry in text:
        ok(f".gitignore contains: {entry}")
    else:
        fail(f".gitignore missing: {entry}")

# No .mtcr files committed
for mtcr in ROOT.rglob("*.mtcr"):
    fail(f"MTCR file found in repo: {mtcr.relative_to(ROOT)}")

# No MyMezo.zip committed
for mz in ROOT.rglob("MyMezo.zip"):
    fail(f"MyMezo.zip found in repo: {mz.relative_to(ROOT)}")

# No .pyc files committed — __pycache__ is runtime-generated and gitignored
# (we verify the .gitignore rule is present above, not runtime state)

if not CHECKS_FAILED:
    ok("No MTCR/MyMezo artifacts in repo")

print()
if CHECKS_FAILED:
    print(f"FAILED ({len(CHECKS_FAILED)} checks)")
    sys.exit(1)
print("ALL PASSED")
sys.exit(0)
