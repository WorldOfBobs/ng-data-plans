"""
FX Bob — Multi-Country Parallel FX Rate Tracker
Telegram Bot

Features:
  - Multi-country (Nigeria, Ghana, Kenya, South Africa)
  - Country picker on /start (global bot)
  - Live rates from multiple sources per currency pair
  - Spike alerts, daily briefing, proactive interval push
  - Reply keyboard: Rate / History / Settings / Feedback
  - Inline "Send money" buttons on rate output (Wise / Remitly)
  - /feedback command → forwards to FEEDBACK_CHAT_ID

Run: python bot.py
"""
import asyncio
import logging
import os
from datetime import datetime, time

from dotenv import load_dotenv
from telegram import (
    Update, ChatMemberUpdated,
    InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton,
)
from telegram.ext import (
    Application, CommandHandler, ContextTypes,
    ChatMemberHandler, CallbackQueryHandler,
    MessageHandler, filters,
)

import db
import scraper
import chart

# DATA_DIR allows running multiple instances from one codebase.
DATA_DIR = os.environ.get("DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(DATA_DIR, ".env"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BOT_TOKEN           = os.environ["BOT_TOKEN"]
POLL_INTERVAL       = int(os.getenv("POLL_INTERVAL_SECONDS", "900"))
DAILY_BRIEFING_HOUR = int(os.getenv("DAILY_BRIEFING_HOUR", "7"))  # 7 UTC = 8am Lagos

# "ALL" = show country picker on /start; a country code = skip straight there
DEFAULT_COUNTRY = os.getenv("DEFAULT_COUNTRY", "NG").upper()

# Where to send user feedback (Telegram chat/user ID)
# Get your own ID by messaging @userinfobot on Telegram
FEEDBACK_CHAT_ID = os.getenv("FEEDBACK_CHAT_ID", "")

# ──────────────────────────────────────────────
# Region + Country config
# ──────────────────────────────────────────────

REGION_CONFIG = {
    "AF_EU": {"name": "Europe & Africa",   "flag": "🌍"},
    "AM":    {"name": "N. & S. America",   "flag": "🌎"},
    "AS_AU": {"name": "Asia & Australia",  "flag": "🌏"},
}

COUNTRY_CONFIG = {
    # Europe & Africa — live
    "NG": {"name": "Nigeria",        "flag": "🇳🇬", "currency": "NGN", "region": "AF_EU", "live": True},
    "GH": {"name": "Ghana",          "flag": "🇬🇭", "currency": "GHS", "region": "AF_EU", "live": True},
    "KE": {"name": "Kenya",          "flag": "🇰🇪", "currency": "KES", "region": "AF_EU", "live": True},
    "ZA": {"name": "South Africa",   "flag": "🇿🇦", "currency": "ZAR", "region": "AF_EU", "live": True},
    # Europe & Africa — coming soon
    "EG": {"name": "Egypt",          "flag": "🇪🇬", "currency": "EGP", "region": "AF_EU", "live": False},
    "ET": {"name": "Ethiopia",       "flag": "🇪🇹", "currency": "ETB", "region": "AF_EU", "live": False},
    "TZ": {"name": "Tanzania",       "flag": "🇹🇿", "currency": "TZS", "region": "AF_EU", "live": False},
    "UG": {"name": "Uganda",         "flag": "🇺🇬", "currency": "UGX", "region": "AF_EU", "live": False},
    "GB": {"name": "United Kingdom", "flag": "🇬🇧", "currency": "GBP", "region": "AF_EU", "live": False},
    # N. & S. America — coming soon
    "MX": {"name": "Mexico",         "flag": "🇲🇽", "currency": "MXN", "region": "AM",    "live": False},
    "BR": {"name": "Brazil",         "flag": "🇧🇷", "currency": "BRL", "region": "AM",    "live": False},
    "CO": {"name": "Colombia",       "flag": "🇨🇴", "currency": "COP", "region": "AM",    "live": False},
    "DO": {"name": "Dominican Rep.", "flag": "🇩🇴", "currency": "DOP", "region": "AM",    "live": False},
    # Asia & Australia — coming soon
    "IN": {"name": "India",          "flag": "🇮🇳", "currency": "INR", "region": "AS_AU", "live": False},
    "PH": {"name": "Philippines",    "flag": "🇵🇭", "currency": "PHP", "region": "AS_AU", "live": False},
    "PK": {"name": "Pakistan",       "flag": "🇵🇰", "currency": "PKR", "region": "AS_AU", "live": False},
    "AU": {"name": "Australia",      "flag": "🇦🇺", "currency": "AUD", "region": "AS_AU", "live": False},
}

# Only live countries can be selected
LIVE_COUNTRIES = {k: v for k, v in COUNTRY_CONFIG.items() if v["live"]}

def get_country(code: str) -> dict:
    return COUNTRY_CONFIG.get(code, COUNTRY_CONFIG["NG"])

def user_country_code(sub: dict | None) -> str:
    if DEFAULT_COUNTRY != "ALL":
        return DEFAULT_COUNTRY
    if sub and sub.get("country"):
        return sub["country"]
    return "NG"

# ──────────────────────────────────────────────
# Keyboards
# ──────────────────────────────────────────────

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("💱 Rate"),    KeyboardButton("📊 History")],
        [KeyboardButton("⚙️ Settings"), KeyboardButton("💬 Feedback")],
    ],
    resize_keyboard=True,
    is_persistent=True,
)

def _region_keyboard():
    """Level 1: 3 region buttons."""
    rows = [
        [InlineKeyboardButton(f"{cfg['flag']} {cfg['name']}", callback_data=f"region:{code}")]
        for code, cfg in REGION_CONFIG.items()
    ]
    return InlineKeyboardMarkup(rows)

def _country_keyboard(region_code: str):
    """Level 2: country buttons for a region."""
    buttons = []
    for code, cfg in COUNTRY_CONFIG.items():
        if cfg["region"] != region_code:
            continue
        if cfg["live"]:
            buttons.append(InlineKeyboardButton(
                f"{cfg['flag']} {cfg['name']}", callback_data=f"country:{code}"
            ))
        else:
            buttons.append(InlineKeyboardButton(
                f"{cfg['flag']} {cfg['name']} ·soon", callback_data="noop"
            ))
    rows = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton("← Back", callback_data="picker:start")])
    return InlineKeyboardMarkup(rows)



# ──────────────────────────────────────────────
# Formatting helpers
# ──────────────────────────────────────────────

FOREIGN_FLAGS = {"USD": "🇺🇸", "GBP": "🇬🇧", "EUR": "🇪🇺"}

def local_currency_symbol(local: str) -> str:
    return {"NGN": "₦", "GHS": "₵", "KES": "KSh", "ZAR": "R", "EGP": "£"}.get(local, local + " ")

def format_rate(r: dict, foreign="USD", local="NGN") -> str:
    fflag = FOREIGN_FLAGS.get(foreign, "💵")
    sym   = local_currency_symbol(local)
    spread = r.get("spread", r.get("parallel_rate", 0) - r.get("cbn_rate", 0))
    spread_pct = r.get("spread_pct", 0)
    spread_emoji = "🟢" if spread_pct < 5 else "🟡" if spread_pct < 15 else "🔴"
    ts = r.get("fetched_at", "")[:16] or datetime.utcnow().strftime("%Y-%m-%d %H:%M")

    official_label = "CBN Official" if local == "NGN" else "Official Rate"
    parallel_label = "Parallel Market" if local in ("NGN", "GHS") else "Street/Market"

    lines = [
        f"{fflag} *{foreign}/{local} Rate* {spread_emoji}",
        "",
        f"🏦 {official_label}:    {sym}{r['cbn_rate']:,.2f}",
        f"🏪 {parallel_label}: {sym}{r['parallel_rate']:,.2f}",
        f"📊 Spread:             {sym}{spread:,.2f} ({spread_pct:.1f}%)",
    ]

    sources = r.get("display_sources") or r.get("sources")
    if sources:
        # Sort: parallel first, official second, remittance (Wise/Remitly) last
        KIND_ORDER = {"parallel": 0, "official": 1, "remittance": 2}
        sources = sorted(sources, key=lambda s: KIND_ORDER.get(s.get("kind", ""), 1))
        lines.append("")
        lines.append("📡 *Sources:*")
        has_outlier = False
        KIND_LABEL = {"parallel": "P2P/market", "official": "official", "remittance": "diaspora send"}
        for s in sources:
            kind = KIND_LABEL.get(s.get("kind", ""), "")
            tag  = f" _[{kind}]_" if kind else ""
            if s["rate"] is None:
                reason = s.get("err_reason")
                if reason:
                    lines.append(f"  🔒 {s['name']}{tag}: _{reason}_")
                else:
                    lines.append(f"  ❌ {s['name']}{tag}: _no data right now_")
            elif s.get("status") == "outlier" or s.get("reliable") is False:
                dev = s.get("deviation_pct") or 0
                lines.append(f"  ⚠️ {s['name']}{tag}: {sym}{s['rate']:,.0f} _({dev:.0f}% off median — excluded)_")
                has_outlier = True
            else:
                lines.append(f"  ✅ {s['name']}{tag}: {sym}{s['rate']:,.0f}")

        if r.get("is_mock"):
            lines.append("")
            lines.append("⚠️ _All live sources down — showing estimated data_")
        elif has_outlier:
            lines.append("")
            lines.append("⚠️ _Outlier sources excluded from consensus rate_")

    lines.append("")
    lines.append(f"🕐 {ts} UTC")

    return "\n".join(lines)

def format_briefing(foreign="USD", local="NGN") -> str:
    r = db.get_latest_rate(foreign, local)
    history = db.get_daily_history(7, foreign, local)
    fflag = FOREIGN_FLAGS.get(foreign, "💵")
    sym   = local_currency_symbol(local)
    today = datetime.utcnow().strftime("%A, %d %b %Y")

    if not r:
        return f"{fflag} *{foreign}/{local} Morning Brief* — {today}\n\n_No data yet — check back after the first poll._"

    trend = ""
    if len(history) >= 2:
        pct = (r["parallel_rate"] - history[0]["avg"]) / history[0]["avg"] * 100
        trend = f"📅 vs 7 days ago: {'📈' if pct > 0 else '📉'} {abs(pct):.1f}%\n"

    return (
        f"{fflag} *{foreign}/{local} Morning Brief* — {today}\n\n"
        f"🏦 Official:  {sym}{r['cbn_rate']:,.2f}\n"
        f"🏪 Market:    {sym}{r['parallel_rate']:,.2f}\n"
        f"📊 Spread:   {r['spread_pct']:.1f}%\n"
        f"{trend}\n"
        f"_Use /rate for live update · /history for 7-day trend_"
    )

def format_history(foreign="USD", local="NGN") -> str:
    rows = db.get_daily_history(7, foreign, local)
    fflag = FOREIGN_FLAGS.get(foreign, "💵")
    sym   = local_currency_symbol(local)
    if not rows:
        return "No history yet — check back after a day of polling."
    lines = [f"{fflag} *{foreign}/{local} — Last 7 Days*\n"]
    for r in rows:
        day = r["day"][5:]
        arrow = "📈" if r["high"] > r["avg"] else "📉"
        lines.append(
            f"`{day}` {arrow} High: {sym}{r['high']:,.0f}  Low: {sym}{r['low']:,.0f}  Avg: {sym}{r['avg']:,.0f}"
        )
    return "\n".join(lines)

# ──────────────────────────────────────────────
# /start and subscription
# ──────────────────────────────────────────────

async def _send_welcome(chat_id, user_first_name, country_code, bot):
    """Send the welcome + commands message after country is chosen."""
    c = get_country(country_code)
    await bot.send_message(
        chat_id,
        f"✅ Set to *{c['flag']} {c['name']}*!\n\n"
        f"💱 *FX Bob* tracks the official vs parallel {c['currency']} rate "
        f"and alerts you when it moves.\n\n"
        "━━━━━━━━━━━━━━\n"
        "📌 *Commands:*\n\n"
        "• /rate — Current rate (USD)\n"
        "• /rate GBP · /rate EUR — Other currencies\n"
        "• /history — 7-day trend\n"
        "• /chart — 24-hour chart\n"
        "• /settings — Your settings\n"
        "• /interval — Scheduled push updates\n"
        "• /country — Change your country\n"
        "• /stop — Pause · /subscribe — Resume\n"
        "• /feedback — Send us a suggestion\n\n"
        "━━━━━━━━━━━━━━\n"
        "🔔 Subscribed to rate alerts + daily briefing.\n\n"
        "_Share with anyone who sends or receives money_ 💸",
        reply_markup=MAIN_KEYBOARD,
        parse_mode="Markdown"
    )

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if DEFAULT_COUNTRY == "ALL":
        await update.message.reply_text(
            f"👋 Welcome, {user.first_name}!\n\n"
            "I track the *official vs parallel FX rate* for your country — "
            "and alert you when it moves.\n\n"
            "*Pick your region to get started:*",
            reply_markup=_region_keyboard(),
            parse_mode="Markdown"
        )
    else:
        db.add_subscriber(user.id, user.username or user.first_name, DEFAULT_COUNTRY)
        await _send_welcome(update.effective_chat.id, user.first_name, DEFAULT_COUNTRY, ctx.bot)

async def callback_picker(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle inline keyboard taps for region → country selection."""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "noop":
        await query.answer("Coming soon! 🚧", show_alert=True)
        return

    if data == "picker:start":
        await query.edit_message_text(
            "Pick your region:",
            reply_markup=_region_keyboard(),
            parse_mode="Markdown"
        )
        return

    if data.startswith("region:"):
        region_code = data.split(":")[1]
        cfg = REGION_CONFIG.get(region_code, {})
        await query.edit_message_text(
            f"{cfg.get('flag','🌍')} *{cfg.get('name','Region')}* — pick your country:",
            reply_markup=_country_keyboard(region_code),
            parse_mode="Markdown"
        )
        return

    if data.startswith("country:"):
        country_code = data.split(":")[1]
        user = query.from_user
        db.add_subscriber(user.id, user.username or user.first_name, country_code)
        await query.delete_message()
        await _send_welcome(update.effective_chat.id, user.first_name, country_code, ctx.bot)
        return

async def cmd_country(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Let the user switch countries at any time."""
    if DEFAULT_COUNTRY != "ALL":
        c = get_country(DEFAULT_COUNTRY)
        await update.message.reply_text(
            f"This bot is fixed to {c['flag']} *{c['name']}*.",
            parse_mode="Markdown"
        )
        return
    await update.message.reply_text(
        "🌍 *Change your country:*\n\nPick your region:",
        reply_markup=_region_keyboard(),
        parse_mode="Markdown"
    )

async def cmd_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    db.remove_subscriber(update.effective_user.id)
    await update.message.reply_text(
        "🔕 Alerts paused. Your settings are saved.\n\nUse /subscribe to turn them back on anytime.",
        reply_markup=MAIN_KEYBOARD,
    )

async def cmd_subscribe(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    sub  = db.get_subscriber(user.id)
    country = user_country_code(sub) if sub else DEFAULT_COUNTRY if DEFAULT_COUNTRY != "ALL" else "NG"
    db.add_subscriber(user.id, user.username or user.first_name, country)
    sub = db.get_subscriber(user.id)
    threshold = sub["alert_threshold_pct"] if sub else 2.0
    direction = sub["alert_direction"] if sub else "both"
    dir_label = {"both": "rises & drops", "up": "rises only", "down": "drops only"}.get(direction, "both")
    await update.message.reply_text(
        f"🔔 Alerts back on!\n\n"
        f"Threshold: {threshold}% · Direction: {dir_label}\n\n"
        f"Use /settings to adjust.",
        reply_markup=MAIN_KEYBOARD,
        parse_mode="Markdown"
    )

# ──────────────────────────────────────────────
# Rate commands
# ──────────────────────────────────────────────

async def cmd_rate(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    sub  = db.get_subscriber(user.id)
    local   = get_country(user_country_code(sub))["currency"]
    foreign = (ctx.args[0].upper() if ctx.args else "USD")

    if foreign not in scraper.SUPPORTED_FOREIGN:
        await update.message.reply_text(
            f"Supported currencies: USD, GBP, EUR\nExample: `/rate GBP`",
            parse_mode="Markdown"
        )
        return

    await update.message.reply_text(f"⏳ Fetching {foreign}/{local}…")
    try:
        rates = await scraper.get_all_sources(foreign, local)
        db.save_rate(rates["cbn_rate"], rates["parallel_rate"], rates.get("source", "multi"), foreign, local)
        rates["fetched_at"] = datetime.utcnow().isoformat()
        await update.message.reply_text(
            format_rate(rates, foreign, local),
            parse_mode="Markdown",
            reply_markup=MAIN_KEYBOARD,
        )
    except Exception as e:
        logger.error(f"Rate fetch error: {e}")
        await update.message.reply_text("❌ Failed to fetch rate. Try again shortly.")

async def cmd_history(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    sub  = db.get_subscriber(user.id)
    local   = get_country(user_country_code(sub))["currency"]
    foreign = (ctx.args[0].upper() if ctx.args else "USD")
    if foreign not in scraper.SUPPORTED_FOREIGN:
        foreign = "USD"
    await update.message.reply_text(format_history(foreign, local), parse_mode="Markdown")

async def cmd_chart(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    sub  = db.get_subscriber(user.id)
    local   = get_country(user_country_code(sub))["currency"]
    foreign = (ctx.args[0].upper() if ctx.args else "USD")
    history = db.get_rate_history(24, foreign, local)
    if not history:
        await update.message.reply_text("No history yet — check back after a few polls!")
        return
    png = chart.matplotlib_chart(history)
    if png:
        await update.message.reply_photo(photo=png, caption=f"📈 {foreign}/{local} — last 24 hours")
    else:
        ascii_c = chart.ascii_chart(history)
        await update.message.reply_text(f"```\n{ascii_c}\n```", parse_mode="Markdown")

# ──────────────────────────────────────────────
# Feedback
# ──────────────────────────────────────────────

async def cmd_feedback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /feedback [message]
    If called with text, forward it immediately.
    If called bare (or via button), prompt the user to type their feedback next.
    """
    user = update.effective_user
    text = " ".join(ctx.args).strip() if ctx.args else ""

    if text:
        await _forward_feedback(user, text, ctx)
    else:
        # Set awaiting state and prompt
        ctx.user_data["awaiting_feedback"] = True
        await update.message.reply_text(
            "💬 *Send your feedback!*\n\n"
            "Type your message and hit send — bug reports, suggestions, anything.\n\n"
            "_(Send /cancel to go back)_",
            parse_mode="Markdown",
        )

async def _forward_feedback(user, text: str, ctx: ContextTypes.DEFAULT_TYPE):
    """Forward feedback text to FEEDBACK_CHAT_ID."""
    handle = f"@{user.username}" if user.username else user.first_name
    full_msg = (
        f"📬 *New Feedback* from {handle} (ID: `{user.id}`)\n\n"
        f"{text}"
    )
    if FEEDBACK_CHAT_ID:
        try:
            await ctx.bot.send_message(FEEDBACK_CHAT_ID, full_msg, parse_mode="Markdown")
            await ctx.bot.send_message(
                user.id,
                "✅ Thanks! Your feedback has been sent.\n\n"
                "We read every message — appreciate you helping make FX Bob better 🙏",
                reply_markup=MAIN_KEYBOARD,
            )
        except Exception as e:
            logger.error(f"Feedback forward failed: {e}")
            await ctx.bot.send_message(
                user.id,
                "❌ Couldn't send feedback right now. Try again later.",
                reply_markup=MAIN_KEYBOARD,
            )
    else:
        logger.info(f"FEEDBACK (no FEEDBACK_CHAT_ID set) from {handle}: {text}")
        await ctx.bot.send_message(
            user.id,
            "✅ Got it! Thanks for the feedback 🙏",
            reply_markup=MAIN_KEYBOARD,
        )

async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Handle reply-keyboard button taps + feedback state.
    """
    text = update.message.text or ""
    user = update.effective_user

    # Feedback state
    if ctx.user_data.get("awaiting_feedback"):
        if text.strip().lower() == "/cancel":
            ctx.user_data["awaiting_feedback"] = False
            await update.message.reply_text("OK, cancelled.", reply_markup=MAIN_KEYBOARD)
            return
        ctx.user_data["awaiting_feedback"] = False
        await _forward_feedback(user, text, ctx)
        return

    # Reply keyboard buttons
    if "Rate" in text:
        ctx.args = []
        await cmd_rate(update, ctx)
    elif "History" in text:
        ctx.args = []
        await cmd_history(update, ctx)
    elif "Settings" in text:
        await cmd_settings(update, ctx)
    elif "Feedback" in text:
        ctx.args = []
        await cmd_feedback(update, ctx)

# ──────────────────────────────────────────────
# Settings
# ──────────────────────────────────────────────

async def cmd_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    sub  = db.get_subscriber(user.id)
    if not sub:
        await update.message.reply_text("You're not subscribed. Send /start to begin.")
        return

    country_code = user_country_code(sub)
    c = get_country(country_code)
    threshold    = sub["alert_threshold_pct"]
    direction    = sub["alert_direction"]
    active       = "🔔 On" if sub["active"] else "🔕 Paused"
    dir_label    = {"both": "rises & drops 📈📉", "up": "rises only 📈", "down": "drops only 📉"}.get(direction, direction)
    interval_min = sub.get("update_interval_min", 0)
    interval_str = (
        "off (alerts only)" if interval_min == 0 else
        f"every {interval_min}m" if interval_min < 60 else
        f"every {interval_min // 60}h" + (f" {interval_min % 60}m" if interval_min % 60 else "")
    )
    country_line = f"Country: *{c['flag']} {c['name']}* ({c['currency']})\n" if DEFAULT_COUNTRY == "ALL" else ""

    await update.message.reply_text(
        f"⚙️ *Your Settings*\n\n"
        f"{country_line}"
        f"Alerts: {active}\n"
        f"Threshold: *{threshold}%* move triggers alert\n"
        f"Direction: *{dir_label}*\n"
        f"Rate updates: *{interval_str}*\n\n"
        f"Commands to change:\n"
        f"`/threshold 3` · `/direction up|down|both`\n"
        f"`/interval 30m|1h|6h|off`"
        + ("\n`/country` — switch country" if DEFAULT_COUNTRY == "ALL" else ""),
        parse_mode="Markdown",
        reply_markup=MAIN_KEYBOARD,
    )

async def cmd_threshold(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: `/threshold 2` (alert on 2% moves)", parse_mode="Markdown")
        return
    try:
        val = float(ctx.args[0])
        assert 0.5 <= val <= 20
    except Exception:
        await update.message.reply_text("Send a number between 0.5 and 20. Example: `/threshold 3`", parse_mode="Markdown")
        return
    db.update_settings(update.effective_user.id, threshold_pct=val)
    await update.message.reply_text(f"✅ Threshold set to *{val}%*", parse_mode="Markdown")

async def cmd_direction(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    valid = {"both", "up", "down"}
    if not ctx.args or ctx.args[0].lower() not in valid:
        await update.message.reply_text("Usage: `/direction both` | `up` | `down`", parse_mode="Markdown")
        return
    val = ctx.args[0].lower()
    db.update_settings(update.effective_user.id, direction=val)
    labels = {"both": "all moves 📈📉", "up": "rises only 📈", "down": "drops only 📉"}
    await update.message.reply_text(f"✅ Alerts set to: *{labels[val]}*", parse_mode="Markdown")

INTERVAL_OPTIONS = {
    "15": 15, "15m": 15, "30": 30, "30m": 30,
    "1h": 60, "60": 60, "2h": 120, "3h": 180,
    "6h": 360, "12h": 720, "off": 0, "0": 0,
}

async def cmd_interval(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text(
            "⏱ *Proactive Rate Updates*\n\n"
            "Get the rate pushed to you at a set interval.\n\n"
            "`/interval 15m` · `30m` · `1h` · `2h` · `6h` · `12h` · `off`\n\n"
            "_Spike alerts always fire regardless of interval._",
            parse_mode="Markdown"
        )
        return
    key = ctx.args[0].lower().strip()
    if key not in INTERVAL_OPTIONS:
        await update.message.reply_text("❌ Try: `15m`, `30m`, `1h`, `2h`, `6h`, `12h`, or `off`", parse_mode="Markdown")
        return
    minutes = INTERVAL_OPTIONS[key]
    db.update_settings(update.effective_user.id, update_interval_min=minutes)
    if minutes == 0:
        await update.message.reply_text("✅ Proactive updates *off*. Spike alerts still fire.", parse_mode="Markdown")
    else:
        hrs, mins = minutes // 60, minutes % 60
        freq = f"{hrs}h" if hrs and not mins else f"{mins}m" if not hrs else f"{hrs}h {mins}m"
        await update.message.reply_text(f"✅ Rate pushed every *{freq}*.\n\nSpike alerts fire instantly.", parse_mode="Markdown")

async def cmd_briefing_time(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: `/briefing 7` (7 UTC = 8am Lagos)", parse_mode="Markdown")
        return
    try:
        hour = int(ctx.args[0])
        assert 0 <= hour <= 23
    except Exception:
        await update.message.reply_text("Send an hour 0–23 in UTC. Example: `/briefing 7`", parse_mode="Markdown")
        return
    db.update_settings(update.effective_user.id, briefing_hour=hour)
    await update.message.reply_text(f"✅ Daily briefing set to *{hour}:00 UTC*", parse_mode="Markdown")

# ──────────────────────────────────────────────
# Group mode
# ──────────────────────────────────────────────

async def handle_chat_member(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    result: ChatMemberUpdated = update.my_chat_member
    if not result:
        return
    old_status = result.old_chat_member.status
    new_status = result.new_chat_member.status
    chat       = result.chat

    if new_status in ("member", "administrator") and old_status in ("left", "kicked"):
        db.register_group(chat.id, chat.title or "Unnamed Group", DEFAULT_COUNTRY if DEFAULT_COUNTRY != "ALL" else "NG")
        logger.info(f"Bot added to group: {chat.title} ({chat.id})")
        await ctx.bot.send_message(
            chat.id,
            "👋 *FX Bob is here!*\n\n"
            "I'll post a daily FX briefing each morning.\n\n"
            "• /rate — Current rate\n"
            "• /rate GBP · /rate EUR\n"
            "• /history — 7-day trend",
            parse_mode="Markdown"
        )
    elif new_status in ("left", "kicked"):
        db.deregister_group(chat.id)

# ──────────────────────────────────────────────
# Background jobs
# ──────────────────────────────────────────────

async def job_poll_rates(ctx: ContextTypes.DEFAULT_TYPE):
    """Fetch latest rate, store it, alert subscribers if threshold crossed."""
    try:
        default_local = get_country(DEFAULT_COUNTRY if DEFAULT_COUNTRY != "ALL" else "NG")["currency"]
        prev  = db.get_latest_rate("USD", default_local)
        rates = await scraper.get_all_sources("USD", default_local)
        saved = db.save_rate(rates["cbn_rate"], rates["parallel_rate"], rates.get("source", "multi"), "USD", default_local)
        saved["fetched_at"]      = datetime.utcnow().isoformat()
        saved["display_sources"] = rates.get("display_sources", [])

        if prev:
            change_pct = (saved["parallel_rate"] - prev["parallel_rate"]) / prev["parallel_rate"] * 100
            moved_up   = change_pct > 0
            abs_change = abs(change_pct)
            alert_msg  = (
                f"🚨 *FX Alert!* Rate moved {'📈 UP' if moved_up else '📉 DOWN'} {abs_change:.1f}%\n\n"
                + format_rate(saved, "USD", default_local)
            )
            for sub in db.get_subscribers():
                tid = sub["telegram_id"]
                if abs_change < sub.get("alert_threshold_pct", 2.0):
                    continue
                dir_pref = sub.get("alert_direction", "both")
                if dir_pref == "up" and not moved_up:
                    continue
                if dir_pref == "down" and moved_up:
                    continue
                try:
                    await ctx.bot.send_message(tid, alert_msg, parse_mode="Markdown")
                except Exception as e:
                    logger.warning(f"Alert failed for {tid}: {e}")

        logger.info(f"Poll done. USD/{default_local} parallel: {saved['parallel_rate']:,.2f}")
    except Exception as e:
        logger.error(f"Poll job error: {e}")

async def job_interval_push(ctx: ContextTypes.DEFAULT_TYPE):
    """Push rate update to subscribers whose interval is due."""
    due = db.get_subscribers_due_interval()
    if not due:
        return

    by_currency: dict[str, list] = {}
    for sub in due:
        code  = user_country_code(sub)
        local = get_country(code)["currency"]
        by_currency.setdefault(local, []).append(sub)

    for local, subs in by_currency.items():
        try:
            rates = await scraper.get_all_sources("USD", local)
            rates["fetched_at"] = datetime.utcnow().isoformat()
            msg = "⏱ *Scheduled Rate Update*\n\n" + format_rate(rates, "USD", local)
            for sub in subs:
                try:
                    await ctx.bot.send_message(sub["telegram_id"], msg, parse_mode="Markdown")
                    db.mark_interval_pushed(sub["telegram_id"])
                except Exception as e:
                    logger.warning(f"Interval push failed for {sub['telegram_id']}: {e}")
        except Exception as e:
            logger.error(f"Interval push job error ({local}): {e}")

async def job_daily_briefing(ctx: ContextTypes.DEFAULT_TYPE):
    """Send morning briefing to all active subscribers and groups."""
    logger.info("Sending daily briefings…")

    by_currency: dict[str, list] = {}
    for sub in db.get_subscribers():
        local = get_country(user_country_code(sub))["currency"]
        by_currency.setdefault(local, []).append(sub)

    for local, subs in by_currency.items():
        msg = format_briefing("USD", local)
        for sub in subs:
            try:
                await ctx.bot.send_message(sub["telegram_id"], msg, parse_mode="Markdown")
            except Exception as e:
                logger.warning(f"Briefing failed for {sub['telegram_id']}: {e}")

    for group in db.get_active_groups():
        local = get_country(group.get("country", "NG"))["currency"]
        msg = format_briefing("USD", local)
        try:
            await ctx.bot.send_message(group["chat_id"], msg, parse_mode="Markdown")
        except Exception as e:
            logger.warning(f"Briefing failed for group {group['chat_id']}: {e}")

# ──────────────────────────────────────────────
# Startup
# ──────────────────────────────────────────────

async def post_init(app: Application):
    app.job_queue.run_repeating(job_poll_rates, interval=POLL_INTERVAL, first=10)
    app.job_queue.run_repeating(job_interval_push, interval=300, first=30)
    app.job_queue.run_daily(job_daily_briefing, time=time(hour=DAILY_BRIEFING_HOUR, minute=0))
    logger.info(f"Jobs scheduled: poll every {POLL_INTERVAL}s, interval-push every 5m, briefing at {DAILY_BRIEFING_HOUR}:00 UTC")
    logger.info(f"DEFAULT_COUNTRY={DEFAULT_COUNTRY} | FEEDBACK_CHAT_ID={'set' if FEEDBACK_CHAT_ID else 'NOT SET'}")

def main():
    db.init_db()
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("stop",      cmd_stop))
    app.add_handler(CommandHandler("subscribe", cmd_subscribe))
    app.add_handler(CommandHandler("country",   cmd_country))
    app.add_handler(CommandHandler("rate",      cmd_rate))
    app.add_handler(CommandHandler("history",   cmd_history))
    app.add_handler(CommandHandler("chart",     cmd_chart))
    app.add_handler(CommandHandler("settings",  cmd_settings))
    app.add_handler(CommandHandler("threshold", cmd_threshold))
    app.add_handler(CommandHandler("direction", cmd_direction))
    app.add_handler(CommandHandler("briefing",  cmd_briefing_time))
    app.add_handler(CommandHandler("interval",  cmd_interval))
    app.add_handler(CommandHandler("feedback",  cmd_feedback))

    # Inline keyboard callbacks (country picker)
    app.add_handler(CallbackQueryHandler(callback_picker))

    # Reply keyboard button taps + feedback text collection
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Group events
    app.add_handler(ChatMemberHandler(handle_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))

    logger.info("🚀 FX Bob starting…")
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
