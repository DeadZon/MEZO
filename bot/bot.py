from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.parse

import requests
import telebot
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("mezo.bot")

# ── Build backend (global default only — per-session backend overrides this) ──
BUILD_BACKEND: str = os.environ.get("BUILD_BACKEND", "fly").lower()

# ── Workflow file mapping (explicit — never generate filenames dynamically) ───
WORKFLOW_MAP: dict = {
    ("mtk",  "fly"):    "fly_mezo_mtk.yml",
    ("snap", "fly"):    "fly_mezo_snapdragon.yml",
    ("mtk",  "github"): "mezo_mtk.yml",
    ("snap", "github"): "mezo_snapdragon.yml",
}

# ── Repository ────────────────────────────────────────────────────────────────
REPO_OWNER: str = os.environ.get("REPO_OWNER", "DeadZon")
REPO_NAME:  str = os.environ.get("REPO_NAME",  "MEZO")
REPO_REF:   str = "main"

# ── Developer access list ─────────────────────────────────────────────────────
_DEV_IDS_ENV = os.environ.get("DEV_IDS", "305266619,7504802216,6114057985")
DEV_IDS: list = [
    int(i)
    for i in _DEV_IDS_ENV.split(",")
    if i.strip().lstrip("-").isdigit()
]

# ── Group chat IDs ────────────────────────────────────────────────────────────
MTK_GROUP_ID:  int = int(os.environ.get("MTK_GROUP_ID",  "-1003908135274"))
SNAP_GROUP_ID: int = int(os.environ.get("SNAP_GROUP_ID", "-1003920954744"))

# ── Dry-run ───────────────────────────────────────────────────────────────────
LOG_PAYLOAD_ONLY: bool = os.environ.get("LOG_PAYLOAD_ONLY", "").lower() in ("1", "true")

# ── Telegram bot token ────────────────────────────────────────────────────────
_BOT_TOKEN: str = ""
for _var in ("BOT_TOKEN", "TELEGRAM_BOT_TOKEN"):
    _BOT_TOKEN = os.environ.get(_var, "").strip()
    if _BOT_TOKEN:
        break

if not _BOT_TOKEN:
    raise RuntimeError("Telegram bot token not found. Set BOT_TOKEN or TELEGRAM_BOT_TOKEN.")

bot = telebot.TeleBot(_BOT_TOKEN)
BOT_USERNAME: str = os.environ.get("BOT_USERNAME", "").lower().lstrip("@")

# ── Device lists ──────────────────────────────────────────────────────────────
MTK_DEVICES: list = ["agate", "aristotle", "daumier", "plato", "zircon"]
SNAPDRAGON_DEVICES: list = [
    "amethyst", "aurora", "babylon", "breeze", "chenfeng", "cupid",
    "dada", "dagu", "diting", "dizi", "flame", "fuxi",
    "garnet", "goku", "haotian", "haydn", "houji", "ingres",
    "ishtar", "lisa", "liuqin", "marble", "mayfly", "miro",
    "mondrian", "moonstone", "munch", "muyu", "myron", "nezha",
    "nuwa", "odin", "onyx", "pandora", "peridot", "piano",
    "pipa", "popsicle", "pudding", "redwood", "ruan", "sapphire",
    "sapphiren", "sheng", "shennong", "sky", "socrates", "star",
    "sunstone", "taoyao", "tapas", "thor", "topaz", "uke",
    "unicorn", "venus", "vermeer", "vili", "xuanyuan", "xun",
    "yudi", "yupei", "zeus", "zijin", "ziyi", "zizhan", "zorn",
]
_MTK_SET  = set(MTK_DEVICES)
_SNAP_SET = set(SNAPDRAGON_DEVICES)

STYLES      = ["Lite", "Plus", "Legend", "Ninja"]
STYLE_TIERS = {"Lite": "Free", "Plus": "Free", "Legend": "Paid", "Ninja": "Paid"}

SESSION_TTL = 1800  # seconds

# ── Arabic / English build-intent keywords ────────────────────────────────────
_BUILD_KW = (
    "ابني", "ابنيلك", "ابدأ بناء", "شغل بيلد", "اعمل روم",
    "build", "start build",
)

# ── Style aliases ─────────────────────────────────────────────────────────────
_STYLE_ALIASES: dict = {
    "لايت": "Lite",   "lite": "Lite",
    "بلس":  "Plus",   "plus": "Plus",
    "ليجند": "Legend", "legend": "Legend",
    "نينجا": "Ninja",  "ninja": "Ninja",
}

# ── Backend aliases ───────────────────────────────────────────────────────────
_BACKEND_ALIASES: dict = {
    "فلاي": "fly",     "fly": "fly",
    "جيتهاب": "github", "github": "github", "actions": "github",
    "جيت هاب": "github",
}

# ── SoC aliases ───────────────────────────────────────────────────────────────
_SOC_ALIASES: dict = {
    "mtk": "mtk", "ميدياتك": "mtk", "mediatek": "mtk",
    "snap": "snap", "snapdragon": "snap", "سناب": "snap",
}

# ── Region code mapping ───────────────────────────────────────────────────────
_REGION_CODES: dict = {
    "CNXM": "CN", "MIXM": "Global", "EUXM": "EU",
    "INXM": "India", "RUXM": "Russia", "TRXM": "Turkey",
    "TWXM": "Taiwan", "IDXM": "Indonesia",
}

# ── ROM version pattern ───────────────────────────────────────────────────────
_ROM_VER_PAT   = re.compile(r'(OS[123]\.\d+\.\d+\.\d+\.[A-Z0-9]+|V\d+\.\d+\.\d+\.[A-Z0-9]+)', re.I)
_ANDROID_PAT   = re.compile(r'user-(\d+)\.\d+', re.I)

# ── Per-chat-user sessions ────────────────────────────────────────────────────
sessions: dict = {}   # (chat_id, user_id) -> session dict

# Kept for any forward-compat references (not used in new flow)
user_config: dict = {}


# ─────────────────────────────────────────────────────────────────────────────
# Session helpers
# ─────────────────────────────────────────────────────────────────────────────

def _new_session() -> dict:
    return {
        "state":               "waiting_rom_url",
        "rom_url":             None,
        "device":              None,
        "soc":                 None,
        "rom_version":         None,
        "os_version":          None,
        "android_version":     None,
        "region":              None,
        "rom_type":            None,
        "style":               "Lite",
        "backend":             BUILD_BACKEND,
        "mode":                "build",
        "upload_pixeldrain":   True,
        "notify_telegram":     True,
        "allow_oversized_final": True,
        "vm_cpus":             "16",
        "vm_memory":           "131072",
        "server_id":           "1",
        "_style_set":          False,
        "_backend_set":        False,
        "_server_set":         False,
        "created_at":          time.time(),
    }


def _get_sess(chat_id: int, user_id: int) -> dict | None:
    key  = (chat_id, user_id)
    sess = sessions.get(key)
    if sess and (time.time() - sess.get("created_at", 0)) > SESSION_TTL:
        del sessions[key]
        return None
    return sess


def _set_sess(chat_id: int, user_id: int, sess: dict) -> None:
    sessions[(chat_id, user_id)] = sess


def _clear_sess(chat_id: int, user_id: int) -> None:
    sessions.pop((chat_id, user_id), None)


# ─────────────────────────────────────────────────────────────────────────────
# ROM URL parser
# ─────────────────────────────────────────────────────────────────────────────

def parse_rom_url(url: str) -> dict:
    result: dict = {
        "device": None, "rom_version": None, "os_version": None,
        "android_version": None, "region": None, "rom_type": None,
    }

    path     = urllib.parse.urlparse(url).path
    filename = os.path.basename(path) if path else url

    # ROM type
    low = filename.lower()
    if low.endswith(".zip") or "ota_full" in low or "recovery" in low:
        result["rom_type"] = "Recovery ZIP"
    elif low.endswith(".tgz") or "images" in low or "fastboot" in low:
        result["rom_type"] = "Fastboot TGZ"
    else:
        result["rom_type"] = "ZIP"

    # ROM version
    m = _ROM_VER_PAT.search(filename)
    if m:
        result["rom_version"] = m.group(1)
        ver = result["rom_version"].upper()
        if   ver.startswith("OS3"): result["os_version"] = "OS3"
        elif ver.startswith("OS2"): result["os_version"] = "OS2"
        elif ver.startswith("OS1"): result["os_version"] = "OS1"
        elif ver.startswith("V"):   result["os_version"] = "MIUI"

    # Android version
    m2 = _ANDROID_PAT.search(filename)
    if m2:
        result["android_version"] = f"A{m2.group(1)}"

    # Region
    up = filename.upper()
    for code, region in _REGION_CODES.items():
        if code in up:
            result["region"] = region
            break

    # Device codename — "codename-ota_full-" or "codename_images" or first segment
    m3 = re.match(r'^([a-z][a-z0-9]+?)[-_](?:ota_full|images|global|fastboot|recovery)', filename, re.I)
    if m3:
        result["device"] = m3.group(1).lower()
    else:
        parts = re.split(r'[-_]', filename)
        if parts and re.match(r'^[a-z][a-z0-9]+$', parts[0], re.I) and len(parts[0]) >= 3:
            result["device"] = parts[0].lower()

    return result


def _detect_soc(codename: str) -> str | None:
    if not codename:
        return None
    c = codename.lower()
    if c in _MTK_SET:
        return "mtk"
    if c in _SNAP_SET:
        return "snap"
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Token / auth helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_github_token() -> str:
    for var in ("G_TOKEN", "GITHUB_TOKEN", "GH_TOKEN"):
        val = os.environ.get(var, "").strip()
        if val:
            return val
    return ""


def is_dev(user_id: int) -> bool:
    if not DEV_IDS:
        return True
    return user_id in DEV_IDS


def is_authorized(message) -> bool:
    uid = message.from_user.id if message.from_user else 0
    return is_dev(uid)


# ─────────────────────────────────────────────────────────────────────────────
# Workflow helpers
# ─────────────────────────────────────────────────────────────────────────────

def normalize_soc(soc: str) -> str:
    s = soc.lower().strip()
    if s in ("mtk", "mediatek"):
        return "mtk"
    if s in ("snap", "snapdragon"):
        return "snap"
    raise ValueError(f"Unknown SoC: {soc!r}")


def get_workflow_file(soc: str, backend: str) -> str:
    norm = normalize_soc(soc)
    key  = (norm, backend.lower())
    wf   = WORKFLOW_MAP.get(key)
    if not wf:
        raise ValueError(f"No workflow for soc={soc!r}, backend={backend!r}. Known: {list(WORKFLOW_MAP)}")
    return wf


def build_dispatch_inputs(sess: dict) -> dict:
    backend = sess["backend"]
    soc     = sess["soc"]
    norm    = normalize_soc(soc)

    if backend == "fly":
        inputs: dict = {
            "rom_url":               sess["rom_url"],
            "style":                 sess["style"],
            "mode":                  sess["mode"],
            "upload_pixeldrain":     str(sess["upload_pixeldrain"]).lower(),
            "notify_telegram":       str(sess["notify_telegram"]).lower(),
            "allow_oversized_final": str(sess["allow_oversized_final"]).lower(),
            "VM_CPUS":               sess.get("vm_cpus", "16"),
            "VM_MEMORY":             sess.get("vm_memory", "131072"),
        }
        if norm == "snap":
            inputs["server_id"] = str(sess.get("server_id", "1"))
    else:  # github
        inputs = {
            "input_url":         sess["rom_url"],
            "style":             sess["style"],
            "notify_telegram":   str(sess["notify_telegram"]).lower(),
            "upload_pixeldrain": str(sess["upload_pixeldrain"]).lower(),
        }
    return inputs


# ─────────────────────────────────────────────────────────────────────────────
# GitHub API
# ─────────────────────────────────────────────────────────────────────────────

def _github_headers(token: str) -> dict:
    return {
        "Authorization":        f"Bearer {token}",
        "Accept":               "application/vnd.github+json",
        "Content-Type":         "application/json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def github_dispatch_workflow(workflow_file: str, inputs: dict) -> tuple:
    token = get_github_token()
    if not token:
        return 0, {"error": "GitHub token missing. Set G_TOKEN, GITHUB_TOKEN, or GH_TOKEN."}

    url = (
        f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}"
        f"/actions/workflows/{workflow_file}/dispatches"
    )
    payload = {"ref": REPO_REF, "inputs": inputs}

    if LOG_PAYLOAD_ONLY:
        log.info("[DRY-RUN] Would dispatch %s | payload: %s", workflow_file, json.dumps(inputs))
        return 204, {}

    try:
        resp = requests.post(url, headers=_github_headers(token), json=payload, timeout=30)
        body: dict = {}
        try:
            body = resp.json()
        except Exception:
            pass
        return resp.status_code, body
    except requests.exceptions.RequestException as exc:
        return 0, {"error": str(exc)}


def _poll_for_run_url(
    workflow_file: str,
    dispatch_time: float,
    max_wait: int = 30,
) -> str:
    """Poll GitHub Actions API to find the run URL for a just-dispatched workflow.

    Returns run URL string if found within max_wait seconds, else empty string.
    Does NOT print the token.
    """
    token = get_github_token()
    if not token:
        return ""

    url = (
        f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}"
        f"/actions/workflows/{workflow_file}/runs"
        f"?branch={REPO_REF}&event=workflow_dispatch&per_page=10"
    )

    deadline = time.time() + max_wait
    while time.time() < deadline:
        time.sleep(3)
        try:
            resp = requests.get(url, headers=_github_headers(token), timeout=15)
            if resp.status_code != 200:
                continue
            runs = resp.json().get("workflow_runs", [])
            for run in runs:
                created = run.get("created_at", "")
                # created_at is ISO8601 UTC; compare roughly
                try:
                    import datetime as _dt
                    ct = _dt.datetime.fromisoformat(created.replace("Z", "+00:00")).timestamp()
                    if ct >= dispatch_time - 10:  # 10s tolerance
                        run_id  = run.get("id", "")
                        server  = "https://github.com"
                        repo    = f"{REPO_OWNER}/{REPO_NAME}"
                        if run_id:
                            return f"{server}/{repo}/actions/runs/{run_id}"
                except Exception:
                    pass
        except Exception:
            pass

    return ""


def format_github_error(status_code: int, response_body: dict, workflow_file: str) -> str:
    hints = {
        0:   "Network error — check bot connectivity.",
        401: "Token is invalid or expired.",
        403: "Token lacks 'workflow' or 'actions' permission.",
        404: "Workflow file not found, or repo access is denied.",
        422: "Invalid workflow inputs, or ref does not exist.",
    }
    hint     = hints.get(status_code, "Unexpected error — check token and repo config.")
    body_str = json.dumps(response_body, indent=2)[:400] if response_body else "(empty)"
    return (
        f"*حصل خطأ في تشغيل الـ Workflow.*\n\n"
        f"Repository: `{REPO_OWNER}/{REPO_NAME}`\n"
        f"Workflow: `{workflow_file}`\n"
        f"Ref: `{REPO_REF}`\n"
        f"HTTP: `{status_code}`\n\n"
        f"*GitHub response:*\n```{body_str}```\n\n"
        f"*Hint:* {hint}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Keyboard builders
# ─────────────────────────────────────────────────────────────────────────────

def _style_kb(current: str = "Lite") -> InlineKeyboardMarkup:
    markup = InlineKeyboardMarkup()
    row = []
    for s in STYLES:
        label = f"✅ {s}" if s == current else s
        row.append(InlineKeyboardButton(label, callback_data=f"style:{s}"))
    markup.row(*row)
    return markup


def _backend_kb() -> InlineKeyboardMarkup:
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("🚀 Fly.io",         callback_data="backend:fly"),
        InlineKeyboardButton("⚙️ GitHub Actions", callback_data="backend:github"),
    )
    return markup


def _soc_kb() -> InlineKeyboardMarkup:
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("MTK",        callback_data="soc:mtk"),
        InlineKeyboardButton("Snapdragon", callback_data="soc:snap"),
    )
    return markup


def _server_kb() -> InlineKeyboardMarkup:
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("Server 1", callback_data="server:1"),
        InlineKeyboardButton("Server 2", callback_data="server:2"),
    )
    return markup


def _summary_kb() -> InlineKeyboardMarkup:
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("✅ ابدأ البيلد",   callback_data="start_build"))
    markup.row(
        InlineKeyboardButton("✏️ غير الاستايل", callback_data="change_style"),
        InlineKeyboardButton("🔁 غير الباكند",  callback_data="change_backend"),
    )
    markup.row(InlineKeyboardButton("❌ إلغاء",         callback_data="cancel_build"))
    return markup


def _lbl_soc(soc: str) -> str:
    return "MTK" if soc == "mtk" else "Snapdragon"


def _lbl_backend(backend: str) -> str:
    return "Fly.io" if backend == "fly" else "GitHub Actions"


# ─────────────────────────────────────────────────────────────────────────────
# Message composers
# ─────────────────────────────────────────────────────────────────────────────

def _fmt_parsed(sess: dict) -> str:
    lines = []
    if sess.get("device"):       lines.append(f"📱 الجهاز: `{sess['device']}`")
    if sess.get("soc"):          lines.append(f"🧩 المعالج: {_lbl_soc(sess['soc'])}")
    if sess.get("rom_version"):  lines.append(f"💿 الإصدار: `{sess['rom_version']}`")
    if sess.get("os_version"):   lines.append(f"🤖 النظام: {sess['os_version']}")
    if sess.get("region"):       lines.append(f"🌍 المنطقة: {sess['region']}")
    if sess.get("rom_type"):     lines.append(f"📦 النوع: {sess['rom_type']}")
    return "\n".join(lines) if lines else "معلومات محدودة — بكمل التفاصيل."


def _fmt_summary(sess: dict) -> str:
    srv = (
        f"\n🖥 السيرفر: {sess.get('server_id', '1')}"
        if sess.get("soc") == "snap" and sess.get("backend") == "fly"
        else ""
    )
    return (
        f"🔥 *ملخص البيلد*\n\n"
        f"📱 الجهاز: `{sess.get('device') or '—'}`\n"
        f"🧩 المعالج: {_lbl_soc(sess.get('soc', 'mtk'))}\n"
        f"💿 الروم: `{sess.get('rom_version') or '—'}`\n"
        f"🤖 النظام: {sess.get('os_version') or '—'}\n"
        f"🌍 المنطقة: {sess.get('region') or '—'}\n"
        f"📦 النوع: {sess.get('rom_type') or '—'}\n"
        f"🎨 الاستايل: {sess.get('style', 'Lite')}\n"
        f"⚙️ الموود: {sess.get('mode', 'build')}\n"
        f"🚀 الباكند: {_lbl_backend(sess.get('backend', 'fly'))}\n"
        f"☁️ PixelDrain: {'ON' if sess.get('upload_pixeldrain') else 'OFF'}\n"
        f"📣 تليجرام: {'ON' if sess.get('notify_telegram') else 'OFF'}\n"
        f"🧠 CPU: {sess.get('vm_cpus', '16')}\n"
        f"🧬 RAM: {sess.get('vm_memory', '131072')} MB"
        f"{srv}\n\n"
        f"Project DeadZone By MEZO Enjoy"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Intent parser — extract style/backend/soc/url from free text
# ─────────────────────────────────────────────────────────────────────────────

def _parse_intent(text: str) -> dict:
    result: dict = {"style": None, "backend": None, "soc": None, "rom_url": None}
    t = text.lower()

    for alias, val in _STYLE_ALIASES.items():
        if alias in t:
            result["style"] = val
            break

    for alias, val in _BACKEND_ALIASES.items():
        if alias in t:
            result["backend"] = val
            break

    for alias, val in _SOC_ALIASES.items():
        if alias in t:
            result["soc"] = val
            break

    m = re.search(r'https?://\S+', text)
    if m:
        result["rom_url"] = m.group(0)

    return result


def _has_build_intent(text: str) -> bool:
    t = text.lower()
    return any(kw in t for kw in _BUILD_KW)


# ─────────────────────────────────────────────────────────────────────────────
# Group / mention detection
# ─────────────────────────────────────────────────────────────────────────────

def _is_for_bot(message) -> bool:
    text      = (message.text or "").strip()
    chat_type = message.chat.type if message.chat else "private"
    uid       = message.from_user.id if message.from_user else 0
    cid       = message.chat.id

    # Always respond when there is an active non-idle session
    sess = sessions.get((cid, uid))
    if sess and sess.get("state") not in ("idle", "finished"):
        if (time.time() - sess.get("created_at", 0)) <= SESSION_TTL:
            return True

    # Private chat — always ours
    if chat_type == "private":
        return True

    # Explicit slash command
    if text.startswith("/"):
        return True

    # Bot mentioned by @username
    if BOT_USERNAME and f"@{BOT_USERNAME}" in text.lower():
        return True

    # Reply to the bot's own message
    if message.reply_to_message and message.reply_to_message.from_user:
        ru = message.reply_to_message.from_user.username or ""
        if BOT_USERNAME and ru.lower() == BOT_USERNAME:
            return True

    # Group build intent in a known build channel
    if chat_type in ("group", "supergroup"):
        if _has_build_intent(text) and cid in (MTK_GROUP_ID, SNAP_GROUP_ID):
            return True

    return False


# ─────────────────────────────────────────────────────────────────────────────
# Build dispatch
# ─────────────────────────────────────────────────────────────────────────────

def _do_dispatch(chat_id: int, user_id: int, edit_msg_id: int | None = None) -> None:
    sess = _get_sess(chat_id, user_id)
    if not sess:
        bot.send_message(chat_id, "❌ الجلسة انتهت. قول ابني من الأول.")
        return

    if not get_github_token():
        bot.send_message(chat_id, "❌ GitHub token مش موجود. اضبط G_TOKEN في البيئة.")
        return

    try:
        workflow_file = get_workflow_file(sess["soc"], sess["backend"])
    except ValueError as exc:
        bot.send_message(chat_id, f"❌ Config error: {exc}")
        return

    inputs      = build_dispatch_inputs(sess)
    b_label     = _lbl_backend(sess["backend"])
    waking_line = (
        "Waking up Fly.io server..."
        if sess["backend"] == "fly"
        else "Build started on GitHub Actions..."
    )

    dispatch_time = time.time()
    log.info("Dispatching workflow=%s backend=%s inputs=%s", workflow_file, sess["backend"], inputs)
    status_code, response_body = github_dispatch_workflow(workflow_file, inputs)

    if status_code == 204:
        srv_line = f"\n🖥 Server: `{inputs['server_id']}`" if "server_id" in inputs else ""

        # Poll for the GitHub Actions run URL (up to 30s)
        run_url = _poll_for_run_url(workflow_file, dispatch_time, max_wait=30)
        run_url_line = (
            f"\n🔗 GitHub run: {run_url}"
            if run_url
            else "\n🔗 GitHub run: لم يُعثر عليه بعد — تحقق من Actions"
        )

        text = (
            f"✅ *Workflow triggered successfully.*\n\n"
            f"Repository: `{REPO_OWNER}/{REPO_NAME}`\n"
            f"Workflow: `{workflow_file}`\n"
            f"Ref: `{REPO_REF}`\n"
            f"🎨 Style: `{sess['style']}`\n"
            f"⚙️ Mode: `{sess['mode']}`\n"
            f"🚀 Backend: {b_label}"
            f"{srv_line}"
            f"{run_url_line}\n\n"
            f"{waking_line}\n\n"
            f"تمام، بدأت أشغل البيلد 🚀\n"
            f"هتوصلك إشعارات اللايف من نظام البناء نفسه."
        )
        log.info("Dispatch OK: workflow=%s style=%s run_url=%s", workflow_file, sess["style"], run_url)
    else:
        text = format_github_error(status_code, response_body, workflow_file)
        log.error("Dispatch FAILED: workflow=%s status=%s body=%s", workflow_file, status_code, response_body)

    sess["state"] = "finished"
    _set_sess(chat_id, user_id, sess)

    if edit_msg_id:
        try:
            bot.edit_message_text(
                text, chat_id=chat_id, message_id=edit_msg_id,
                parse_mode="Markdown", disable_web_page_preview=True,
            )
            return
        except Exception:
            pass
    bot.send_message(chat_id, text, parse_mode="Markdown", disable_web_page_preview=True)


# ─────────────────────────────────────────────────────────────────────────────
# Conversation step functions
# ─────────────────────────────────────────────────────────────────────────────

def _after_url(chat_id: int, user_id: int, url: str, intent: dict) -> None:
    sess = _get_sess(chat_id, user_id) or _new_session()

    sess["rom_url"] = url
    parsed = parse_rom_url(url)
    for k, v in parsed.items():
        if v is not None:
            sess[k] = v

    # Apply intent overrides
    if intent.get("style"):
        sess["style"]      = intent["style"]
        sess["_style_set"] = True
    if intent.get("backend"):
        sess["backend"]      = intent["backend"]
        sess["_backend_set"] = True
    if intent.get("soc"):
        sess["soc"] = intent["soc"]

    # Auto-detect SoC from codename if still unknown
    if not sess.get("soc") and sess.get("device"):
        sess["soc"] = _detect_soc(sess["device"])

    _set_sess(chat_id, user_id, sess)

    info_block = _fmt_parsed(sess)
    prefix     = f"تمام، فهمت الروم دي 👇\n\n{info_block}\n\n"

    if not sess.get("soc"):
        sess["state"] = "waiting_soc"
        _set_sess(chat_id, user_id, sess)
        who = f"الجهاز: `{sess['device']}`\n" if sess.get("device") else ""
        bot.send_message(
            chat_id,
            f"{prefix}{who}محتاج أعرف نوع المعالج:",
            parse_mode="Markdown",
            reply_markup=_soc_kb(),
        )
        return

    _step_style(chat_id, user_id, prefix)


def _step_style(chat_id: int, user_id: int, prefix: str = "") -> None:
    sess = _get_sess(chat_id, user_id)
    if not sess:
        return
    if sess.get("_style_set"):
        _step_backend(chat_id, user_id)
        return
    sess["state"] = "waiting_style"
    _set_sess(chat_id, user_id, sess)
    bot.send_message(
        chat_id,
        (prefix + "اختار الاستايل اللي عاوز تبني بيه:").strip(),
        parse_mode="Markdown",
        reply_markup=_style_kb(sess.get("style", "Lite")),
    )


def _step_backend(chat_id: int, user_id: int) -> None:
    sess = _get_sess(chat_id, user_id)
    if not sess:
        return
    if sess.get("_backend_set"):
        _step_server_or_summary(chat_id, user_id)
        return
    sess["state"] = "waiting_backend"
    _set_sess(chat_id, user_id, sess)
    bot.send_message(
        chat_id,
        "هتبنيها على إيه؟\nGitHub Actions ولا Fly.io؟",
        reply_markup=_backend_kb(),
    )


def _step_server_or_summary(chat_id: int, user_id: int) -> None:
    sess = _get_sess(chat_id, user_id)
    if not sess:
        return
    if sess.get("soc") == "snap" and sess.get("backend") == "fly" and not sess.get("_server_set"):
        sess["state"] = "waiting_server_id"
        _set_sess(chat_id, user_id, sess)
        bot.send_message(chat_id, "اختار سيرفر Snapdragon:", reply_markup=_server_kb())
        return
    _step_summary(chat_id, user_id)


def _step_summary(chat_id: int, user_id: int) -> None:
    sess = _get_sess(chat_id, user_id)
    if not sess:
        return
    sess["state"] = "ready_to_start"
    _set_sess(chat_id, user_id, sess)
    bot.send_message(
        chat_id,
        _fmt_summary(sess),
        parse_mode="Markdown",
        reply_markup=_summary_kb(),
        disable_web_page_preview=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Core build trigger (entry point for all build-intent messages)
# ─────────────────────────────────────────────────────────────────────────────

def _start_flow(message) -> None:
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else 0

    if not is_authorized(message):
        bot.send_message(chat_id, "مش مسموحلك تشغل بيلد هنا.")
        return

    text   = message.text or ""
    clean  = re.sub(r'@\S+', '', text).strip()
    intent = _parse_intent(clean)

    # Create fresh session
    sess = _new_session()

    if intent.get("style"):
        sess["style"]      = intent["style"]
        sess["_style_set"] = True
    if intent.get("backend"):
        sess["backend"]      = intent["backend"]
        sess["_backend_set"] = True
    if intent.get("soc"):
        sess["soc"] = intent["soc"]

    # Auto-detect SoC from group channel if still unknown
    if not sess.get("soc"):
        if message.chat.id == MTK_GROUP_ID:
            sess["soc"] = "mtk"
        elif message.chat.id == SNAP_GROUP_ID:
            sess["soc"] = "snap"

    _set_sess(chat_id, user_id, sess)

    # If ROM URL already in the message, skip asking
    if intent.get("rom_url"):
        _after_url(chat_id, user_id, intent["rom_url"], intent)
        return

    sess["state"] = "waiting_rom_url"
    _set_sess(chat_id, user_id, sess)
    bot.send_message(chat_id, "تمام يا باش 🔥\nابعتلي لينك الروم وأنا هفهم الجهاز والإصدار لوحدي.")


# ─────────────────────────────────────────────────────────────────────────────
# Command handlers
# ─────────────────────────────────────────────────────────────────────────────

@bot.message_handler(commands=["build", "start"])
def cmd_build(message) -> None:
    _start_flow(message)


@bot.message_handler(commands=["cancel"])
def cmd_cancel(message) -> None:
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else 0
    _clear_sess(chat_id, user_id)
    bot.send_message(chat_id, "تمام، تم إلغاء الجلسة. ✅")


@bot.message_handler(commands=["status"])
def cmd_status(message) -> None:
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else 0
    sess    = _get_sess(chat_id, user_id)
    if not sess:
        bot.send_message(chat_id, "مفيش جلسة حالية. قول ابني عشان تبدأ.")
        return
    bot.send_message(
        chat_id,
        f"*الجلسة الحالية:*\n"
        f"State: `{sess['state']}`\n"
        f"Style: {sess.get('style', '—')}\n"
        f"Backend: {_lbl_backend(sess.get('backend', 'fly'))}\n"
        f"SoC: {_lbl_soc(sess.get('soc', '?'))}\n"
        f"ROM: `{sess.get('rom_version') or '—'}`",
        parse_mode="Markdown",
    )


@bot.message_handler(commands=["help"])
def cmd_help(message) -> None:
    bot.send_message(
        message.chat.id,
        "*MEZO Bot — أمثلة:*\n\n"
        "`@bot ابني`\n"
        "`@bot ابني فلاي`\n"
        "`@bot ابني github lite`\n"
        "`@bot build snap fly lite`\n"
        "`@bot ابني <ROM_URL>`\n\n"
        "*أوامر:*\n"
        "/build — ابدأ بيلد جديد\n"
        "/cancel — إلغاء الجلسة الحالية\n"
        "/status — اعرض الجلسة الحالية\n"
        "/help — الأوامر دي\n\n"
        "*الاستايلات:* Lite ✅ · Plus · Legend · Ninja\n"
        "*الباكند:* Fly.io (افتراضي) · GitHub Actions",
        parse_mode="Markdown",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Free-text handler (group mentions + active sessions)
# ─────────────────────────────────────────────────────────────────────────────

@bot.message_handler(func=lambda m: _is_for_bot(m) and bool(m.text))
def handle_text(message) -> None:
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else 0
    text    = message.text or ""
    clean   = re.sub(r'@\S+', '', text).strip()
    sess    = _get_sess(chat_id, user_id)

    # ── Active session: waiting for ROM URL ───────────────────────────────────
    if sess and sess.get("state") == "waiting_rom_url":
        m = re.search(r'https?://\S+', text)
        if m:
            intent = _parse_intent(clean)
            _after_url(chat_id, user_id, m.group(0), intent)
        else:
            bot.send_message(chat_id, "ابعتلي لينك ROM صحيح (يبدأ بـ http أو https).")
        return

    # ── Active session: ready to start — text confirmation ───────────────────
    if sess and sess.get("state") == "ready_to_start":
        _GO_WORDS = ("ابدأ", "start", "تمام", "يلا", "ابدأ البناء", "ok", "نعم", "go")
        if any(w in clean.lower() for w in _GO_WORDS):
            if not is_authorized(message):
                bot.send_message(chat_id, "مش مسموحلك تشغل بيلد هنا.")
                return
            _do_dispatch(chat_id, user_id)
        return

    # ── Build intent in free text ─────────────────────────────────────────────
    if _has_build_intent(clean):
        _start_flow(message)
        return


# ─────────────────────────────────────────────────────────────────────────────
# Callback query handler
# ─────────────────────────────────────────────────────────────────────────────

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call) -> None:
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    data    = call.data
    sess    = _get_sess(chat_id, user_id)

    # ── Style selection ───────────────────────────────────────────────────────
    if data.startswith("style:"):
        style = data.split(":", 1)[1]
        if style not in STYLES or not sess:
            bot.answer_callback_query(call.id)
            return
        sess["style"]      = style
        sess["_style_set"] = True
        _set_sess(chat_id, user_id, sess)
        bot.answer_callback_query(call.id, f"✅ {style}")
        try:
            bot.edit_message_reply_markup(
                chat_id=chat_id, message_id=call.message.message_id,
                reply_markup=_style_kb(style),
            )
        except Exception:
            pass
        _step_backend(chat_id, user_id)
        return

    # ── Backend selection ─────────────────────────────────────────────────────
    if data.startswith("backend:"):
        backend = data.split(":", 1)[1]
        if backend not in ("fly", "github") or not sess:
            bot.answer_callback_query(call.id)
            return
        sess["backend"]      = backend
        sess["_backend_set"] = True
        _set_sess(chat_id, user_id, sess)
        bot.answer_callback_query(call.id, _lbl_backend(backend))
        _step_server_or_summary(chat_id, user_id)
        return

    # ── SoC selection ─────────────────────────────────────────────────────────
    if data.startswith("soc:"):
        soc = data.split(":", 1)[1]
        if soc not in ("mtk", "snap") or not sess:
            bot.answer_callback_query(call.id)
            return
        sess["soc"] = soc
        _set_sess(chat_id, user_id, sess)
        bot.answer_callback_query(call.id, _lbl_soc(soc))
        _step_style(chat_id, user_id)
        return

    # ── Server selection ──────────────────────────────────────────────────────
    if data.startswith("server:"):
        server = data.split(":", 1)[1]
        if not sess:
            bot.answer_callback_query(call.id)
            return
        sess["server_id"]   = server
        sess["_server_set"] = True
        _set_sess(chat_id, user_id, sess)
        bot.answer_callback_query(call.id, f"Server {server}")
        _step_summary(chat_id, user_id)
        return

    # ── Start build ───────────────────────────────────────────────────────────
    if data == "start_build":
        if not is_dev(user_id):
            bot.answer_callback_query(call.id, "مش مسموحلك!", show_alert=True)
            return
        if not sess:
            bot.answer_callback_query(call.id, "الجلسة انتهت.", show_alert=True)
            return
        bot.answer_callback_query(call.id, "🚀 بدأ البيلد!")
        try:
            bot.edit_message_reply_markup(
                chat_id=chat_id, message_id=call.message.message_id,
                reply_markup=None,
            )
        except Exception:
            pass
        _do_dispatch(chat_id, user_id, edit_msg_id=call.message.message_id)
        return

    # ── Cancel ────────────────────────────────────────────────────────────────
    if data == "cancel_build":
        _clear_sess(chat_id, user_id)
        bot.answer_callback_query(call.id, "تم الإلغاء ✅")
        try:
            bot.edit_message_text(
                "❌ تم إلغاء البيلد.",
                chat_id=chat_id, message_id=call.message.message_id,
            )
        except Exception:
            pass
        return

    # ── Change style (from summary) ───────────────────────────────────────────
    if data == "change_style":
        if not sess:
            bot.answer_callback_query(call.id)
            return
        sess["_style_set"] = False
        _set_sess(chat_id, user_id, sess)
        bot.answer_callback_query(call.id)
        bot.send_message(chat_id, "اختار الاستايل:", reply_markup=_style_kb(sess.get("style", "Lite")))
        return

    # ── Change backend (from summary) ─────────────────────────────────────────
    if data == "change_backend":
        if not sess:
            bot.answer_callback_query(call.id)
            return
        sess["_backend_set"] = False
        _set_sess(chat_id, user_id, sess)
        bot.answer_callback_query(call.id)
        bot.send_message(chat_id, "اختار الباكند:", reply_markup=_backend_kb())
        return

    # ── noop ──────────────────────────────────────────────────────────────────
    bot.answer_callback_query(call.id)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Fetch bot username via getMe so group mentions work without hardcoding
    try:
        me = bot.get_me()
        if me and me.username:
            BOT_USERNAME = me.username.lower()
            log.info("Bot username: @%s", BOT_USERNAME)
    except Exception as exc:
        log.warning("Could not fetch bot username via getMe: %s", exc)
        if BOT_USERNAME:
            log.info("Using BOT_USERNAME from env: @%s", BOT_USERNAME)

    gh_token = get_github_token()
    if not gh_token:
        log.warning("No GitHub token found. Set G_TOKEN, GITHUB_TOKEN, or GH_TOKEN.")
    else:
        log.info("GitHub token loaded (length=%d)", len(gh_token))

    if not DEV_IDS:
        log.warning("DEV_IDS not set; all users can start builds.")
    else:
        log.info("Developer IDs  : %d IDs loaded", len(DEV_IDS))

    log.info("Build backend (default): %s", BUILD_BACKEND)
    log.info("Repository     : %s/%s @ %s", REPO_OWNER, REPO_NAME, REPO_REF)
    log.info("Starting MEZO bot (polling)...")
    bot.infinity_polling()
