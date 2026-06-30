"""
NeuroAntiSpam - Member Handler
Handles new member joins, leaves, and raid detection.
"""

import logging
from datetime import datetime

from telegram import Update, ChatMember
from telegram.ext import ContextTypes
from telegram.error import TelegramError

logger = logging.getLogger(__name__)


class MemberHandler:
    def __init__(self, db, spam_detector, config):
        self.db = db
        self.spam_detector = spam_detector
        self.config = config

    async def handle_member_update(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        result = update.chat_member or update.my_chat_member
        if not result:
            return

        old_status = result.old_chat_member.status
        new_status = result.new_chat_member.status
        user = result.new_chat_member.user
        chat = result.chat

        # Bot was added to a group
        if user.id == context.bot.id:
            if new_status in (ChatMember.ADMINISTRATOR, ChatMember.MEMBER):
                await self._on_bot_added(chat, context)
            return

        # New member joined
        if old_status in (ChatMember.LEFT, ChatMember.BANNED) and new_status == ChatMember.MEMBER:
            await self._on_member_joined(user, chat, context)

        # Member left or was banned
        elif new_status in (ChatMember.LEFT, ChatMember.BANNED):
            await self._on_member_left(user, chat)

    async def _on_bot_added(self, chat, context: ContextTypes.DEFAULT_TYPE):
        """Bot was added to a new group."""
        await self.db.get_or_create_group(chat.id, chat.title, getattr(chat, "username", None))
        logger.info(f"Bot added to group: {chat.title} ({chat.id})")
        try:
            await context.bot.send_message(
                chat.id,
                "🛡 <b>NeuroAntiSpam подключён!</b>\n\n"
                "Я готов защищать вашу группу от спама.\n\n"
                "⚙️ Настройте меня через /settings\n"
                "📊 Статистика: /stats\n"
                "❓ Помощь: /help\n\n"
                "Убедитесь, что у меня есть права:\n"
                "• Удаление сообщений\n"
                "• Блокировка участников\n"
                "• Ограничение участников",
                parse_mode="HTML",
            )
        except TelegramError as e:
            logger.warning(f"Could not send welcome message: {e}")

    async def _on_member_joined(self, user, chat, context: ContextTypes.DEFAULT_TYPE):
        """Handle a new member joining."""
        group = await self.db.get_or_create_group(chat.id, chat.title)
        settings = group.settings or {}

        # Create member record
        await self.db.get_or_create_member(chat.id, user.id, user.username, user.full_name)

        # Raid protection
        if settings.get("raid_protection", True):
            raid_threshold = settings.get("raid_threshold", self.config.RAID_THRESHOLD)
            raid_window = settings.get("raid_window", self.config.FLOOD_WINDOW)
            join_count = await self.db.increment_raid(chat.id, raid_window)

            if join_count >= raid_threshold:
                await self._handle_raid(chat, user, context, settings)
                return

        # Check blacklist
        member_record = await self.db.get_or_create_member(chat.id, user.id)
        if member_record.is_blacklisted:
            try:
                await context.bot.ban_chat_member(chat.id, user.id)
                logger.info(f"Auto-banned blacklisted user {user.id} in {chat.title}")
            except TelegramError as e:
                logger.warning(f"Could not ban blacklisted user: {e}")
            return

        # Captcha
        if settings.get("captcha_enabled", True):
            from handlers.captcha_handler import CaptchaHandler
            captcha = CaptchaHandler(self.db, self.config)
            username = f"@{user.username}" if user.username else user.full_name or str(user.id)
            await captcha.send_captcha(chat.id, user.id, username, context)
        else:
            # Send welcome message if no captcha
            await self._send_welcome(user, chat, settings, context)

    async def _on_member_left(self, user, chat):
        """Handle member leaving."""
        logger.info(f"User {user.id} left {chat.title}")

    async def _handle_raid(self, chat, user, context: ContextTypes.DEFAULT_TYPE, settings: dict):
        """Mass join detected — kick the joining user and alert admins."""
        try:
            await context.bot.ban_chat_member(chat.id, user.id)
            await context.bot.unban_chat_member(chat.id, user.id)
            logger.warning(f"Raid detected in {chat.title}, kicked {user.id}")
        except TelegramError as e:
            logger.error(f"Raid kick failed: {e}")

        # Notify group once (avoid spam of raid messages)
        try:
            await context.bot.send_message(
                chat.id,
                "🚨 <b>Обнаружена атака (рейд)!</b>\n"
                "Массовое вступление заблокировано.\n"
                "Усиленная защита активирована.",
                parse_mode="HTML",
            )
        except TelegramError:
            pass

    async def _send_welcome(self, user, chat, settings: dict, context: ContextTypes.DEFAULT_TYPE):
        """Send welcome message to new member."""
        if not settings.get("welcome_enabled", True):
            return

        username = f"@{user.username}" if user.username else user.full_name or "Новый участник"
        custom_msg = settings.get("welcome_message")

        if custom_msg:
            text = custom_msg.replace("{name}", username)
        else:
            text = f"👋 Добро пожаловать в группу, <b>{username}</b>!"

        try:
            msg = await context.bot.send_message(chat.id, text, parse_mode="HTML")
            # Auto-delete welcome after 30 seconds
            import asyncio
            await asyncio.sleep(30)
            try:
                await msg.delete()
            except TelegramError:
                pass
        except TelegramError as e:
            logger.warning(f"Could not send welcome: {e}")
