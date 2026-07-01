"""
NeuroAntiSpam - Admin Handler
Commands for group administrators.
"""

import logging
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import TelegramError

logger = logging.getLogger(__name__)


def admin_only(func):
    """Decorator: only group admins can use this command."""
    async def wrapper(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        chat = update.effective_chat
        if not user or not chat:
            return
        try:
            member = await chat.get_member(user.id)
            if member.status not in ("administrator", "creator"):
                await update.message.reply_text("❌ Только администраторы могут использовать эту команду.")
                return
        except TelegramError:
            return
        return await func(self, update, context)
    return wrapper


class AdminHandler:
    def __init__(self, db, config):
        self.db = db
        self.config = config

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat = update.effective_chat
        if chat.type == "private":
            text = (
                "👋 <b>Привет! Я NeuroAntiSpam</b>\n\n"
                "🤖 Умный антиспам-бот с ИИ для Telegram-групп.\n\n"
                "<b>Как добавить меня в группу:</b>\n"
                "1. Добавь меня как участника группы\n"
                "2. Назначь меня администратором\n"
                "3. Дай права: удаление сообщений, бан участников\n\n"
                "🌐 Панель управления: /settings\n"
                "📊 Статистика: /stats\n"
                "❓ Помощь: /help"
            )
        else:
            group = await self.db.get_or_create_group(chat.id, chat.title, chat.username)
            text = (
                f"✅ <b>NeuroAntiSpam активирован</b> в <b>{chat.title}</b>\n\n"
                f"🛡 Режим защиты: <b>{group.get_setting('mode', 'medium').upper()}</b>\n"
                f"📊 /stats — статистика\n"
                f"⚙️ /settings — настройки\n"
                f"❓ /help — все команды"
            )
        await update.message.reply_text(text, parse_mode="HTML")

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = (
            "📖 <b>Команды NeuroAntiSpam</b>\n\n"
            "<b>👮 Модерация:</b>\n"
            "/ban @user — заблокировать\n"
            "/kick @user — удалить из группы\n"
            "/mute @user [мин] — заглушить\n"
            "/unmute @user — снять мут\n"
            "/warn @user — предупреждение\n"
            "/unwarn @user — снять предупреждение\n"
            "/warns @user — проверить предупреждения\n\n"
            "<b>📋 Списки:</b>\n"
            "/whitelist @user — добавить в белый список\n"
            "/blacklist @user — добавить в чёрный список\n\n"
            "<b>🧠 Обучение:</b>\n"
            "/addspam [текст] — добавить спам-фразу\n"
            "/report — пожаловаться на сообщение (ответом)\n\n"
            "<b>⚙️ Настройки:</b>\n"
            "/settings — панель настроек\n"
            "/mode soft|medium|hard — режим защиты\n"
            "/setlang ru|en|any — языковой фильтр\n\n"
            "<b>📊 Статистика:</b>\n"
            "/stats — статистика группы\n\n"
            "🌐 Веб-панель управления: " + self.config.WEBSITE_URL
        )
        await update.message.reply_text(text, parse_mode="HTML")

    @admin_only
    async def cmd_ban(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        target = await self._resolve_target(update, context)
        if not target:
            return
        user_id, username = target
        try:
            await update.effective_chat.ban_member(user_id)
            await update.message.reply_text(f"🚫 <b>{username}</b> заблокирован.", parse_mode="HTML")
        except TelegramError as e:
            await update.message.reply_text(f"❌ Ошибка: {e}")

    @admin_only
    async def cmd_kick(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        target = await self._resolve_target(update, context)
        if not target:
            return
        user_id, username = target
        try:
            await update.effective_chat.ban_member(user_id)
            await update.effective_chat.unban_member(user_id)
            await update.message.reply_text(f"👢 <b>{username}</b> удалён из группы.", parse_mode="HTML")
        except TelegramError as e:
            await update.message.reply_text(f"❌ Ошибка: {e}")

    @admin_only
    async def cmd_mute(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        target = await self._resolve_target(update, context)
        if not target:
            return
        user_id, username = target

        minutes = 60
        if context.args and len(context.args) >= 2:
            try:
                minutes = int(context.args[1])
            except ValueError:
                pass

        until = datetime.utcnow() + timedelta(minutes=minutes)
        try:
            from telegram import ChatPermissions
            await update.effective_chat.restrict_member(
                user_id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until,
            )
            await self.db.set_mute(update.effective_chat.id, user_id, until)
            await update.message.reply_text(
                f"🔇 <b>{username}</b> заглушен на <b>{minutes} мин</b>.", parse_mode="HTML"
            )
        except TelegramError as e:
            await update.message.reply_text(f"❌ Ошибка: {e}")

    @admin_only
    async def cmd_unmute(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        target = await self._resolve_target(update, context)
        if not target:
            return
        user_id, username = target
        try:
            from telegram import ChatPermissions
            await update.effective_chat.restrict_member(
                user_id,
                permissions=ChatPermissions(
                    can_send_messages=True,
                    can_send_media_messages=True,
                    can_send_polls=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True,
                ),
            )
            await self.db.set_mute(update.effective_chat.id, user_id, None)
            await update.message.reply_text(f"🔊 <b>{username}</b> размучен.", parse_mode="HTML")
        except TelegramError as e:
            await update.message.reply_text(f"❌ Ошибка: {e}")

    @admin_only
    async def cmd_warn(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat = update.effective_chat
        target = await self._resolve_target(update, context)
        if not target:
            return
        user_id, username = target
        group = await self.db.get_or_create_group(chat.id, chat.title)
        max_warns = group.get_setting("max_warnings", self.config.MAX_WARNINGS)
        warns = await self.db.add_warning(chat.id, user_id)
        if warns >= max_warns:
            try:
                await chat.ban_member(user_id)
                await update.message.reply_text(
                    f"🚫 <b>{username}</b> достиг {warns}/{max_warns} предупреждений — заблокирован.",
                    parse_mode="HTML"
                )
            except TelegramError as e:
                await update.message.reply_text(f"❌ Ошибка бана: {e}")
        else:
            await update.message.reply_text(
                f"⚠️ <b>{username}</b> получил предупреждение <b>{warns}/{max_warns}</b>.",
                parse_mode="HTML"
            )

    @admin_only
    async def cmd_unwarn(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        target = await self._resolve_target(update, context)
        if not target:
            return
        user_id, username = target
        await self.db.reset_warnings(update.effective_chat.id, user_id)
        await update.message.reply_text(f"✅ Предупреждения <b>{username}</b> сброшены.", parse_mode="HTML")

    async def cmd_warns(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        target = await self._resolve_target(update, context)
        if not target:
            return
        user_id, username = target
        chat = update.effective_chat
        group = await self.db.get_or_create_group(chat.id, chat.title)
        max_warns = group.get_setting("max_warnings", self.config.MAX_WARNINGS)
        member = await self.db.get_or_create_member(chat.id, user_id)
        await update.message.reply_text(
            f"📋 <b>{username}</b>: {member.warnings}/{max_warns} предупреждений.", parse_mode="HTML"
        )

    @admin_only
    async def cmd_whitelist(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        target = await self._resolve_target(update, context)
        if not target:
            return
        user_id, username = target
        await self.db.get_or_create_member(update.effective_chat.id, user_id)
        await self.db.set_whitelist(update.effective_chat.id, user_id, True)
        await update.message.reply_text(f"✅ <b>{username}</b> добавлен в белый список.", parse_mode="HTML")

    @admin_only
    async def cmd_blacklist(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        target = await self._resolve_target(update, context)
        if not target:
            return
        user_id, username = target
        await self.db.get_or_create_member(update.effective_chat.id, user_id)
        await self.db.set_blacklist(update.effective_chat.id, user_id, True)
        await update.message.reply_text(f"🚫 <b>{username}</b> добавлен в чёрный список.", parse_mode="HTML")

    @admin_only
    async def cmd_add_spam_phrase(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("Использование: /addspam [фраза]")
            return
        phrase = " ".join(context.args)
        await self.db.add_spam_phrase(
            phrase=phrase,
            group_id=update.effective_chat.id,
            added_by=update.effective_user.id,
        )
        await update.message.reply_text(f"✅ Спам-фраза добавлена: <code>{phrase}</code>", parse_mode="HTML")

    @admin_only
    async def cmd_set_mode(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args or context.args[0] not in ("soft", "medium", "hard"):
            await update.message.reply_text("Использование: /mode soft|medium|hard")
            return
        mode = context.args[0]
        chat = update.effective_chat
        group = await self.db.get_or_create_group(chat.id, chat.title)
        settings = group.settings or {}
        settings["mode"] = mode
        await self.db.update_group_settings(chat.id, settings)
        labels = {"soft": "🟢 Мягкий", "medium": "🟡 Средний", "hard": "🔴 Жёсткий"}
        await update.message.reply_text(f"⚙️ Режим защиты: <b>{labels[mode]}</b>", parse_mode="HTML")

    @admin_only
    async def cmd_set_language(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args or context.args[0] not in ("ru", "en", "any"):
            await update.message.reply_text("Использование: /setlang ru|en|any")
            return
        lang = context.args[0]
        chat = update.effective_chat
        group = await self.db.get_or_create_group(chat.id, chat.title)
        settings = group.settings or {}
        settings["language_filter"] = None if lang == "any" else lang
        await self.db.update_group_settings(chat.id, settings)
        await update.message.reply_text(f"🌐 Языковой фильтр: <b>{lang}</b>", parse_mode="HTML")

    async def cmd_settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat = update.effective_chat
        url = f"{self.config.WEBSITE_URL}/dashboard"
        keyboard = [[InlineKeyboardButton("🌐 Открыть панель управления", url=url)]]
        await update.message.reply_text(
            f"⚙️ Настройки группы <b>{chat.title}</b> доступны в веб-панели:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
        )

    async def handle_settings_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        # Settings are managed via website, just redirect
        await query.edit_message_text(
            f"⚙️ Используйте веб-панель: {self.config.WEBSITE_URL}/dashboard"
        )

    async def _resolve_target(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Extract target user_id and display name from command."""
        message = update.effective_message

        # Via reply (most reliable method)
        if message.reply_to_message:
            user = message.reply_to_message.from_user
            name = f"@{user.username}" if user.username else user.full_name
            return user.id, name

        # Via numeric Telegram ID argument
        if context.args:
            arg = context.args[0]
            try:
                uid = int(arg)
                return uid, str(uid)
            except ValueError:
                # Telegram Bot API cannot resolve @username to a user_id unless
                # that user has messaged the bot before or is cached locally.
                # The reliable way is to reply to one of their messages instead.
                await message.reply_text(
                    "❌ Бот не может найти пользователя по @username напрямую "
                    "(ограничение Telegram API).\n\n"
                    "Используйте один из вариантов:\n"
                    "• Ответьте этой командой на сообщение пользователя\n"
                    "• Укажите числовой Telegram ID (например: /ban 123456789)"
                )
                return None

        await message.reply_text("❌ Укажите пользователя: ответьте на сообщение или укажите @username.")
        return None
