"""
Nigeria Parallel FX Rate Tracker — Telegram Bot
Features: live rates (USD/GBP/EUR), alerts, daily briefing, /history, group mode
Run: python bot.py
"""
import asyncio
import logging
import os
from datetime import datetime, time

from dotenv import load_dotenv
from telegram import Update, ChatMemberUpdated
from telegram.ext import (
    Application, CommandHandler, ContextTypes,
    ChatMemberHandler, filters, MessageHandler,
)

import db
import scraper
import chart

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SECONDS", "900"))   # 15 min
DAILY_BRIEFING_HOUR = int(os.getenv("DAILY_BRIEFING_HOUR", "7"))  # 7 UTC = 8am Lagos WAT

# ──────────────────────────────────────────────
# Formatting helpers
# ──────────────────────────────────────────────

CURRENCY_FLAGS = {"USD": "🇺🇸", "GBP": "🇬🇧", "EUR": "🇪🇺"}

def format_rate(r: dict, currency="USD") -> str:
    flag = CURRENCY_FLAGS.get(currency, "💵")
    spread = r.get("spread", r.get("parallel_rate", 0) - r.get("cbn_rate", 0))
    spread_pct = r.get("spread_pct", 0)
    spread_emoji = "🟢" if spread_pct < 5 else "🟡" if spread_pct < 15 else "🔴"
    ts = r.get("fetched_at", "")[:16] or datetime.utcnow().strftime("%Y-%m-%d %H:%M")

    lines = [
        f"{flag} *{currency}/NGN Rate* {spread_emoji}",
        "",
        f"🏦 CBN Official:    ₦{r['cbn_rate']:,.2f}",
        f"🏪 Parallel Market: ₦{r['parallel_rate']:,.2f}",
        f"📊 Spread:          ₦{spread:,.2f} ({spread_pct:.1f}%)",
    ]

    # Source breakdown
    sources = r.get("display_sources") or r.get("sources")
    if sources:
        lines.append("")
        lines.append("📡 *Sources:*")
        has_outlier = False
        for s in sources:
            if s["rate"] is None:
                lines.append(f"  ⚫ {s['name']}: unavailable")
            elif s.get("status") == "outlier" or s.get("reliable") is False:
                dev = s.get("deviation_pct") or s.get("deviation_pct", 0)
                lines.append(f"  ⚠️ {s['name']}: ₦{s['rate']:,.0f} _({dev:.0f}% off — outlier)_")
                has_outlier = True
            else:
                lines.append(f"  ✅ {s['name']}: ₦{s['rate']:,.0f}")

        if r.get("is_mock"):
            lines.append("")
            lines.append("⚠️ _All live sources down — showing estimated data_")
        elif has_outlier:
            lines.append("")
            lines.append("⚠️ _Outlier sources excluded from consensus rate_")

    lines.append("")
    lines.append(f"🕐 {ts} UTC")
    return "\n".join(lines)

def format_briefing(currency="USD") -> str:
    r = db.get_latest_rate(currency)
    history = db.get_daily_history(7, currency)
    flag = CURRENCY_FLAGS.get(currency, "💵")
    today = datetime.utcnow().strftime("%A, %d %b %Y")

    if not r:
        return f"{flag} *{currency}/NGN Morning Brief* — {today}\n\n_No data yet — check back after the first poll._"

    # Week trend
    trend = ""
    if len(history) >= 2:
        week_start = history[0]["avg"]
        week_now = r["parallel_rate"]
        pct = (week_now - week_start) / week_start * 100
        trend = f"📅 vs 7 days ago: {'📈' if pct > 0 else '📉'} {abs(pct):.1f}%\n"

    return (
        f"{flag} *{currency}/NGN Morning Brief* — {today}\n\n"
        f"🏦 CBN:     ₦{r['cbn_rate']:,.2f}\n"
        f"🏪 Parallel: ₦{r['parallel_rate']:,.2f}\n"
        f"📊 Spread:  {r['spread_pct']:.1f}%\n"
        f"{trend}\n"
        f"_Use /rate for live update · /history for 7-day trend_"
    )

def format_history(currency="USD") -> str:
    rows = db.get_daily_history(7, currency)
    flag = CURRENCY_FLAGS.get(currency, "💵")
    if not rows:
        return "No history yet — check back after a day of polling."
    lines = [f"{flag} *{currency}/NGN — Last 7 Days*\n"]
    for r in rows:
        day = r["day"][5:]  # MM-DD
        arrow = "📈" if r["high"] > r["avg"] else "📉"
        lines.append(
            f"`{day}` {arrow} High: ₦{r['high']:,.0f}  Low: ₦{r['low']:,.0f}  Avg: ₦{r['avg']:,.0f}"
        )
    return "\n".join(lines)

# ──────────────────────────────────────────────
# /start and subscription
# ──────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.add_subscriber(user.id, user.username or user.first_name)
    await update.message.reply_text(
        f"👋 Welcome, {user.first_name}!\n\n"
        "💵 *Nigeria FX Rate Tracker* monitors the USD/NGN rate so you don't have to.\n\n"
        "I track the *CBN official rate* and the *parallel market rate* and alert you "
        "whenever there's a significant move — before the bureaux de change catch up.\n\n"
        "━━━━━━━━━━━━━━\n"
        "📌 *Commands:*\n\n"
        "• /rate — Current USD/NGN rate\n"
        "• /rate GBP — Current GBP/NGN rate\n"
        "• /rate EUR — Current EUR/NGN rate\n"
        "• /history — 7-day rate trend\n"
        "• /chart — 24-hour chart\n"
        "• /settings — Your alert settings\n"
        "• /stop — Pause alerts · /subscribe — Resume\n\n"
        "━━━━━━━━━━━━━━\n"
        "🔔 You're subscribed to rate alerts + a daily 8am briefing.\n\n"
        "_Share with anyone who buys or sells dollars_ 🇳🇬",
        parse_mode="Markdown"
    )

async def cmd_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    db.remove_subscriber(update.effective_user.id)
    await update.message.reply_text(
        "🔕 Alerts paused. Your settings are saved.\n\nUse /subscribe to turn them back on anytime."
    )

async def cmd_subscribe(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.add_subscriber(user.id, user.username or user.first_name)
    sub = db.get_subscriber(user.id)
    threshold = sub["alert_threshold_pct"] if sub else 2.0
    direction = sub["alert_direction"] if sub else "both"
    dir_label = {"both": "rises & drops", "up": "rises only", "down": "drops only"}.get(direction, "both")
    await update.message.reply_text(
        f"🔔 Alerts back on!\n\n"
        f"Threshold: {threshold}% · Direction: {dir_label}\n\n"
        f"Use /settings to adjust.",
        parse_mode="Markdown"
    )

# ──────────────────────────────────────────────
# Rate commands
# ──────────────────────────────────────────────

async def cmd_rate(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    currency = (ctx.args[0].upper() if ctx.args else "USD")
    if currency not in scraper.SUPPORTED_CURRENCIES:
        await update.message.reply_text(f"Supported currencies: USD, GBP, EUR\nExample: `/rate GBP`", parse_mode="Markdown")
        return
    await update.message.reply_text(f"⏳ Fetching {currency}/NGN from all sources...")
    try:
        rates = await scraper.get_all_sources(currency)
        db.save_rate(rates["cbn_rate"], rates["parallel_rate"], rates.get("source", "multi"), currency)
        rates["fetched_at"] = datetime.utcnow().isoformat()
        await update.message.reply_text(format_rate(rates, currency), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Rate fetch error: {e}")
        await update.message.reply_text("❌ Failed to fetch rate. Try again shortly.")

async def cmd_history(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    currency = (ctx.args[0].upper() if ctx.args else "USD")
    if currency not in scraper.SUPPORTED_CURRENCIES:
        currency = "USD"
    await update.message.reply_text(format_history(currency), parse_mode="Markdown")

async def cmd_chart(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    currency = (ctx.args[0].upper() if ctx.args else "USD")
    history = db.get_rate_history(24, currency)
    if not history:
        await update.message.reply_text("No history yet — check back after a few polls!")
        return
    png = chart.matplotlib_chart(history)
    if png:
        await update.message.reply_photo(photo=png, caption=f"📈 {currency}/NGN — last 24 hours")
    else:
        ascii_c = chart.ascii_chart(history)
        await update.message.reply_text(f"```\n{ascii_c}\n```", parse_mode="Markdown")

# ──────────────────────────────────────────────
# Settings
# ──────────────────────────────────────────────

async def cmd_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    sub = db.get_subscriber(user.id)
    if not sub:
        await update.message.reply_text("You're not subscribed. Send /start to begin.")
        return
    threshold = sub["alert_threshold_pct"]
    direction = sub["alert_direction"]
    hour = sub.get("briefing_hour", 8)
    active = "🔔 On" if sub["active"] else "🔕 Paused"
    dir_label = {"both": "rises & drops 📈📉", "up": "rises only 📈", "down": "drops only 📉"}.get(direction, direction)
    await update.message.reply_text(
        f"⚙️ *Your Settings*\n\n"
        f"Alerts: {active}\n"
        f"Threshold: *{threshold}%* move triggers alert\n"
        f"Direction: *{dir_label}*\n"
        f"Daily briefing: *{hour}:00 UTC* ({hour+1}am Lagos)\n\n"
        f"Change threshold: `/threshold 3`\n"
        f"Change direction: `/direction up` | `down` | `both`\n"
        f"Change briefing time: `/briefing 6` (6 UTC = 7am Lagos)",
        parse_mode="Markdown"
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
    await update.message.reply_text(
        f"✅ Daily briefing set to *{hour}:00 UTC* ({hour+1}am Lagos time)",
        parse_mode="Markdown"
    )

# ──────────────────────────────────────────────
# Group mode
# ──────────────────────────────────────────────

async def handle_chat_member(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Detect when bot is added to or removed from a group."""
    result: ChatMemberUpdated = update.my_chat_member
    if not result:
        return
    old_status = result.old_chat_member.status
    new_status = result.new_chat_member.status
    chat = result.chat

    if new_status in ("member", "administrator") and old_status in ("left", "kicked"):
        db.register_group(chat.id, chat.title or "Unnamed Group")
        logger.info(f"Bot added to group: {chat.title} ({chat.id})")
        await ctx.bot.send_message(
            chat.id,
            "👋 *Nigeria FX Rate Tracker is here!*\n\n"
            "I'll post a daily USD/NGN briefing at 8am Lagos time.\n\n"
            "Commands work in groups too:\n"
            "• /rate — Current rate\n"
            "• /rate GBP · /rate EUR\n"
            "• /history — 7-day trend",
            parse_mode="Markdown"
        )
    elif new_status in ("left", "kicked"):
        db.deregister_group(chat.id)
        logger.info(f"Bot removed from group: {chat.title} ({chat.id})")

# ──────────────────────────────────────────────
# Background jobs
# ──────────────────────────────────────────────

async def job_poll_rates(ctx: ContextTypes.DEFAULT_TYPE):
    """Fetch latest rate, store it, alert subscribers if threshold crossed."""
    try:
        prev = db.get_latest_rate("USD")
        rates = await scraper.get_all_sources("USD")
        saved = db.save_rate(rates["cbn_rate"], rates["parallel_rate"], rates.get("source", "multi"), "USD")
        saved["fetched_at"] = datetime.utcnow().isoformat()

        if prev:
            change_pct = (saved["parallel_rate"] - prev["parallel_rate"]) / prev["parallel_rate"] * 100
            moved_up = change_pct > 0
            abs_change = abs(change_pct)
            direction_label = "📈 UP" if moved_up else "📉 DOWN"
            alert_msg = (
                f"🚨 *FX Alert!* Rate moved {direction_label} {abs_change:.1f}%\n\n"
                + format_rate(saved, "USD")
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

        logger.info(f"Poll done. USD parallel: ₦{saved['parallel_rate']:,.2f}")
    except Exception as e:
        logger.error(f"Poll job error: {e}")

async def job_daily_briefing(ctx: ContextTypes.DEFAULT_TYPE):
    """Send morning briefing to all active subscribers and groups."""
    logger.info("Sending daily briefings...")
    msg = format_briefing("USD")

    # Individual subscribers
    for sub in db.get_subscribers():
        try:
            await ctx.bot.send_message(sub["telegram_id"], msg, parse_mode="Markdown")
        except Exception as e:
            logger.warning(f"Briefing failed for {sub['telegram_id']}: {e}")

    # Groups
    for group in db.get_active_groups():
        try:
            await ctx.bot.send_message(group["chat_id"], msg, parse_mode="Markdown")
        except Exception as e:
            logger.warning(f"Briefing failed for group {group['chat_id']}: {e}")

# ──────────────────────────────────────────────
# Startup
# ──────────────────────────────────────────────

async def post_init(app: Application):
    # Rate polling every 15 min
    app.job_queue.run_repeating(job_poll_rates, interval=POLL_INTERVAL, first=10)
    # Daily briefing at DAILY_BRIEFING_HOUR UTC
    app.job_queue.run_daily(
        job_daily_briefing,
        time=time(hour=DAILY_BRIEFING_HOUR, minute=0)
    )
    logger.info(f"Jobs scheduled: poll every {POLL_INTERVAL}s, briefing at {DAILY_BRIEFING_HOUR}:00 UTC")

def main():
    db.init_db()
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("subscribe", cmd_subscribe))
    app.add_handler(CommandHandler("rate", cmd_rate))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CommandHandler("chart", cmd_chart))
    app.add_handler(CommandHandler("settings", cmd_settings))
    app.add_handler(CommandHandler("threshold", cmd_threshold))
    app.add_handler(CommandHandler("direction", cmd_direction))
    app.add_handler(CommandHandler("briefing", cmd_briefing_time))

    # Group events (bot added/removed)
    app.add_handler(ChatMemberHandler(handle_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))

    logger.info("🚀 FX Tracker bot starting...")
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
