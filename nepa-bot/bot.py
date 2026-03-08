"""
NEPA Power Outage Alert Bot — Telegram
Run: python bot.py
"""
import asyncio
import logging
import os
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler

from dotenv import load_dotenv
import db

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]

SET_AREA = 0  # conversation state

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def parse_area(text: str) -> tuple[str, str, str]:
    """Parse 'Lagos, Lekki Phase 1' → (state, city, neighborhood)"""
    parts = [p.strip() for p in text.split(",")]
    if len(parts) == 1:
        return ("", parts[0], "")
    elif len(parts) == 2:
        return ("", parts[0], parts[1])
    else:
        return (parts[0], parts[1], parts[2])

def area_status_msg(city: str, reports: list[dict]) -> str:
    if not reports:
        return f"🤷 No recent reports for *{city}*. You're the first — share what's happening!"
    total = sum(r["cnt"] for r in reports)
    top = reports[0]
    if top["status"] == "out":
        emoji = "🔴"
        msg = f"NEPA don take light for *{city}*"
    else:
        emoji = "🟢"
        msg = f"Light don come back for *{city}*"
    return f"{emoji} {msg}\n📊 {total} report(s) in the last 2 hours"

async def notify_area(app, reporter_id, city, neighborhood, status):
    """Notify all subscribed users in same area."""
    subs = db.get_subscribers_in_area(city, neighborhood, exclude_id=reporter_id)
    if not subs:
        return 0
    if status == "out":
        msg = f"🔴 Alert: NEPA don take light for *{city}* {f'({neighborhood})' if neighborhood else ''}!\nSomeone just reported power is out."
    else:
        msg = f"🟢 Praise God! Light don come back for *{city}* {f'({neighborhood})' if neighborhood else ''}!\nSomeone just reported power is restored."
    sent = 0
    for tid in subs:
        try:
            await app.bot.send_message(tid, msg, parse_mode="Markdown")
            sent += 1
        except Exception as e:
            logger.warning(f"Notify failed for {tid}: {e}")
    return sent

# ──────────────────────────────────────────────
# Commands
# ──────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚡ *NEPA Alert Bot* — Power Outage Tracker\n\n"
        "Track and report power outages in your area.\n\n"
        "First, set your area with /area\n\n"
        "Commands:\n"
        "/area — Set your location\n"
        "/out — Report power is OUT ❌\n"
        "/back — Report power is BACK ✅\n"
        "/status — Check your area's current status\n"
        "/subscribe — Get alerts from your neighbours\n"
        "/unsubscribe — Stop alerts",
        parse_mode="Markdown"
    )

async def cmd_area_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📍 What area are you in?\n\n"
        "Send it like this:\n"
        "• *Lekki Phase 1* (just neighbourhood)\n"
        "• *Lagos, Lekki Phase 1* (city, neighbourhood)\n"
        "• *Abuja, Wuse 2* (city, area)",
        parse_mode="Markdown"
    )
    return SET_AREA

async def cmd_area_receive(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user = update.effective_user
    state, city, neighborhood = parse_area(text)
    db.upsert_user(user.id, user.username or user.first_name, state, city, neighborhood)
    display = ", ".join(filter(None, [city, neighborhood]))
    await update.message.reply_text(
        f"✅ Area set to *{display}*!\n\n"
        "Now you can:\n"
        "/out — Report power cut\n"
        "/back — Report power restored\n"
        "/subscribe — Get neighbour alerts",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def cmd_area_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled. Use /area to set your location.")
    return ConversationHandler.END

async def cmd_report_out(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_data = db.get_user(update.effective_user.id)
    if not user_data or not user_data.get("area_city"):
        await update.message.reply_text("First set your area with /area")
        return
    city = user_data["area_city"]
    hood = user_data.get("area_neighborhood", "")
    db.add_report(update.effective_user.id, city, hood, "out")
    sent = await notify_area(ctx.application, update.effective_user.id, city, hood, "out")
    await update.message.reply_text(
        f"🔴 Reported: *NEPA don take light for {city}* {f'({hood})' if hood else ''}!\n"
        f"📢 Notified {sent} neighbour(s).",
        parse_mode="Markdown"
    )

async def cmd_report_back(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_data = db.get_user(update.effective_user.id)
    if not user_data or not user_data.get("area_city"):
        await update.message.reply_text("First set your area with /area")
        return
    city = user_data["area_city"]
    hood = user_data.get("area_neighborhood", "")
    db.add_report(update.effective_user.id, city, hood, "back")
    sent = await notify_area(ctx.application, update.effective_user.id, city, hood, "back")
    await update.message.reply_text(
        f"🟢 Reported: *Light don come back for {city}* {f'({hood})' if hood else ''}! Praise God! 🙏\n"
        f"📢 Notified {sent} neighbour(s).",
        parse_mode="Markdown"
    )

async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_data = db.get_user(update.effective_user.id)
    if not user_data or not user_data.get("area_city"):
        await update.message.reply_text("First set your area with /area")
        return
    city = user_data["area_city"]
    reports = db.get_area_status(city)
    await update.message.reply_text(area_status_msg(city, reports), parse_mode="Markdown")

async def cmd_subscribe(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    db.set_subscription(update.effective_user.id, True)
    await update.message.reply_text("✅ Subscribed! You'll get alerts when neighbours report power changes.")

async def cmd_unsubscribe(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    db.set_subscription(update.effective_user.id, False)
    await update.message.reply_text("🔕 Unsubscribed. Use /subscribe to turn alerts back on.")

# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def main():
    db.init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    area_conv = ConversationHandler(
        entry_points=[CommandHandler("area", cmd_area_start)],
        states={SET_AREA: [MessageHandler(filters.TEXT & ~filters.COMMAND, cmd_area_receive)]},
        fallbacks=[CommandHandler("cancel", cmd_area_cancel)],
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(area_conv)
    app.add_handler(CommandHandler("out", cmd_report_out))
    app.add_handler(CommandHandler("back", cmd_report_back))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("subscribe", cmd_subscribe))
    app.add_handler(CommandHandler("unsubscribe", cmd_unsubscribe))

    logger.info("⚡ NEPA Alert Bot starting...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
