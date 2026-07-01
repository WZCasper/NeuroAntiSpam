"""
NeuroAntiSpam - Deep Link Handler
Handles /start commands with encoded moderation actions
sent from the GitHub Pages dashboard.

Format: /start ACTION_USERID_GROUPID[_MINUTES]
Examples:
  /start ban_123456789_-1001234567890
  /start kick_123456789_-1001234567890
  /start mute_123456789_-1001234567890_60
  /start warn_123456789_-1001234567890
  /start unban_123456789_-1001234567890
"""

import logging
from datetime import datetime, timedelta

from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import TelegramError

logger = logging.getLogger(__name__)

VALID_ACTIONS = {"ban", "kick", "mute", "warn", "unban", "unmute", "whitelist", "blacklist", "shadowban"}


async def handle_deeplink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command with deep link payload."""
    message = update.effective_message
    user = update.effective_user

    # No payload → normal /start
    if not context.args:
        return False  # Let admin_handler.cmd_start handle it

    payload = context.args[0]  # e.g. "ban_123456789_-1001234567890"
    parts = payload.split("_")

    if len(parts) < 3:
        return False

    action = parts[0].lower()
    if action not in VALID_ACTIONS:
        return False

    # Parse target user_id and group_id
    # group_id is encoded as n{abs_value} for negative or p{abs_value} for positive
    # to avoid underscores in negative numbers breaking split("_")
    try:
        target_user_id = int(parts[1])
        raw_group = parts[2]
        if raw_group.startswith('n'):
            group_id = -int(raw_group[1:])
        elif raw_group.startswith('p'):
            group_id = int(raw_group[1:])
        else:
            group_id = int(raw_group)
        minutes = int(parts[3]) if len(parts) > 3 else 60
    except (ValueError, IndexError):
        await message.reply_text("❌ Неверный формат команды.")
        return True

    db = context.bot_data.get("db")
    config = context.bot_data.get("config")

    # Verify the user is actually an admin of that group
    try:
        chat_member = await context.bot.get_chat_member(group_id, user.id)
        if chat_member.status not in ("administrator", "creator"):
            await message.reply_text("❌ У вас нет прав администратора в этой группе.")
            return True
    except TelegramError as e:
        await message.reply_text(f"❌ Ошибка проверки прав: {e}")
        return True

    # Execute action
    result_msg = ""

    try:
        if action == "ban":
            await context.bot.ban_chat_member(group_id, target_user_id)
            result_msg = f"✅ Пользователь `{target_user_id}` заблокирован в группе."

        elif action == "kick":
            await context.bot.ban_chat_member(group_id, target_user_id)
            await context.bot.unban_chat_member(group_id, target_user_id)
            result_msg = f"✅ Пользователь `{target_user_id}` удалён из группы."

        elif action == "unban":
            await context.bot.unban_chat_member(group_id, target_user_id)
            if db:
                await db.set_blacklist(group_id, target_user_id, False)
            result_msg = f"✅ Пользователь `{target_user_id}` разблокирован."

        elif action == "mute":
            until = datetime.utcnow() + timedelta(minutes=minutes)
            from telegram import ChatPermissions
            await context.bot.restrict_chat_member(
                group_id,
                target_user_id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until,
            )
            if db:
                await db.set_mute(group_id, target_user_id, until)
            result_msg = f"✅ Пользователь `{target_user_id}` заглушен на {minutes} мин."

        elif action == "unmute":
            from telegram import ChatPermissions
            await context.bot.restrict_chat_member(
                group_id,
                target_user_id,
                permissions=ChatPermissions(
                    can_send_messages=True,
                    can_send_media_messages=True,
                    can_send_polls=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True,
                ),
            )
            if db:
                await db.set_mute(group_id, target_user_id, None)
            result_msg = f"✅ Мут снят с пользователя `{target_user_id}`."

        elif action == "warn":
            warns = 1
            if db:
                warns = await db.add_warning(group_id, target_user_id)
                group = await db.get_or_create_group(group_id)
                max_warns = group.get_setting("max_warnings", 3)
                if warns >= max_warns:
                    await context.bot.ban_chat_member(group_id, target_user_id)
                    result_msg = f"🚫 Пользователь `{target_user_id}` достиг {warns}/{max_warns} варнов — заблокирован."
                else:
                    result_msg = f"⚠️ Пользователь `{target_user_id}` получил предупреждение {warns}/{max_warns}."
            else:
                result_msg = f"⚠️ Предупреждение выдано пользователю `{target_user_id}`."

        elif action == "whitelist":
            if db:
                await db.get_or_create_member(group_id, target_user_id)
                await db.set_whitelist(group_id, target_user_id, True)
            result_msg = f"✅ Пользователь `{target_user_id}` добавлен в белый список."

        elif action == "blacklist":
            if db:
                await db.get_or_create_member(group_id, target_user_id)
                await db.set_blacklist(group_id, target_user_id, True)
            result_msg = f"🚫 Пользователь `{target_user_id}` добавлен в чёрный список."

        elif action == "shadowban":
            if db:
                await db.get_or_create_member(group_id, target_user_id)
                await db.set_shadowban(group_id, target_user_id, True)
            result_msg = f"👻 Теневой бан применён к пользователю `{target_user_id}`."

    except TelegramError as e:
        result_msg = f"❌ Ошибка выполнения действия: {e}"

    await message.reply_text(result_msg, parse_mode="Markdown")
    return True  # Handled
