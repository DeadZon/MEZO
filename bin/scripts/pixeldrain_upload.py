#!/usr/bin/env python3
"""PixelDrain ROM upload for MEZO ROM builder.
Ported from DeadZon/DeadZone factory/core/uploader.py.

Usage:
  pixeldrain_upload.py <final_zip_path>

Required env var:
  PIXELDRAIN_API_KEY

Behaviour:
  - Uploads only the final ROM ZIP; refuses anything that is not a .zip file.
  - Retries up to 3 times with 25-second delays on failure.
  - On success: prints "PIXELDRAIN_URL=<url>" to stdout and exits 0.
  - On failure: prints error to stderr, exits 1.
  - Always writes output/reports/pixeldrain_upload_report.json.
"""
from __future__ import annotations

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

PIXELDRAIN_API_URL  = "https://pixeldrain.com/api/file"
PIXELDRAIN_PUBLIC_URL = "https://pixeldrain.com/u"
UPLOAD_ATTEMPTS     = 3
UPLOAD_RETRY_DELAY  = 25
REPORT_FILE         = Path("bin/output/reports/pixeldrain_upload_report.json")


def _api_key() -> str:
    return os.environ.get("PIXELDRAIN_API_KEY", "").strip()


def _put_file(zip_path: Path, api_key: str) -> tuple[str, str]:
    """HTTP PUT the file to PixelDrain. Returns (file_id, error_message)."""
    url = f"{PIXELDRAIN_API_URL}/{urllib.parse.quote(zip_path.name)}"
    with zip_path.open("rb") as fh:
        data = fh.read()
    req = urllib.request.Request(url, data=data, method="PUT")
    req.add_header("Content-Type", "application/octet-stream")
    token = base64.b64encode(f":{api_key}".encode("utf-8")).decode("ascii")
    req.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(req, timeout=3600) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            payload = json.loads(body)
            file_id = str(payload.get("id") or "").strip()
            if file_id:
                return file_id, ""
            return "", f"upload response missing 'id': {body[:200]}"
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return "", f"HTTP {exc.code}: {body[:200]}"
    except Exception as exc:
        return "", str(exc)


def _write_report(result: dict) -> None:
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    if len(sys.argv) < 2:
        print("[PIXELDRAIN] Usage: pixeldrain_upload.py <zip_path>", file=sys.stderr)
        sys.exit(1)

    zip_path = Path(sys.argv[1])

    result: dict = {
        "provider":       "PixelDrain",
        "requested":      True,
        "final_zip_path": str(zip_path),
        "status":         "failed",
        "url":            "",
        "file_id":        "",
        "failure_reason": "",
        "attempts":       0,
        "warnings":       [],
    }

    # Validate file exists
    if not zip_path.is_file():
        result["failure_reason"] = f"ZIP file not found: {zip_path}"
        print(f"[PIXELDRAIN] ERROR: {result['failure_reason']}", file=sys.stderr)
        _write_report(result)
        sys.exit(1)

    # Validate it is actually a ZIP
    if zip_path.suffix.lower() != ".zip":
        result["failure_reason"] = f"Refusing to upload non-ZIP artifact: {zip_path.name}"
        print(f"[PIXELDRAIN] ERROR: {result['failure_reason']}", file=sys.stderr)
        _write_report(result)
        sys.exit(1)

    # Require API key
    api_key = _api_key()
    if not api_key:
        result["failure_reason"] = (
            "PIXELDRAIN_API_KEY is required when upload is enabled but the secret is not set"
        )
        print(f"[PIXELDRAIN] ERROR: {result['failure_reason']}", file=sys.stderr)
        _write_report(result)
        sys.exit(1)

    size_mib = zip_path.stat().st_size / 1024 / 1024
    print(f"[PIXELDRAIN] Uploading {zip_path.name} ({size_mib:.1f} MiB) …")

    last_error = ""
    for attempt in range(1, UPLOAD_ATTEMPTS + 1):
        result["attempts"] = attempt
        print(f"[PIXELDRAIN] Attempt {attempt}/{UPLOAD_ATTEMPTS}")
        file_id, error = _put_file(zip_path, api_key)
        if file_id:
            result["status"]  = "uploaded"
            result["file_id"] = file_id
            result["url"]     = f"{PIXELDRAIN_PUBLIC_URL}/{file_id}"
            print(f"[PIXELDRAIN] Uploaded: {result['url']}")
            _write_report(result)
            # Emit URL on stdout so the workflow can capture it
            print(f"PIXELDRAIN_URL={result['url']}", flush=True)
            sys.exit(0)

        last_error = error or "unknown upload error"
        print(f"[PIXELDRAIN] Attempt {attempt} failed: {last_error}", file=sys.stderr)
        if attempt < UPLOAD_ATTEMPTS:
            print(f"[PIXELDRAIN] Retrying in {UPLOAD_RETRY_DELAY}s …")
            time.sleep(UPLOAD_RETRY_DELAY)

    result["failure_reason"] = last_error
    print(f"[PIXELDRAIN] All {UPLOAD_ATTEMPTS} attempts failed.", file=sys.stderr)
    _write_report(result)
    sys.exit(1)


if __name__ == "__main__":
    main()
