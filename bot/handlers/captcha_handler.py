"""
NeuroAntiSpam - Captcha Handler
Math captcha for new members to prevent bot raids.
"""

import asyncio
import logging
import random
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import TelegramError

logger = logging.getLogger(__name__)

# Active captcha sessions: {(chat_id, user_id): {"answer": int, "message_id": int, "expires": datetime}}
_pending: dict = {}


class CaptchaHandler:
    def __init__(self, db, config):
        self.db = db
        self.config = config

    async def send_captcha(self, chat_id: int, user_id: int, username: str, context: ContextTypes.DEFAULT_TYPE):
        """Send math captcha to new member and restrict them until solved."""
        try:
            from telegram import ChatPermissions
            await context.bot.restrict_member(
                chat_id,
                user_id,
                permissions=ChatPermissions(can_send_messages=False),
            )
        except TelegramError as e:
            logger.warning(f"Could not restrict new member: {e}")
            return

        a = random.randint(1, 20)
        b = random.randint(1, 20)
        answer = a + b

        # Build answer buttons with 3 wrong options
        options = {answer}
        while len(options) < 4:
            options.add(random.randint(1, 40))
        options = list(options)
        random.shuffle(options)

        keyboard = [
            [InlineKeyboardButton(str(opt), callback_data=f"captcha_{user_id}_{opt}") for opt in options]
        ]

        timeout = self.config.CAPTCHA_TIMEOUT
        expires = datetime.utcnow() + timedelta(seconds=timeout)

        try:
            msg = await context.bot.send_message(
                chat_id,
                f"👋 <b>{username}</b>, добро пожаловать!\n\n"
                f"Чтобы войти в группу, реши пример:\n"
                f"<b>{a} + {b} = ?</b>\n\n"
                f"⏳ У тебя <b>{timeout} секунд</b>.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )

            _pending[(chat_id, user_id)] = {
                "answer": answer,
                "message_id": msg.message_id,
                "expires": expires,
                "username": username,
            }

            # Auto-kick if timeout exceeded
            asyncio.create_task(self._captcha_timeout(chat_id, user_id, msg.message_id, context, timeout))

        except TelegramError as e:
            logger.error(f"Could not send captcha: {e}")

    async def _captcha_timeout(self, chat_id: int, user_id: int, msg_id: int,
                                context: ContextTypes.DEFAULT_TYPE, timeout: int):
        await asyncio.sleep(timeout)
        if (chat_id, user_id) in _pending:
            _pending.pop((chat_id, user_id), None)
            try:
                await context.bot.ban_chat_member(chat_id, user_id)
                await context.bot.unban_chat_member(chat_id, user_id)
                await context.bot.delete_message(chat_id, msg_id)
                await context.bot.send_message(
                    chat_id,
                    "⏰ Пользователь не прошёл капчу и был удалён из группы.",
                )
                logger.info(f"Captcha timeout: kicked user {user_id} from chat {chat_id}")
            except TelegramError as e:
                logger.warning(f"Captcha kick failed: {e}")

    async def handle_captcha(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        parts = query.data.split("_")
        if len(parts) != 3:
            return

        _, target_user_id, chosen = parts
        target_user_id = int(target_user_id)
        chosen = int(chosen)
        chat_id = query.message.chat_id
        clicking_user_id = query.from_user.id

        # Only the target user can solve the captcha
        if clicking_user_id != target_user_id:
            await query.answer("❌ Эта капча не для тебя!", show_alert=True)
            return

        session = _pending.get((chat_id, target_user_id))
        if not session:
            await query.answer("⏰ Время капчи истекло.", show_alert=True)
            return

        if datetime.utcnow() > session["expires"]:
            _pending.pop((chat_id, target_user_id), None)
            await query.answer("⏰ Время истекло!", show_alert=True)
            return

        if chosen == session["answer"]:
            _pending.pop((chat_id, target_user_id), None)
            # Restore permissions
            try:
                from telegram import ChatPermissions
                await context.bot.restrict_member(
                    chat_id,
                    target_user_id,
                    permissions=ChatPermissions(
                        can_send_messages=True,
                        can_send_media_messages=True,
                        can_send_polls=True,
                        can_send_other_messages=True,
                        can_add_web_page_previews=True,
                    ),
                )
            except TelegramError as e:
                logger.warning(f"Could not restore permissions: {e}")

            try:
                await query.edit_message_text(
                    f"✅ <b>{session['username']}</b> прошёл проверку и добавлен в группу!",
                    parse_mode="HTML",
                )
                await asyncio.sleep(5)
                await query.delete_message()
            except TelegramError:
                pass
        else:
            # Wrong answer — kick
            _pending.pop((chat_id, target_user_id), None)
            try:
                await context.bot.ban_chat_member(chat_id, target_user_id)
                await context.bot.unban_chat_member(chat_id, target_user_id)
                await query.edit_message_text(
                    f"❌ <b>{session['username']}</b> дал неверный ответ и удалён.",
                    parse_mode="HTML",
                )
                await asyncio.sleep(5)
                await query.delete_message()
            except TelegramError as e:
                logger.warning(f"Wrong captcha kick failed: {e}")
