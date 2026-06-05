#!/usr/bin/env python3
"""Android image type detection and safe sparse/raw merge helper.

Checks the first 4 bytes (Android sparse magic: 3A FF 26 ED) to decide
whether to run simg2img or cat image chunks together.

CLI:
  python3 image_utils.py detect <image>
  python3 image_utils.py merge --dst <output> [--simg2img <bin>] chunk1 [chunk2 ...]
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

# Android sparse image magic: little-endian 0xED26FF3A
SPARSE_MAGIC = bytes([0x3A, 0xFF, 0x26, 0xED])


def detect_image_type(path: "Path | str") -> dict:
    """Return {'type': 'SPARSE'|'RAW', 'size': int, 'magic': str}."""
    p = Path(path)
    if not p.is_file():
        return {"type": "RAW", "size": 0, "magic": "????????"}
    size = p.stat().st_size
    if size < 4:
        return {"type": "RAW", "size": size, "magic": "??"}
    with p.open("rb") as fh:
        header = fh.read(4)
    magic_hex = header.hex()
    img_type = "SPARSE" if header == SPARSE_MAGIC else "RAW"
    return {"type": img_type, "size": size, "magic": magic_hex}


def log_image(name: str, info: dict) -> None:
    print(f"[IMAGE] {name}: {info['type']}, size={info['size']}, magic={info['magic']}")


def safe_simg2img(
    src_files: "list[str]",
    dst: str,
    simg2img_bin: str = "simg2img",
) -> bool:
    """Merge sparse or raw image chunks into a single output file.

    SPARSE chunks → runs simg2img (tool handles sparse format natively)
    RAW chunks    → concatenates directly without involving simg2img

    This prevents 'Invalid sparse file format at header magic' when
    the input images are raw rather than Android sparse format.
    """
    dst_path = Path(dst)
    srcs = sorted([Path(s) for s in src_files], key=lambda p: p.name)
    if not srcs:
        print("[IMAGE] safe_simg2img: no source files provided", file=sys.stderr)
        return False

    first_info = detect_image_type(srcs[0])
    log_image(srcs[0].name, first_info)
    for extra in srcs[1:]:
        log_image(extra.name, detect_image_type(extra))

    if first_info["type"] == "SPARSE":
        print(f"[IMAGE] Detected SPARSE (magic={first_info['magic']}) -- running simg2img on {len(srcs)} chunk(s)")
        cmd = [simg2img_bin] + [str(s) for s in srcs] + [str(dst_path)]
        result = subprocess.run(cmd)
        if result.returncode != 0:
            print(
                f"[IMAGE] simg2img FAILED (rc={result.returncode})\n"
                f"[IMAGE] Command: {' '.join(cmd)}",
                file=sys.stderr,
            )
            return False
        print(f"[IMAGE] simg2img OK -> {dst_path}  ({dst_path.stat().st_size:,} bytes)")
    else:
        print(
            f"[IMAGE] Detected RAW (magic={first_info['magic']}) -- "
            f"concatenating {len(srcs)} chunk(s) directly (simg2img skipped)"
        )
        with dst_path.open("wb") as out:
            for src in srcs:
                with src.open("rb") as inp:
                    shutil.copyfileobj(inp, out)
        print(f"[IMAGE] concat OK -> {dst_path}  ({dst_path.stat().st_size:,} bytes)")

    return True


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    dp = sub.add_parser("detect", help="Detect and log image type")
    dp.add_argument("image", help="Image file path")

    mp = sub.add_parser("merge", help="Safely merge sparse or raw image chunks")
    mp.add_argument("chunks", nargs="+", help="Input chunk file(s)")
    mp.add_argument("--dst", required=True, help="Output merged image path")
    mp.add_argument("--simg2img", default="simg2img", help="Path to simg2img binary")

    args = ap.parse_args()

    if args.cmd == "detect":
        info = detect_image_type(args.image)
        log_image(Path(args.image).name, info)
    elif args.cmd == "merge":
        ok = safe_simg2img(args.chunks, args.dst, args.simg2img)
        sys.exit(0 if ok else 1)
