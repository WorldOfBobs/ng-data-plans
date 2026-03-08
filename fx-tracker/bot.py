"""
Nigeria Parallel FX Rate Tracker — Telegram Bot
Run: python bot.py
"""
import asyncio
import logging
import os
from datetime import datetime

from dotenv import load_dotenv
from telegram import Update, InputFile
from telegram.ext import Application, CommandHandler, ContextTypes

import db
import scraper
import chart

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SECONDS", "900"))  # 15 min
ALERT_THRESHOLD_PCT = float(os.getenv("ALERT_THRESHOLD_PCT", "2.0"))  # 2%

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def format_rate(r: dict) -> str:
    flag = "🟢" if r["spread_pct"] < 5 else "🟡" if r["spread_pct"] < 15 else "🔴"
    ts = r["fetched_at"][:16] if r.get("fetched_at") else "N/A"
    return (
        f"💵 *USD/NGN Rate Update* {flag}\n\n"
        f"🏦 CBN Official:    ₦{r['cbn_rate']:,.2f}\n"
        f"🏪 Parallel Market: ₦{r['parallel_rate']:,.2f}\n"
        f"📊 Spread:          ₦{r['spread']:,.2f} ({r['spread_pct']:.1f}%)\n\n"
        f"🕐 Updated: {ts} UTC\n"
        f"📡 Source: {r.get('source', 'N/A')}"
    )

# ──────────────────────────────────────────────
# Bot commands
# ──────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.add_subscriber(user.id, user.username or user.first_name)
    await update.message.reply_text(
        f"👋 Welcome to *Nigeria FX Tracker*, {user.first_name}!\n\n"
        "You're now subscribed to rate alerts.\n\n"
        "Commands:\n"
        "/rate — Current USD/NGN rate\n"
        "/chart — 24-hour chart\n"
        "/stop — Unsubscribe from alerts",
        parse_mode="Markdown"
    )

async def cmd_rate(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Fetching latest rate...")
    try:
        rates = await scraper.get_rates()
        saved = db.save_rate(rates["cbn_rate"], rates["parallel_rate"], rates["source"])
        saved["source"] = rates["source"]
        saved["fetched_at"] = datetime.utcnow().isoformat()
        await update.message.reply_text(format_rate(saved), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Rate fetch error: {e}")
        await update.message.reply_text("❌ Failed to fetch rate. Try again shortly.")

async def cmd_chart(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    history = db.get_rate_history(24)
    if not history:
        await update.message.reply_text("No history yet — check back after a few polls!")
        return

    png = chart.matplotlib_chart(history)
    if png:
        await update.message.reply_photo(photo=png, caption="📈 USD/NGN — last 24 hours")
    else:
        ascii_c = chart.ascii_chart(history)
        await update.message.reply_text(f"```\n{ascii_c}\n```", parse_mode="Markdown")

async def cmd_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    db.remove_subscriber(update.effective_user.id)
    await update.message.reply_text("✅ Unsubscribed. Use /start to resubscribe anytime.")

# ──────────────────────────────────────────────
# Background polling + alerts
# ──────────────────────────────────────────────

async def poll_and_alert(app: Application):
    """Run every POLL_INTERVAL seconds, alert subscribers if rate moves significantly."""
    while True:
        await asyncio.sleep(POLL_INTERVAL)
        try:
            prev = db.get_latest_rate()
            rates = await scraper.get_rates()
            saved = db.save_rate(rates["cbn_rate"], rates["parallel_rate"], rates["source"])
            saved["source"] = rates["source"]
            saved["fetched_at"] = datetime.utcnow().isoformat()

            # Check if spread changed enough to alert
            if prev:
                change_pct = abs(saved["parallel_rate"] - prev["parallel_rate"]) / prev["parallel_rate"] * 100
                if change_pct >= ALERT_THRESHOLD_PCT:
                    direction = "📈 UP" if saved["parallel_rate"] > prev["parallel_rate"] else "📉 DOWN"
                    msg = (
                        f"🚨 *FX Alert!* Rate moved {direction} {change_pct:.1f}%\n\n"
                        + format_rate(saved)
                    )
                    for tid in db.get_subscribers():
                        try:
                            await app.bot.send_message(tid, msg, parse_mode="Markdown")
                        except Exception as e:
                            logger.warning(f"Alert failed for {tid}: {e}")

            logger.info(f"Poll done. Parallel: ₦{saved['parallel_rate']:,.2f}")
        except Exception as e:
            logger.error(f"Poll error: {e}")

# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def main():
    db.init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("rate", cmd_rate))
    app.add_handler(CommandHandler("chart", cmd_chart))
    app.add_handler(CommandHandler("stop", cmd_stop))

    loop = asyncio.get_event_loop()
    loop.create_task(poll_and_alert(app))

    logger.info("🚀 FX Tracker bot starting...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
