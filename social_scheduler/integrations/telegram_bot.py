from __future__ import annotations

import os
import time

import httpx


class TelegramNotifier:
    def __init__(self) -> None:
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.allowed_user_id = os.getenv("TELEGRAM_ALLOWED_USER_ID")

    def send_message(self, text: str, critical: bool = False) -> None:
        if not self.token or not self.allowed_user_id:
            return
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = self._message_payload(text=text, critical=critical)
        delays = [0.5, 1.5, 3.0]
        last_exc: Exception | None = None
        for idx, delay in enumerate(delays, start=1):
            try:
                with httpx.Client(timeout=10.0) as client:
                    resp = client.post(url, json=payload)
                    resp.raise_for_status()
                return
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if idx < len(delays):
                    time.sleep(delay)
        raise RuntimeError(f"Telegram send failed after retries: {last_exc}")

    def send_decision_card(self, request_id: str, message: str) -> None:
        if not self.token or not self.allowed_user_id:
            return
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = self._message_payload(
            text=message,
            critical=False,
            reply_markup={
                "inline_keyboard": [
                    [
                        {"text": "Approve", "callback_data": f"approve:{request_id}"},
                        {"text": "Reject", "callback_data": f"reject:{request_id}"},
                    ]
                ]
            },
        )
        delays = [0.5, 1.5, 3.0]
        last_exc: Exception | None = None
        for idx, delay in enumerate(delays, start=1):
            try:
                with httpx.Client(timeout=10.0) as client:
                    resp = client.post(url, json=payload)
                    resp.raise_for_status()
                return
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if idx < len(delays):
                    time.sleep(delay)
        raise RuntimeError(f"Telegram decision card send failed after retries: {last_exc}")

    def _message_payload(self, text: str, critical: bool, reply_markup: dict | None = None) -> dict:
        payload = {
            "chat_id": self.allowed_user_id,
            "text": text,
            "disable_notification": not critical,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return payload
