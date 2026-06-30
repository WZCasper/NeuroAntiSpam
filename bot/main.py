#!/usr/bin/env python3
"""
NeuroAntiSpam Bot - Main Entry Point
Autonomous Telegram Anti-Spam Bot with AI-powered detection
"""

import asyncio
import logging
import os
import sys

from telegram.ext import (
    Application,
    MessageHandler,
    ChatMemberHandler,
    CommandHandler,
    CallbackQueryHandler,
    filters,
)

from handlers.spam_handler import SpamHandler
from handlers.admin_handler import AdminHandler
from handlers.captcha_handler import CaptchaHandler
from handlers.member_handler import MemberHandler
from handlers.report_handler import ReportHandler, StatsHandler, FloodHandler
from database.db import Database
from ml.spam_detector import SpamDetector
from config import Config

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler("neuroantispam.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


async def main():
    """Initialize and start the bot."""
    config = Config()
    
    # Initialize database
    db = Database(config.DATABASE_URL)
    await db.initialize()
    logger.info("Database initialized")

    # Initialize ML spam detector
    spam_detector = SpamDetector(db)
    await spam_detector.load_model()
    logger.info("ML Spam Detector loaded")

    # Build application
    app = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .build()
    )

    # Store shared objects
    app.bot_data["db"] = db
    app.bot_data["spam_detector"] = spam_detector
    app.bot_data["config"] = config

    # Initialize handlers
    spam_handler = SpamHandler(db, spam_detector, config)
    admin_handler = AdminHandler(db, config)
    captcha_handler = CaptchaHandler(db, config)
    member_handler = MemberHandler(db, spam_detector, config)
    report_handler = ReportHandler(db, config)
    stats_handler = StatsHandler(db, config)
    flood_handler = FloodHandler(db, config)

    # Register command handlers
    app.add_handler(CommandHandler("start", admin_handler.cmd_start))
    app.add_handler(CommandHandler("help", admin_handler.cmd_help))
    app.add_handler(CommandHandler("settings", admin_handler.cmd_settings))
    app.add_handler(CommandHandler("stats", stats_handler.cmd_stats))
    app.add_handler(CommandHandler("ban", admin_handler.cmd_ban))
    app.add_handler(CommandHandler("kick", admin_handler.cmd_kick))
    app.add_handler(CommandHandler("mute", admin_handler.cmd_mute))
    app.add_handler(CommandHandler("unmute", admin_handler.cmd_unmute))
    app.add_handler(CommandHandler("warn", admin_handler.cmd_warn))
    app.add_handler(CommandHandler("unwarn", admin_handler.cmd_unwarn))
    app.add_handler(CommandHandler("warns", admin_handler.cmd_warns))
    app.add_handler(CommandHandler("whitelist", admin_handler.cmd_whitelist))
    app.add_handler(CommandHandler("blacklist", admin_handler.cmd_blacklist))
    app.add_handler(CommandHandler("report", report_handler.cmd_report))
    app.add_handler(CommandHandler("addspam", admin_handler.cmd_add_spam_phrase))
    app.add_handler(CommandHandler("mode", admin_handler.cmd_set_mode))
    app.add_handler(CommandHandler("setlang", admin_handler.cmd_set_language))

    # Register message handlers
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS,
            spam_handler.handle_message,
        )
    )
    app.add_handler(
        MessageHandler(
            filters.PHOTO | filters.Document.ALL | filters.VIDEO,
            spam_handler.handle_media,
        )
    )

    # Register member join/leave handler
    app.add_handler(ChatMemberHandler(member_handler.handle_member_update))

    # Register callback query handler (buttons)
    app.add_handler(CallbackQueryHandler(captcha_handler.handle_captcha, pattern="^captcha_"))
    app.add_handler(CallbackQueryHandler(report_handler.handle_report_callback, pattern="^report_"))
    app.add_handler(CallbackQueryHandler(admin_handler.handle_settings_callback, pattern="^settings_"))

    # Schedule periodic tasks
    job_queue = app.job_queue
    job_queue.run_repeating(spam_detector.retrain_model, interval=3600, first=60)
    job_queue.run_repeating(db.cleanup_old_data, interval=86400, first=300)
    job_queue.run_repeating(flood_handler.reset_flood_counters, interval=60, first=60)

    logger.info("NeuroAntiSpam Bot starting...")
    
    async with app:
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        logger.info("Bot is running!")
        
        # Keep running
        await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
