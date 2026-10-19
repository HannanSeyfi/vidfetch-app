"""Small asynchronous Telegram Bot API client; credentials never enter log output."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx


class TelegramError(Exception):
    def __init__(self, code: int, description: str, retry_after: int = 0):
        self.code = code
        self.retry_after = retry_after
        # Telegram errors normally contain no token, but don't retain raw responses.
        messages = {
            401: "The bot token is invalid. Get a token from @BotFather and run again.",
            409: "Another copy of this bot is running. Stop it before starting this copy.",
            403: "Telegram could not deliver a message to this chat.",
            429: "Telegram asked the bot to slow down. Try again shortly.",
        }
        self.description = description.lower()  # Used only to classify a video-format error.
        super().__init__(messages.get(code, "Telegram could not complete the request. Try again."))


class Telegram:
    def __init__(self, token: str, *, transport: httpx.AsyncBaseTransport | None = None):
        self._client = httpx.AsyncClient(
            base_url=f"https://api.telegram.org/bot{token}/",
            transport=transport,
            timeout=httpx.Timeout(60, connect=20, write=600),
            follow_redirects=False,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def call(self, method: str, data: dict | None = None, *, files: dict | None = None):
        try:
            if files:
                response = await self._client.post(method, data=data, files=files)
            else:
                response = await self._client.post(method, json=data or {})
            body = response.json()
        except (httpx.HTTPError, ValueError):
            # httpx's exception text includes the URL, which includes the bot token.
            raise TelegramError(0, "network") from None
        if not body.get("ok"):
            raise TelegramError(
                int(body.get("error_code", response.status_code)),
                str(body.get("description", "")),
                int(body.get("parameters", {}).get("retry_after", 0)),
            )
        return body.get("result")

    async def message(self, chat_id: int, text: str, *, keyboard: list | None = None) -> dict:
        payload = {"chat_id": chat_id, "text": text, "link_preview_options": {"is_disabled": True}}
        if keyboard is not None:
            payload["reply_markup"] = {"inline_keyboard": keyboard}
        return await self.call("sendMessage", payload)

    async def edit(
        self, chat_id: int, message_id: int, text: str, *, keyboard: list | None = None
    ) -> None:
        try:
            await self.call(
                "editMessageText",
                {
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "text": text,
                    "reply_markup": {"inline_keyboard": keyboard or []},
                    "link_preview_options": {"is_disabled": True},
                },
            )
        except TelegramError as error:
            if error.code in {401, 409}:
                raise
            # Deleted status messages, duplicate edits and temporary network failures
            # must not destroy a successfully downloaded/compressed file.

    async def acknowledge(self, query_id: str, text: str = "") -> None:
        try:
            await self.call("answerCallbackQuery", {"callback_query_id": query_id, "text": text})
        except TelegramError:
            pass  # An old callback may expire before Telegram receives the answer.

    async def upload(
        self, chat_id: int, path: Path, caption: str, *, width: int, height: int, duration: int
    ) -> None:
        payload = {
            "chat_id": str(chat_id),
            "caption": caption,
            "supports_streaming": "true",
            "width": str(width),
            "height": str(height),
            "duration": str(duration),
        }
        with path.open("rb") as video:
            try:
                await self.call(
                    "sendVideo", payload, files={"video": ("VidFetch.mp4", video, "video/mp4")}
                )
            except TelegramError as error:
                # Only an explicit format rejection justifies resending as a document.
                # Never retry ambiguous network/timeouts: the first upload may have arrived.
                if error.code != 400 or not any(
                    word in error.description
                    for word in (
                        "video_content_type",
                        "video_content_invalid",
                        "wrong type of the web page content",
                    )
                ):
                    raise
                video.seek(0)
                await self.call(
                    "sendDocument",
                    {"chat_id": str(chat_id), "caption": caption},
                    files={"document": ("VidFetch.mp4", video, "video/mp4")},
                )

    async def updates(self, offset: int):
        return await self.call(
            "getUpdates",
            {"offset": offset, "timeout": 30, "allowed_updates": ["message", "callback_query"]},
        )

    async def poll(self):
        offset = 0
        backoff = 1
        while True:
            try:
                updates = await self.updates(offset)
                backoff = 1
                for update in updates:
                    yield update
                    offset = max(offset, update["update_id"] + 1)
            except TelegramError as error:
                if error.code in {401, 409}:
                    raise
                await asyncio.sleep(min(max(backoff, error.retry_after), 60))
                backoff = min(backoff * 2, 30)
