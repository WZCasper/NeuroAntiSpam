"""
NeuroAntiSpam - Spam Handler
Processes every message and decides action based on group settings.
"""

import logging
import re
from datetime import datetime, timedelta

from telegram import Update, Message, Chat
from telegram.ext import ContextTypes
from telegram.error import TelegramError

logger = logging.getLogger(__name__)

URL_RE = re.compile(r"https?://\S+|www\.\S+|t\.me/\S+", re.I)


class SpamHandler:
    def __init__(self, db, spam_detector, config):
        self.db = db
        self.detector = spam_detector
        self.config = config

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        message = update.effective_message
        user = update.effective_user
        chat = update.effective_chat

        if not message or not user or not chat or user.is_bot:
            return

        group = await self.db.get_or_create_group(chat.id, chat.title, chat.username)
        settings = group.settings or {}

        member = await self.db.get_or_create_member(
            chat.id, user.id, user.username, user.full_name
        )

        # Skip whitelisted users
        if member.is_whitelisted:
            return

        text = message.text or message.caption or ""

        # Shadow ban check — delete silently
        if member.is_shadowbanned:
            try:
                await message.delete()
            except TelegramError:
                pass
            return

        # Mute check
        if member.is_muted and member.mute_until:
            if datetime.utcnow() < member.mute_until:
                try:
                    await message.delete()
                except TelegramError:
                    pass
                return
            else:
                await self.db.set_mute(chat.id, user.id, None)

        # Anti-link for new/untrusted users
        if settings.get("antilink_enabled", True):
            new_only = settings.get("antilink_new_only", True)
            is_new = member.message_count <= settings.get("quarantine_msgs", 5)
            if URL_RE.search(text) and (not new_only or is_new):
                await self._take_action(
                    "delete", message, user, chat, group, settings,
                    score=0.9, method="antilink", text=text
                )
                return

        # Night mode — extra strict
        if settings.get("night_mode_enabled", False):
            hour = datetime.utcnow().hour
            start = settings.get("night_mode_start", 23)
            end = settings.get("night_mode_end", 7)
            in_night = (hour >= start) or (hour < end)
            if in_night:
                threshold = max(0.5, settings.get("spam_threshold", 0.75) - 0.2)
            else:
                threshold = settings.get("spam_threshold", 0.75)
        else:
            threshold = settings.get("spam_threshold", 0.75)

        # Quarantine — stricter for new users
        if settings.get("new_user_quarantine", True):
            quarantine_limit = settings.get("quarantine_msgs", 5)
            if member.message_count <= quarantine_limit:
                threshold = max(0.5, threshold - 0.15)

        # Get group custom phrases
        group_phrases = await self.db.get_spam_phrases(chat.id)

        # Flood check
        if settings.get("flood_enabled", True):
            flood_limit = settings.get("flood_limit", self.config.FLOOD_LIMIT)
            flood_window = settings.get("flood_window", self.config.FLOOD_WINDOW)
            count = await self.db.increment_flood(chat.id, user.id, flood_window)
            if count > flood_limit:
                await self._take_action(
                    "mute_temp", message, user, chat, group, settings,
                    score=1.0, method="flood", text=text
                )
                return

        # ML + AI analysis
        is_spam, score, method = await self.detector.analyze(
            text, group_phrases=group_phrases, threshold=threshold
        )

        if is_spam:
            action = self._decide_action(score, settings, member.warnings)
            await self._take_action(
                action, message, user, chat, group, settings,
                score=score, method=method, text=text
            )

    async def handle_media(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle photo/video/document spam (caption analysis)."""
        message = update.effective_message
        user = update.effective_user
        chat = update.effective_chat

        if not message or not user or not chat or user.is_bot:
            return

        caption = message.caption or ""
        if not caption:
            return

        # Reuse text handler logic via caption
        update.effective_message.text = caption
        await self.handle_message(update, context)

    def _decide_action(self, score: float, settings: dict, current_warnings: int) -> str:
        mode = settings.get("mode", "medium")
        max_warns = settings.get("max_warnings", self.config.MAX_WARNINGS)

        if mode == "soft":
            if score >= 0.95:
                return "warn"
            return "delete"

        if mode == "medium":
            if score >= 0.95:
                if current_warnings + 1 >= max_warns:
                    return "ban"
                return "warn"
            return "delete"

        if mode == "hard":
            if score >= 0.85:
                return "ban"
            return "kick"

        return "delete"

    async def _take_action(
        self, action: str, message: Message, user, chat: Chat,
        group, settings: dict, score: float, method: str, text: str
    ):
        chat_id = chat.id
        user_id = user.id
        username = f"@{user.username}" if user.username else user.full_name or str(user_id)

        # Always delete spam message
        if settings.get("auto_delete_spam", True):
            try:
                await message.delete()
            except TelegramError as e:
                logger.warning(f"Could not delete message: {e}")

        real_action = action

        if action == "ban":
            try:
                await message.chat.ban_member(user_id)
                logger.info(f"Banned {username} in {chat.title}")
            except TelegramError as e:
                logger.error(f"Ban failed: {e}")
                real_action = "delete"

        elif action == "kick":
            try:
                await message.chat.ban_member(user_id)
                await message.chat.unban_member(user_id)
                logger.info(f"Kicked {username} from {chat.title}")
            except TelegramError as e:
                logger.error(f"Kick failed: {e}")
                real_action = "delete"

        elif action == "mute_temp":
            until = datetime.utcnow() + timedelta(minutes=10)
            try:
                from telegram import ChatPermissions
                await message.chat.restrict_member(
                    user_id,
                    permissions=ChatPermissions(can_send_messages=False),
                    until_date=until,
                )
                await self.db.set_mute(chat_id, user_id, until)
                logger.info(f"Muted {username} for 10 min in {chat.title}")
            except TelegramError as e:
                logger.error(f"Mute failed: {e}")

        elif action == "warn":
            warns = await self.db.add_warning(chat_id, user_id)
            max_warns = settings.get("max_warnings", self.config.MAX_WARNINGS)
            if warns >= max_warns:
                try:
                    await message.chat.ban_member(user_id)
                    real_action = "ban"
                    logger.info(f"Auto-banned {username} after {warns} warnings")
                except TelegramError as e:
                    logger.error(f"Auto-ban failed: {e}")

        elif action == "shadowban":
            await self.db.set_shadowban(chat_id, user_id, True)

        # Log to database
        await self.db.log_spam(
            group_id=chat_id, user_id=user_id, username=username,
            text=text, score=score, method=method, action=real_action,
        )

        # Add to training data
        await self.db.add_training_sample(text, is_spam=True, source="auto")

        # Send notification to group
        if settings.get("notify_admin", True):
            await self._send_notification(message, chat, user, username, real_action, score, method, settings)

    async def _send_notification(self, message, chat, user, username, action, score, method, settings):
        action_labels = {
            "ban": "🚫 Заблокирован",
            "kick": "👢 Удалён из группы",
            "mute_temp": "🔇 Замолчан на 10 мин",
            "warn": "⚠️ Получил предупреждение",
            "delete": "🗑 Сообщение удалено",
            "shadowban": "👻 Теневой бан",
        }
        method_labels = {
            "keyword": "ключевые слова",
            "phrase": "спам-фраза",
            "ml": "ML-модель",
            "ai": "AI-анализ",
            "flood": "флуд",
            "antilink": "запрещённая ссылка",
            "global_phrase": "глобальная база",
        }
        label = action_labels.get(action, action)
        mlabel = method_labels.get(method, method)
        pct = int(score * 100)

        notify_channel = settings.get("notify_channel_id")
        target_chat = notify_channel or chat.id

        text = (
            f"🛡 <b>NeuroAntiSpam</b>\n"
            f"👤 Пользователь: {username}\n"
            f"📊 Уверенность: {pct}%\n"
            f"🔍 Метод: {mlabel}\n"
            f"⚡ Действие: {label}"
        )
        try:
            sent = await message.chat.send_message(text, parse_mode="HTML")
            # Auto-delete notification after 15 seconds
            import asyncio
            await asyncio.sleep(15)
            try:
                await sent.delete()
            except TelegramError:
                pass
        except TelegramError as e:
            logger.warning(f"Could not send notification: {e}")
