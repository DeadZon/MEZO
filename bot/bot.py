import json
import logging
import os

import requests
import telebot
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("mezo.bot")

# ── Build backend ─────────────────────────────────────────────────────────────
# Allowed values: "fly" | "github"
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
DEV_IDS: list = [
    int(i)
    for i in os.environ.get("DEV_IDS", "305266619,7504802216,6114057985").split(",")
    if i.strip().lstrip("-").isdigit()
]

# ── Group chat IDs ────────────────────────────────────────────────────────────
MTK_GROUP_ID:  int = int(os.environ.get("MTK_GROUP_ID",  "-1003908135274"))
SNAP_GROUP_ID: int = int(os.environ.get("SNAP_GROUP_ID", "-1003920954744"))

# ── Dry-run: log payload without dispatching (set LOG_PAYLOAD_ONLY=1) ────────
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
user_config: dict = {}

# ── Device lists ──────────────────────────────────────────────────────────────
MTK_DEVICES = ["agate", "aristotle", "daumier", "plato", "zircon"]
SNAPDRAGON_DEVICES = [
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
DEVICES_PER_PAGE = 8
STYLES      = ["Lite", "Plus", "Legend", "Ninja"]
STYLE_TIERS = {"Lite": "Free", "Plus": "Free", "Legend": "Paid", "Ninja": "Paid"}
MODES       = ["build", "production"]
MTK_MAX_DEVICES  = 2
SNAP_MAX_DEVICES = 4


# ─────────────────────────────────────────────────────────────────────────────
# Token helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_github_token() -> str:
    """Return GitHub token from env: G_TOKEN > GITHUB_TOKEN > GH_TOKEN."""
    for var in ("G_TOKEN", "GITHUB_TOKEN", "GH_TOKEN"):
        val = os.environ.get(var, "").strip()
        if val:
            return val
    return ""


def get_telegram_token() -> str:
    """Return Telegram bot token from env: BOT_TOKEN > TELEGRAM_BOT_TOKEN."""
    for var in ("BOT_TOKEN", "TELEGRAM_BOT_TOKEN"):
        val = os.environ.get(var, "").strip()
        if val:
            return val
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# SoC / workflow helpers
# ─────────────────────────────────────────────────────────────────────────────

def normalize_soc(soc: str) -> str:
    """Normalize SoC string to canonical 'mtk' or 'snap'."""
    s = soc.lower().strip()
    if s in ("mtk", "mediatek"):
        return "mtk"
    if s in ("snap", "snapdragon"):
        return "snap"
    raise ValueError(f"Unknown SoC type: {soc!r}")


def get_workflow_file(soc: str, backend: str) -> str:
    """Return the exact workflow filename. Raises ValueError for unknown combinations."""
    norm = normalize_soc(soc)
    key  = (norm, backend.lower())
    wf   = WORKFLOW_MAP.get(key)
    if not wf:
        raise ValueError(
            f"No workflow mapping for soc={soc!r}, backend={backend!r}. "
            f"Known: {list(WORKFLOW_MAP.keys())}"
        )
    return wf


def build_workflow_inputs(config: dict, soc: str, backend: str) -> dict:
    """
    Build the inputs payload for workflow dispatch.
    Fly workflows do NOT accept 'devices' — the pipeline auto-detects from ROM URL.
    allow_oversized_final is always 'true' because MEZO final ZIPs are large.
    """
    norm      = normalize_soc(soc)
    vm_cpus   = "8"     if config.get("ram") == "64" else "16"
    vm_memory = "65536" if config.get("ram") == "64" else "131072"

    inputs: dict = {
        "rom_url":               config["rom_url"],
        "style":                 config.get("style", "Plus"),
        "mode":                  config.get("mode",  "build"),
        "upload_pixeldrain":     str(config.get("upload_pixeldrain", False)).lower(),
        "notify_telegram":       "true",
        "allow_oversized_final": "true",
        "VM_CPUS":               vm_cpus,
        "VM_MEMORY":             vm_memory,
    }

    # Snapdragon Fly workflow requires server_id to select the builder instance
    if norm == "snap" and backend.lower() == "fly":
        inputs["server_id"] = str(config.get("snap_servers", "1"))

    return inputs


# ─────────────────────────────────────────────────────────────────────────────
# GitHub API helpers
# ─────────────────────────────────────────────────────────────────────────────

def _github_headers(token: str) -> dict:
    return {
        "Authorization":        f"Bearer {token}",
        "Accept":               "application/vnd.github+json",
        "Content-Type":         "application/json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def github_get_workflow(workflow_file: str) -> tuple:
    """
    Check that the workflow file exists on the target repo.
    Returns (exists: bool, response_body: dict).
    """
    token = get_github_token()
    if not token:
        return False, {"error": "GitHub token missing"}
    url = (
        f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}"
        f"/actions/workflows/{workflow_file}"
    )
    try:
        resp = requests.get(url, headers=_github_headers(token), timeout=30)
        body: dict = {}
        try:
            body = resp.json()
        except Exception:
            pass
        return resp.status_code == 200, body
    except requests.exceptions.RequestException as exc:
        return False, {"error": str(exc)}


def github_dispatch_workflow(workflow_file: str, inputs: dict) -> tuple:
    """
    POST a workflow_dispatch event to GitHub Actions API.
    Returns (status_code: int, response_body: dict).
    204 = success; anything else = failure.
    """
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
        resp = requests.post(
            url,
            headers=_github_headers(token),
            json=payload,
            timeout=30,
        )
        body: dict = {}
        try:
            body = resp.json()
        except Exception:
            pass
        return resp.status_code, body
    except requests.exceptions.RequestException as exc:
        return 0, {"error": str(exc)}


def format_github_error(status_code: int, response_body: dict, workflow_file: str) -> str:
    """Build a safe, informative Telegram error message (no secrets exposed)."""
    hints = {
        0:   "Network error — check bot connectivity.",
        401: "Token is invalid or expired.",
        403: "Token lacks 'workflow' or 'actions' permission.",
        404: "Workflow file not found, or repo access is denied.",
        422: "Invalid workflow inputs, or ref does not exist.",
    }
    hint     = hints.get(status_code, "Unexpected error — check token and repository config.")
    body_str = json.dumps(response_body, indent=2)[:400] if response_body else "(empty)"

    return (
        f"*Failed to trigger workflow.*\n\n"
        f"Repository: `{REPO_OWNER}/{REPO_NAME}`\n"
        f"Workflow: `{workflow_file}`\n"
        f"Ref: `{REPO_REF}`\n"
        f"HTTP: `{status_code}`\n\n"
        f"*GitHub response:*\n```{body_str}```\n\n"
        f"*Hint:* {hint}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Auth / detection helpers
# ─────────────────────────────────────────────────────────────────────────────

def is_dev(user_id: int) -> bool:
    return user_id in DEV_IDS


def is_authorized_chat(message) -> bool:
    return is_dev(message.from_user.id if message.from_user else 0)


def detect_soc(chat_id: int, args=None):
    if args:
        arg = args.lower().strip()
        if arg in ("mtk", "mediatek"):
            return "mtk"
        if arg in ("snap", "snapdragon"):
            return "snap"
    if chat_id == MTK_GROUP_ID:
        return "mtk"
    if chat_id == SNAP_GROUP_ID:
        return "snap"
    return None


def get_devices(soc: str) -> list:
    return MTK_DEVICES if soc == "mtk" else SNAPDRAGON_DEVICES


def get_soc_label(soc: str) -> str:
    return "MediaTek" if soc == "mtk" else "Snapdragon"


def get_max_devices(soc: str) -> int:
    return MTK_MAX_DEVICES if soc == "mtk" else SNAP_MAX_DEVICES


def init_config(user_id: int, soc: str) -> None:
    user_config[user_id] = {
        "soc":               soc,
        "selected_devices":  [],
        "style":             STYLES[0],
        "style_idx":         0,
        "mode":              MODES[0],
        "mode_idx":          0,
        "ram":               "64",
        "upload_pixeldrain": False,
        "custom_codename":   "",
        "rom_url":           "",
        "snap_servers":      "1",
    }


def extract_soc(data: str, user_id: int) -> str:
    parts = data.split(":")
    if len(parts) >= 3:
        return parts[2]
    if len(parts) >= 2 and parts[1] in ("mtk", "snap"):
        return parts[1]
    if user_id in user_config:
        return user_config[user_id].get("soc", "mtk")
    return "mtk"


# ─────────────────────────────────────────────────────────────────────────────
# UI helpers
# ─────────────────────────────────────────────────────────────────────────────

def send_soc_choice(chat_id: int, message_id=None) -> None:
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("MediaTek (MTK)", callback_data="soc:mtk"),
        InlineKeyboardButton("Snapdragon",     callback_data="soc:snap"),
    )
    text = "*Welcome to MEZO Cloud Builder!*\n\nChoose your SoC type:"
    if message_id:
        bot.edit_message_text(
            text, chat_id=chat_id, message_id=message_id,
            reply_markup=markup, parse_mode="Markdown",
        )
    else:
        bot.send_message(chat_id, text, reply_markup=markup, parse_mode="Markdown")


@bot.message_handler(commands=["start", "build"])
def start_menu(message) -> None:
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else 0

    if not is_authorized_chat(message):
        bot.send_message(
            chat_id,
            "*This bot is restricted to MEZO developers only.*",
            parse_mode="Markdown",
        )
        return

    parts = message.text.split()
    args  = parts[1] if len(parts) > 1 else None

    soc = detect_soc(chat_id, args)
    if soc is None:
        send_soc_choice(chat_id)
        return

    init_config(user_id, soc)
    send_config_menu(user_id, chat_id=chat_id)


def send_config_menu(user_id: int, chat_id=None, message_id=None) -> None:
    if chat_id is None:
        chat_id = user_id
    if user_id not in user_config:
        send_soc_choice(chat_id)
        return

    config  = user_config[user_id]
    soc     = config["soc"]
    markup  = InlineKeyboardMarkup()
    max_dev = get_max_devices(soc)

    dev_text = f"Devices ({len(config['selected_devices'])}/{max_dev})"
    markup.row(InlineKeyboardButton(dev_text, callback_data=f"show_devices:{soc}"))

    rom_raw     = config["rom_url"]
    rom_display = rom_raw[:30] + "..." if len(rom_raw) > 30 else rom_raw
    rom_text    = f"ROM: {rom_display}" if rom_raw else "Set ROM URL"
    markup.row(InlineKeyboardButton(rom_text, callback_data=f"set_rom_url:{soc}"))

    markup.row(
        InlineKeyboardButton(f"Style: {config['style']}", callback_data=f"cycle_style:{soc}"),
        InlineKeyboardButton(f"Mode: {config['mode']}",   callback_data=f"cycle_mode:{soc}"),
    )
    markup.row(
        InlineKeyboardButton(
            f"RAM: {config['ram']}GB", callback_data=f"toggle_ram:{soc}"
        ),
        InlineKeyboardButton(
            "PixelDrain: ON" if config["upload_pixeldrain"] else "PixelDrain: OFF",
            callback_data=f"toggle_upload:{soc}",
        ),
    )

    if soc == "snap":
        markup.row(InlineKeyboardButton(
            f"Server: {config.get('snap_servers', '1')}",
            callback_data=f"toggle_servers:{soc}",
        ))

    markup.row(InlineKeyboardButton("Set Custom Device", callback_data=f"set_custom:{soc}"))
    markup.row(InlineKeyboardButton("Switch SoC",        callback_data="choose_soc"))
    markup.row(InlineKeyboardButton("START BUILD",       callback_data=f"start_build:{soc}"))

    cores         = "8" if config["ram"] == "64" else "16"
    upload_status = "Enabled" if config["upload_pixeldrain"] else "Disabled"
    custom_info   = f"\n*Custom:* `{config['custom_codename']}`" if config["custom_codename"] else ""
    rom_info      = f"\n*ROM:* `{rom_raw}`" if rom_raw else "\n*ROM:* not set"
    srv_info      = f"\n*Server:* {config.get('snap_servers', '1')}" if soc == "snap" else ""
    style_tier    = STYLE_TIERS.get(config["style"], "Free")
    backend_label = "Fly.io" if BUILD_BACKEND == "fly" else "GitHub Actions"

    text = (
        f"*MEZO {get_soc_label(soc)} Cloud Builder* ({backend_label})\n\n"
        f"*Devices:* `{', '.join(config['selected_devices']) or 'None'}`"
        f"{custom_info}\n"
        f"*Style:* {config['style']} ({style_tier})\n"
        f"*Mode:* {config['mode']}\n"
        f"*PixelDrain:* {upload_status}\n"
        f"*RAM:* {config['ram']}GB ({cores} Cores)"
        f"{srv_info}"
        f"\n*SoC:* {get_soc_label(soc)}"
        f"{rom_info}"
    )

    if message_id:
        bot.edit_message_text(
            text, chat_id=chat_id, message_id=message_id,
            reply_markup=markup, parse_mode="Markdown",
            disable_web_page_preview=True,
        )
    else:
        bot.send_message(
            chat_id, text, reply_markup=markup,
            parse_mode="Markdown", disable_web_page_preview=True,
        )


def send_device_list(user_id: int, chat_id=None, page: int = 0, message_id=None) -> None:
    if chat_id is None:
        chat_id = user_id
    if user_id not in user_config:
        return

    config      = user_config[user_id]
    soc         = config["soc"]
    devices     = get_devices(soc)
    max_dev     = get_max_devices(soc)
    markup      = InlineKeyboardMarkup()
    total_pages = (len(devices) + DEVICES_PER_PAGE - 1) // DEVICES_PER_PAGE
    start       = page * DEVICES_PER_PAGE
    page_devs   = devices[start : start + DEVICES_PER_PAGE]

    for dev in page_devs:
        checked = "[x] " if dev in config["selected_devices"] else "[ ] "
        markup.row(InlineKeyboardButton(
            f"{checked}{dev}", callback_data=f"toggle_dev:{dev}:{soc}"
        ))

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("Prev", callback_data=f"devp:{page - 1}:{soc}"))
    nav.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next", callback_data=f"devp:{page + 1}:{soc}"))
    markup.row(*nav)
    markup.row(InlineKeyboardButton("Back", callback_data=f"back_menu:{soc}"))

    selected = config["selected_devices"]
    text     = f"*Select Devices (max {max_dev}):*\nTap to toggle. Selected: {len(selected)}/{max_dev}"
    if selected:
        text += f"\n`{', '.join(selected)}`"

    if message_id:
        bot.edit_message_text(
            text, chat_id=chat_id, message_id=message_id,
            reply_markup=markup, parse_mode="Markdown",
        )
    else:
        bot.send_message(chat_id, text, reply_markup=markup, parse_mode="Markdown")


# ─────────────────────────────────────────────────────────────────────────────
# Build trigger
# ─────────────────────────────────────────────────────────────────────────────

def trigger_build(call, soc: str) -> None:
    user_id = call.from_user.id
    chat_id = call.message.chat.id

    if user_id not in user_config:
        return

    config = user_config[user_id]

    if not config.get("rom_url"):
        bot.answer_callback_query(call.id, "Please set a ROM URL first!", show_alert=True)
        return

    # Validate GitHub token before any API call
    token = get_github_token()
    if not token:
        bot.answer_callback_query(call.id, "GitHub token missing!", show_alert=True)
        bot.send_message(
            chat_id,
            "*GitHub token is missing.*\n"
            "Set `G_TOKEN`, `GITHUB_TOKEN`, or `GH_TOKEN` in the bot environment.",
            parse_mode="Markdown",
        )
        return

    # Resolve workflow file via explicit mapping
    try:
        workflow_file = get_workflow_file(soc, BUILD_BACKEND)
    except ValueError as exc:
        bot.answer_callback_query(call.id, "Unknown SoC/backend!", show_alert=True)
        bot.send_message(chat_id, f"Config error: {exc}")
        log.error("Workflow mapping failed: soc=%s backend=%s error=%s", soc, BUILD_BACKEND, exc)
        return

    # Build inputs — no 'devices', allow_oversized_final always "true"
    inputs = build_workflow_inputs(config, soc, BUILD_BACKEND)

    label         = get_soc_label(soc)
    backend_label = "Fly.io" if BUILD_BACKEND == "fly" else "GitHub Actions"

    log.info(
        "Dispatching %s | workflow=%s backend=%s inputs=%s",
        label, workflow_file, BUILD_BACKEND, inputs,
    )

    status_msg = bot.send_message(
        chat_id,
        f"*Initializing {label} Build...*\n"
        f"Workflow: `{workflow_file}`\n"
        f"Backend: {backend_label}",
        parse_mode="Markdown",
    )

    status_code, response_body = github_dispatch_workflow(workflow_file, inputs)

    if status_code == 204:
        pd_status   = "enabled" if inputs.get("upload_pixeldrain") == "true" else "disabled"
        server_line = f"\nServer ID: `{inputs['server_id']}`" if "server_id" in inputs else ""
        success_text = (
            f"*Workflow triggered successfully.*\n\n"
            f"Repository: `{REPO_OWNER}/{REPO_NAME}`\n"
            f"Workflow: `{workflow_file}`\n"
            f"Ref: `{REPO_REF}`\n"
            f"Style: `{inputs['style']}`\n"
            f"Mode: `{inputs['mode']}`\n"
            f"PixelDrain: `{pd_status}`\n"
            f"Backend: `{backend_label}`"
            f"{server_line}\n\n"
            f"Waking up {backend_label} server..."
        )
        bot.answer_callback_query(call.id, f"{label} build triggered!", show_alert=True)
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=status_msg.message_id,
            text=success_text,
            parse_mode="Markdown",
        )
        log.info(
            "Dispatch OK: workflow=%s style=%s mode=%s",
            workflow_file, inputs["style"], inputs["mode"],
        )
    else:
        error_text = format_github_error(status_code, response_body, workflow_file)
        bot.answer_callback_query(call.id, "Failed to trigger workflow!", show_alert=True)
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=status_msg.message_id,
            text=error_text,
            parse_mode="Markdown",
        )
        log.error(
            "Dispatch FAILED: workflow=%s repo=%s/%s ref=%s status=%s response=%s",
            workflow_file, REPO_OWNER, REPO_NAME, REPO_REF,
            status_code, response_body,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Input step handlers
# ─────────────────────────────────────────────────────────────────────────────

def process_rom_url(message, soc: str) -> None:
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else 0
    if not is_dev(user_id) or user_id not in user_config:
        return
    url = message.text.strip()
    if not url:
        bot.send_message(chat_id, "Empty URL. Try again.")
        return
    user_config[user_id]["rom_url"] = url
    bot.send_message(chat_id, f"ROM URL set:\n`{url}`", parse_mode="Markdown")
    send_config_menu(user_id, chat_id=chat_id)


def process_custom_codename(message, soc: str) -> None:
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else 0
    if not is_dev(user_id) or user_id not in user_config:
        return
    codename = message.text.strip().lower().replace(" ", "")
    if not codename:
        bot.send_message(chat_id, "Empty codename. Try again.")
        return
    user_config[user_id]["custom_codename"] = codename
    send_config_menu(user_id, chat_id=chat_id)


# ─────────────────────────────────────────────────────────────────────────────
# Callback query handler
# ─────────────────────────────────────────────────────────────────────────────

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call) -> None:
    user_id = call.from_user.id
    chat_id = call.message.chat.id

    if not is_dev(user_id):
        bot.answer_callback_query(call.id, "Unauthorized interaction!", show_alert=True)
        return

    data = call.data

    if data == "choose_soc":
        send_soc_choice(chat_id, message_id=call.message.message_id)
        bot.answer_callback_query(call.id)
        return

    if data == "noop":
        bot.answer_callback_query(call.id)
        return

    if data.startswith("soc:"):
        soc = data.split(":", 1)[1]
        if soc not in ("mtk", "snap"):
            return
        init_config(user_id, soc)
        send_config_menu(user_id, chat_id=chat_id, message_id=call.message.message_id)
        bot.answer_callback_query(call.id)
        return

    soc    = extract_soc(data, user_id)
    action = data.split(":")[0]

    if user_id not in user_config:
        init_config(user_id, soc)

    cfg = user_config[user_id]

    if action == "show_devices":
        send_device_list(user_id, chat_id=chat_id, page=0, message_id=call.message.message_id)

    elif action == "devp":
        parts = data.split(":")
        page  = int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else 0
        send_device_list(user_id, chat_id=chat_id, page=page, message_id=call.message.message_id)

    elif action == "toggle_dev":
        parts   = data.split(":")
        dev     = parts[1] if len(parts) >= 2 else ""
        max_dev = get_max_devices(cfg["soc"])
        if dev in cfg["selected_devices"]:
            cfg["selected_devices"].remove(dev)
        elif len(cfg["selected_devices"]) < max_dev:
            cfg["selected_devices"].append(dev)
        else:
            bot.answer_callback_query(call.id, f"Max {max_dev} devices allowed!", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        send_device_list(user_id, chat_id=chat_id, message_id=call.message.message_id)
        return

    elif action == "back_menu":
        send_config_menu(user_id, chat_id=chat_id, message_id=call.message.message_id)

    elif action == "set_rom_url":
        msg = bot.send_message(chat_id, "Send the ROM download URL:")
        bot.register_next_step_handler(msg, lambda m: process_rom_url(m, soc))

    elif action == "cycle_style":
        cfg["style_idx"] = (cfg["style_idx"] + 1) % len(STYLES)
        cfg["style"]     = STYLES[cfg["style_idx"]]
        send_config_menu(user_id, chat_id=chat_id, message_id=call.message.message_id)

    elif action == "cycle_mode":
        cfg["mode_idx"] = (cfg["mode_idx"] + 1) % len(MODES)
        cfg["mode"]     = MODES[cfg["mode_idx"]]
        send_config_menu(user_id, chat_id=chat_id, message_id=call.message.message_id)

    elif action == "toggle_ram":
        cfg["ram"] = "128" if cfg["ram"] == "64" else "64"
        send_config_menu(user_id, chat_id=chat_id, message_id=call.message.message_id)

    elif action == "toggle_upload":
        cfg["upload_pixeldrain"] = not cfg["upload_pixeldrain"]
        send_config_menu(user_id, chat_id=chat_id, message_id=call.message.message_id)

    elif action == "toggle_servers":
        cfg["snap_servers"] = "2" if cfg.get("snap_servers", "1") == "1" else "1"
        send_config_menu(user_id, chat_id=chat_id, message_id=call.message.message_id)

    elif action == "set_custom":
        msg = bot.send_message(chat_id, "Send the custom device codename:")
        bot.register_next_step_handler(msg, lambda m: process_custom_codename(m, soc))

    elif action == "start_build":
        trigger_build(call, soc)
        return

    bot.answer_callback_query(call.id)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    gh_token = get_github_token()
    if not gh_token:
        log.warning("No GitHub token found. Set G_TOKEN, GITHUB_TOKEN, or GH_TOKEN.")
    else:
        log.info("GitHub token loaded (length=%d)", len(gh_token))

    log.info("Build backend  : %s", BUILD_BACKEND)
    log.info("Repository     : %s/%s @ %s", REPO_OWNER, REPO_NAME, REPO_REF)
    log.info("Developer IDs  : %s", DEV_IDS)
    log.info("Starting MEZO bot (polling)...")

    bot.infinity_polling()
