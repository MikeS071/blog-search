from __future__ import annotations

import os
import asyncio
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from social_scheduler.core.paths import ensure_directories
from social_scheduler.core.service import SocialSchedulerService
from social_scheduler.core.telegram_control import TelegramControl


class TelegramRuntime:
    def __init__(self) -> None:
        ensure_directories()
        self.token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.allowed_user_id = os.getenv("TELEGRAM_ALLOWED_USER_ID", "")
        self.service = SocialSchedulerService()
        self.control = TelegramControl(self.service, self.allowed_user_id)

    async def on_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        await update.message.reply_text("Social Scheduler bot online.")

    async def on_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        text = (update.message.text or "").strip()
        result = self.control.handle_command(str(update.effective_user.id), text)
        token_id = self._confirm_token_from_message(result.message)
        if result.ok and token_id:
            keyboard = InlineKeyboardMarkup(
                [[InlineKeyboardButton("Confirm", callback_data=f"confirm:{token_id}")]]
            )
            await update.message.reply_text(result.message, reply_markup=keyboard)
            return
        await update.message.reply_text(result.message)

    async def on_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        query = update.callback_query
        await query.answer()
        data = query.data or ""
        user_id = str(update.effective_user.id)

        if data.startswith("approve:"):
            req_id = data.split(":", 1)[1]
            result = self.control.handle_command(user_id, f"/approve {req_id}")
            if not result.ok:
                refreshed = self.control.refresh_expired_request(req_id)
                if refreshed:
                    await query.edit_message_text("Action card expired. Sent a fresh decision card.")
                    if query.message:
                        await query.message.reply_text(
                            refreshed.message,
                            reply_markup=self._decision_keyboard(refreshed.id),
                        )
                    return
            await query.edit_message_text(result.message)
            return
        if data.startswith("reject:"):
            req_id = data.split(":", 1)[1]
            result = self.control.handle_command(user_id, f"/reject {req_id}")
            if not result.ok:
                refreshed = self.control.refresh_expired_request(req_id)
                if refreshed:
                    await query.edit_message_text("Action card expired. Sent a fresh decision card.")
                    if query.message:
                        await query.message.reply_text(
                            refreshed.message,
                            reply_markup=self._decision_keyboard(refreshed.id),
                        )
                    return
            await query.edit_message_text(result.message)
            return
        if data.startswith("confirm:"):
            tok_id = data.split(":", 1)[1]
            result = self.control.handle_command(user_id, f"/confirm {tok_id}")
            if not result.ok:
                refreshed = self.control.refresh_expired_confirmation_token(tok_id)
                if refreshed:
                    await query.edit_message_text("Confirmation expired. Sent a fresh confirm action.")
                    if query.message:
                        await query.message.reply_text(
                            f"Confirm with /confirm {refreshed.id}",
                            reply_markup=self._confirm_keyboard(refreshed.id),
                        )
                    return
            await query.edit_message_text(result.message)
            return

        await query.edit_message_text("Unknown action")

    async def send_decision_card(self, chat_id: str, request_id: str, message: str) -> None:
        app = Application.builder().token(self.token).build()
        keyboard = self._decision_keyboard(request_id)
        async with app:
            await app.bot.send_message(chat_id=chat_id, text=message, reply_markup=keyboard)

    def build_application(self) -> Application:
        if not self.token:
            raise RuntimeError("Missing TELEGRAM_BOT_TOKEN")
        app = Application.builder().token(self.token).build()
        app.add_handler(CommandHandler("start", self.on_start))
        app.add_handler(CallbackQueryHandler(self.on_callback))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.on_text))
        app.add_handler(CommandHandler("health", self.on_text))
        app.add_handler(CommandHandler("digest", self.on_text))
        app.add_handler(CommandHandler("weekly", self.on_text))
        app.add_handler(CommandHandler("kill_on", self.on_text))
        app.add_handler(CommandHandler("kill_off", self.on_text))
        app.add_handler(CommandHandler("confirm", self.on_text))
        app.add_handler(CommandHandler("approve", self.on_text))
        app.add_handler(CommandHandler("reject", self.on_text))
        app.add_handler(CommandHandler("override", self.on_text))
        return app

    def run_polling(self) -> None:
        app = self.build_application()
        app.run_polling(close_loop=False)

    async def run_webhook(
        self,
        listen: str = "127.0.0.1",
        port: int = 8080,
        url_path: str = "/telegram",
        webhook_url: str | None = None,
    ) -> None:
        if not self.token:
            raise RuntimeError("Missing TELEGRAM_BOT_TOKEN")
        app = self.build_application()
        async with app:
            await app.initialize()
            if webhook_url:
                await app.bot.set_webhook(url=f"{webhook_url.rstrip('/')}{url_path}")
            await app.start()
            await app.updater.start_webhook(
                listen=listen,
                port=port,
                url_path=url_path.lstrip("/"),
                webhook_url=(f"{webhook_url.rstrip('/')}{url_path}" if webhook_url else None),
            )
            try:
                while True:
                    await asyncio.sleep(1)
            finally:
                await app.updater.stop()
                await app.stop()

    def _authorized(self, update: Update) -> bool:
        if not self.allowed_user_id:
            return True
        uid = str(update.effective_user.id) if update.effective_user else ""
        return uid == self.allowed_user_id

    @staticmethod
    def _confirm_token_from_message(message: str) -> str | None:
        match = re.search(r"/confirm\s+([^\s]+)", message)
        return match.group(1) if match else None

    @staticmethod
    def _decision_keyboard(request_id: str) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Approve", callback_data=f"approve:{request_id}"),
                    InlineKeyboardButton("Reject", callback_data=f"reject:{request_id}"),
                ]
            ]
        )

    @staticmethod
    def _confirm_keyboard(token_id: str) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [[InlineKeyboardButton("Confirm", callback_data=f"confirm:{token_id}")]]
        )
