"""
NeuroAntiSpam - Report Handler
Allows users to report spam messages for ML training.
"""
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import TelegramError

logger = logging.getLogger(__name__)


class ReportHandler:
    def __init__(self, db, config):
        self.db = db
        self.config = config

    async def cmd_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        message = update.effective_message
        if not message.reply_to_message:
            await message.reply_text("❌ Ответьте на сообщение, которое хотите отметить как спам.")
            return

        target = message.reply_to_message
        text = target.text or target.caption or ""
        if not text:
            await message.reply_text("❌ Нет текста для анализа.")
            return

        user = update.effective_user
        chat = update.effective_chat
        reporter = f"@{user.username}" if user.username else user.full_name

        keyboard = [[
            InlineKeyboardButton("✅ Да, спам", callback_data=f"report_spam_{target.from_user.id}"),
            InlineKeyboardButton("❌ Не спам", callback_data=f"report_ham_{target.from_user.id}"),
        ]]
        await message.reply_text(
            f"🚨 <b>{reporter}</b> сообщил о спаме.\nПодтвердите действие (только для администраторов):",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        # Save to training data immediately
        await self.db.add_training_sample(text, is_spam=True, source="report")

    async def handle_report_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user = query.from_user
        chat = query.message.chat

        # Only admins confirm
        try:
            member = await chat.get_member(user.id)
            if member.status not in ("administrator", "creator"):
                await query.answer("❌ Только администраторы могут подтверждать.", show_alert=True)
                return
        except TelegramError:
            return

        await query.answer()
        parts = query.data.split("_")
        action = parts[1]  # spam or ham
        target_user_id = int(parts[2])

        if action == "spam":
            try:
                await chat.ban_member(target_user_id)
                await query.edit_message_text("✅ Спамер заблокирован. Спасибо за сообщение!")
            except TelegramError as e:
                await query.edit_message_text(f"❌ Ошибка: {e}")
        else:
            await query.edit_message_text("✅ Отмечено как не-спам. Данные сохранены для обучения.")


class StatsHandler:
    def __init__(self, db, config):
        self.db = db
        self.config = config

    async def cmd_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat = update.effective_chat
        stats = await self.db.get_group_stats(chat.id, days=7)
        total = stats.get("total", 0)
        by_action = stats.get("by_action", {})
        by_method = stats.get("by_method", {})

        action_lines = "\n".join(
            f"  • {k}: {v}" for k, v in by_action.items()
        ) or "  Нет данных"
        method_lines = "\n".join(
            f"  • {k}: {v}" for k, v in by_method.items()
        ) or "  Нет данных"

        text = (
            f"📊 <b>Статистика NeuroAntiSpam</b>\n"
            f"Группа: <b>{chat.title}</b>\n"
            f"Период: последние 7 дней\n\n"
            f"🛡 Всего обнаружено: <b>{total}</b>\n\n"
            f"<b>По действиям:</b>\n{action_lines}\n\n"
            f"<b>По методам:</b>\n{method_lines}"
        )
        await update.message.reply_text(text, parse_mode="HTML")


class FloodHandler:
    def __init__(self, db, config):
        self.db = db
        self.config = config

    async def reset_flood_counters(self, context: ContextTypes.DEFAULT_TYPE = None):
        """Called every minute to clean up old flood tracking."""
        try:
            from sqlalchemy import delete
            from database.db import FloodTracker
            from datetime import timedelta
            import datetime as dt
            cutoff = dt.datetime.utcnow() - timedelta(minutes=2)
            async with self.db.session() as s:
                await s.execute(
                    delete(FloodTracker).where(FloodTracker.window_start < cutoff)
                )
                await s.commit()
        except Exception as e:
            logger.error(f"Flood reset error: {e}")
