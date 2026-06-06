#!/usr/bin/env python3
"""Queue pruning: revalidate every pending item and remove those that fail current rules.

Removes items that:
  - are not OS3 / Stable
  - have an unsupported version suffix (TWXM, RUXM, EUXM, TRXM, JPXM, …)
  - have a region/suffix mismatch (e.g. queued as Global but suffix says Taiwan)
  - reference an unsupported device codename
  - are missing a ROM URL

Items with status 'built' or 'building' are always preserved regardless of validation.

Usage:
  python3 scripts/prune_queue.py [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (
    load_queue, save_queue, load_supported_codenames,
    detect_os3, extract_version_suffix,
    VERSION_SUFFIX_REGION, VERSION_SUFFIX_NAMES,
    log, _now_iso,
)

# Only items in these statuses are candidates for removal.
# 'built' and 'building' are preserved unconditionally.
_PRUNE_STATUSES = {"queued", "failed", "skipped"}


# ── Validation ─────────────────────────────────────────────────────────────────

def validate_for_prune(item: dict, supported: set[str]) -> tuple[bool, str]:
    """
    Return (ok, reason).  reason is '' on success.

    Applies the same OS3 / Stable / suffix rules as build_next_stable.validate_item
    but does NOT check is_duplicate — that check is only appropriate at build time.
    """
    if item.get("style", "").lower() != "stable":
        return False, "not_stable"

    if not detect_os3(item.get("os_tag", "") + " " + item.get("version", "")):
        return False, "not_os3"

    region = item.get("region", "")
    if region not in ("China", "Global"):
        return False, "unsupported_region"

    version = item.get("version", "")
    if version:
        suffix = extract_version_suffix(version)
        if suffix is not None:
            allowed = VERSION_SUFFIX_REGION.get(suffix)
            if allowed is None:
                return False, "unsupported_version_suffix"
            if allowed != region:
                return False, "region_suffix_mismatch"

    codename = item.get("codename", "")
    if not codename or codename not in supported:
        return False, "unsupported_device"

    if not item.get("rom_url"):
        return False, "missing_rom_url"

    return True, ""


# ── Core prune logic ───────────────────────────────────────────────────────────

def prune_queue(
    dry_run: bool = False,
    supported: set[str] | None = None,
) -> dict:
    """
    Revalidate every pending queue item and remove invalid entries.

    Args:
        dry_run:   When True, log what would be removed but do not write the file.
        supported: Set of supported device codenames.  If None, loaded from disk.

    Returns:
        {"before": N, "after": N, "removed": N}
    """
    if supported is None:
        supported = load_supported_codenames()

    queue  = load_queue()
    before = len(queue)
    kept: list[dict] = []
    removed = 0

    for item in queue:
        status = item.get("status", "queued")

        # Always preserve terminal / in-progress items.
        if status not in _PRUNE_STATUSES:
            kept.append(item)
            continue

        ok, reason = validate_for_prune(item, supported)
        if ok:
            kept.append(item)
            continue

        # Build structured log kwargs
        item_id      = item.get("id", "?")
        log_kwargs: dict = {"id": item_id, "reason": reason}

        if reason == "unsupported_version_suffix":
            sfx = extract_version_suffix(item.get("version", ""))
            if sfx:
                log_kwargs["suffix"] = sfx + "XM"

        log("QUEUE_PRUNED", **log_kwargs)
        removed += 1

    after = len(kept)
    log("QUEUE_PRUNE_DONE", before=before, after=after, removed=removed)

    if not dry_run and removed > 0:
        save_queue(kept)

    return {"before": before, "after": after, "removed": removed}


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prune invalid items from the auto-build queue"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report what would be removed without modifying the queue"
    )
    args = parser.parse_args()

    result = prune_queue(dry_run=args.dry_run)
    print(
        f"\n[PRUNE] Done. "
        f"before={result['before']}  after={result['after']}  removed={result['removed']}"
    )


if __name__ == "__main__":
    main()
