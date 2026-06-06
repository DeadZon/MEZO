#!/usr/bin/env python3
"""TelegramAutoBuildStatus — live status notifications for the auto build loop.

Sends one message to TELEGRAM_STATUS_CHAT_ID at run start, then edits
that same message at each stage. Falls back to a new message if edit
fails (flood limit, message too old, etc.).

Never raises — all Telegram errors are swallowed so the build continues.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from html import escape
from typing import Any


TELEGRAM_API = "https://api.telegram.org"


class TelegramAutoBuildStatus:
    """Edit a single status message in TELEGRAM_STATUS_CHAT_ID throughout the run."""

    def __init__(self) -> None:
        self._token: str    = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        self._chat_id: str  = os.environ.get("TELEGRAM_STATUS_CHAT_ID", "").strip()
        self._message_id: int | None = None
        self._enabled: bool = bool(self._token and self._chat_id)
        self.max_builds:     int   = 1
        self.built_count:    int   = 0
        self.published_count: int  = 0
        self.failed_count:   int   = 0
        self._started_at:    float = time.time()

    # ── Low-level Telegram helpers ─────────────────────────────────────────────

    def _post(self, method: str, payload: dict[str, Any]) -> dict:
        if not self._enabled:
            return {}
        data = json.dumps(payload).encode("utf-8")
        req  = urllib.request.Request(
            f"{TELEGRAM_API}/bot{self._token}/{method}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except Exception as exc:
            print(f"[STATUS_TG] {method} error: {exc}", flush=True)
            return {}

    def _send_new(self, text: str) -> None:
        resp = self._post("sendMessage", {
            "chat_id":                  self._chat_id,
            "text":                     text,
            "parse_mode":               "HTML",
            "disable_web_page_preview": True,
        })
        if resp.get("ok"):
            self._message_id = resp["result"]["message_id"]

    def _push(self, text: str) -> None:
        """Edit existing message or send a new one; never raises."""
        if not self._enabled:
            return
        try:
            if self._message_id is None:
                self._send_new(text)
                return
            resp = self._post("editMessageText", {
                "chat_id":                  self._chat_id,
                "message_id":               self._message_id,
                "text":                     text,
                "parse_mode":               "HTML",
                "disable_web_page_preview": True,
            })
            if not resp.get("ok"):
                # Edit failed — send a fresh message instead
                self._message_id = None
                self._send_new(text)
        except Exception as exc:
            print(f"[STATUS_TG] push error: {exc}", flush=True)

    # ── Message renderer ───────────────────────────────────────────────────────

    def _fmt(
        self,
        stage: str,
        index: int       = 0,
        codename: str    = "",
        device_name: str = "",
        version: str     = "",
        region: str      = "",
        download_url: str = "",
        publish_result: str = "",
        extra: str       = "",
    ) -> str:
        elapsed = int(time.time() - self._started_at)
        lines: list[str] = ["<b>DeadZone Auto Builder</b>", ""]
        lines.append(f"Stage: <b>{escape(stage)}</b>")
        if index:
            lines.append(f"Build: {index} / {self.max_builds}")
        if codename:
            lines.append(f"Device: <code>{escape(codename)}</code>")
        if device_name and device_name != codename:
            lines.append(f"Name: {escape(device_name)}")
        if version:
            lines.append(f"Version: <code>{escape(version)}</code>")
        if region:
            lines.append(f"Region: {escape(region)}")
        if download_url:
            lines.append(f'Download: <a href="{escape(download_url)}">PixelDrain</a>')
        if publish_result:
            lines.append(f"Publish: {escape(publish_result)}")
        if extra:
            lines.append(f"\n{escape(extra)}")
        lines += [
            "",
            f"Built: {self.built_count}  "
            f"Published: {self.published_count}  "
            f"Failed: {self.failed_count}",
            f"Elapsed: {elapsed // 60}m {elapsed % 60}s",
        ]
        return "\n".join(lines)

    # ── Public stage API ───────────────────────────────────────────────────────

    def run_started(self, max_builds: int) -> None:
        self.max_builds   = max_builds
        self._started_at  = time.time()
        self._push(self._fmt(f"Run started — max {max_builds} build(s)"))

    def scan_started(self) -> None:
        self._push(self._fmt("Scanning TECH_MUKUL…"))

    def scan_done(self, queued_count: int) -> None:
        self._push(self._fmt(f"Scan done — {queued_count} item(s) in queue"))

    def queue_count(self, count: int) -> None:
        self._push(self._fmt(f"Queue: {count} item(s) pending"))

    def prune_done(self, removed: int, remaining: int) -> None:
        self._push(self._fmt(f"Prune done — removed {removed}, remaining {remaining}"))

    def build_started(self, index: int, item: dict) -> None:
        self._push(self._fmt(
            "Build started",
            index=index,
            codename=item.get("codename", ""),
            device_name=item.get("device_name", ""),
            version=item.get("version", ""),
            region=item.get("region", ""),
        ))

    def download_started(self, index: int, item: dict) -> None:
        self._push(self._fmt(
            "Downloading ROM…",
            index=index,
            codename=item.get("codename", ""),
            version=item.get("version", ""),
            region=item.get("region", ""),
        ))

    def download_done(self, index: int, item: dict) -> None:
        self._push(self._fmt(
            "Download done",
            index=index,
            codename=item.get("codename", ""),
            version=item.get("version", ""),
            region=item.get("region", ""),
        ))

    def extraction_started(self, index: int, item: dict) -> None:
        self._push(self._fmt(
            "Extracting ROM…",
            index=index,
            codename=item.get("codename", ""),
            version=item.get("version", ""),
        ))

    def extraction_done(self, index: int, item: dict) -> None:
        self._push(self._fmt(
            "Extraction done",
            index=index,
            codename=item.get("codename", ""),
            version=item.get("version", ""),
        ))

    def build_succeeded(self, index: int, item: dict) -> None:
        self._push(self._fmt(
            "Build succeeded",
            index=index,
            codename=item.get("codename", ""),
            device_name=item.get("device_name", ""),
            version=item.get("version", ""),
            region=item.get("region", ""),
        ))

    def build_failed(self, index: int, item: dict, reason: str = "") -> None:
        self._push(self._fmt(
            "Build FAILED",
            index=index,
            codename=item.get("codename", ""),
            version=item.get("version", ""),
            region=item.get("region", ""),
            extra=f"Reason: {reason}" if reason else "",
        ))

    def upload_started(self, index: int, item: dict) -> None:
        self._push(self._fmt(
            "Uploading to PixelDrain…",
            index=index,
            codename=item.get("codename", ""),
            version=item.get("version", ""),
        ))

    def upload_done(self, index: int, item: dict, download_url: str) -> None:
        self._push(self._fmt(
            "Upload done",
            index=index,
            codename=item.get("codename", ""),
            device_name=item.get("device_name", ""),
            version=item.get("version", ""),
            region=item.get("region", ""),
            download_url=download_url,
        ))

    def publish_sent(self, index: int, item: dict, download_url: str) -> None:
        self.published_count += 1
        self._push(self._fmt(
            "Published to channel",
            index=index,
            codename=item.get("codename", ""),
            device_name=item.get("device_name", ""),
            version=item.get("version", ""),
            region=item.get("region", ""),
            download_url=download_url,
            publish_result="sent",
        ))

    def publish_skipped(self, index: int, item: dict, reason: str = "") -> None:
        self._push(self._fmt(
            "Publish skipped",
            index=index,
            codename=item.get("codename", ""),
            version=item.get("version", ""),
            publish_result=f"skipped: {reason}" if reason else "skipped",
        ))

    def run_finished(
        self,
        requested: int,
        built: int,
        published: int,
        failed: int,
        skipped: int,
    ) -> None:
        elapsed = int(time.time() - self._started_at)
        lines = [
            "<b>DeadZone Auto Builder — Run Finished</b>",
            "",
            f"Requested:  {requested}",
            f"Built:      {built}",
            f"Published:  {published}",
            f"Failed:     {failed}",
            f"Skipped:    {skipped}",
            "",
            f"Elapsed: {elapsed // 60}m {elapsed % 60}s",
        ]
        self._push("\n".join(lines))
