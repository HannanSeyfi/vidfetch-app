"""Small asynchronous Telegram Bot API client; credentials never enter log output."""

from __future__ import annotations

import asyncio
import mimetypes
from pathlib import Path
from urllib.parse import urlsplit

import httpx

CLOUD_UPLOAD_LIMIT = 49_000_000
LOCAL_UPLOAD_LIMIT = 1_950_000_000  # Headroom below Telegram's documented 2000 MB ceiling.


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
            503: "The local Telegram API server stopped. Restart the bot cell.",
        }
        self.description = description.lower()  # Used only to classify a video-format error.
        super().__init__(messages.get(code, "Telegram could not complete the request. Try again."))


class Telegram:
    def __init__(
        self,
        token: str,
        *,
        api_root: str = "https://api.telegram.org",
        local_files: bool = False,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        address = urlsplit(api_root)
        if (
            address.username
            or address.password
            or address.query
            or address.fragment
            or address.path not in {"", "/"}
        ):
            raise ValueError("Use a Telegram API origin without credentials or a path.")
        loopback = address.hostname in {"127.0.0.1", "::1"}
        if address.scheme != "https" and not (address.scheme == "http" and loopback):
            raise ValueError("Telegram API connections require HTTPS or a loopback address.")
        if local_files and not loopback:
            raise ValueError("Local file delivery requires a server on the same machine.")
        self.local_files = local_files
        self.api_root = api_root.rstrip("/")
        self.server_process = None
        self.upload_limit = LOCAL_UPLOAD_LIMIT if local_files else CLOUD_UPLOAD_LIMIT
        self._client = httpx.AsyncClient(
            base_url=f"{api_root.rstrip('/')}/bot{token}/",
            transport=transport,
            timeout=httpx.Timeout(60, connect=20, write=600),
            follow_redirects=False,
            trust_env=not local_files,  # Loopback requests must not use an HTTP proxy.
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def call(
        self,
        method: str,
        data: dict | None = None,
        *,
        files: dict | None = None,
        uploading: bool = False,
    ):
        if self.server_process is not None and self.server_process.returncode is not None:
            raise TelegramError(503, "local server stopped")
        options = {"timeout": httpx.Timeout(3600, connect=20, write=3600)} if uploading else {}
        try:
            if files:
                response = await self._client.post(method, data=data, files=files, **options)
            else:
                response = await self._client.post(method, json=data or {}, **options)
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

    async def send_file(self, method: str, field: str, path: Path, payload: dict) -> None:
        size = path.stat().st_size
        if not 0 < size <= self.upload_limit:
            raise TelegramError(413, "file size")
        if self.local_files:
            await self.call(method, {**payload, field: path.resolve().as_uri()}, uploading=True)
        else:
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            if path.suffix == ".m4a":
                content_type = "audio/mp4"
            with path.open("rb") as stream:
                await self.call(
                    method,
                    payload,
                    files={field: (path.name, stream, content_type)},
                    uploading=True,
                )

    async def upload_document(self, chat_id: int, path: Path, caption: str) -> None:
        await self.send_file(
            "sendDocument",
            "document",
            path,
            {"chat_id": str(chat_id), "caption": caption, "parse_mode": "HTML"},
        )

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
            "parse_mode": "HTML",
            "supports_streaming": "true",
            "width": str(width),
            "height": str(height),
            "duration": str(duration),
        }
        try:
            await self.send_file("sendVideo", "video", path, payload)
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
            await self.upload_document(chat_id, path, caption)

    async def updates(self, offset: int):
        return await self.call(
            "getUpdates",
            {"offset": offset, "timeout": 30, "allowed_updates": ["message", "callback_query"]},
        )

    async def upload_audio(
        self, chat_id: int, path: Path, caption: str, *, title: str, duration: int
    ) -> None:
        payload = {
            "chat_id": str(chat_id),
            "caption": caption,
            "parse_mode": "HTML",
            "title": title,
            "duration": str(duration),
        }
        await self.send_file("sendAudio", "audio", path, payload)

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
                if error.code in {401, 409, 503}:
                    raise
                await asyncio.sleep(min(max(backoff, error.retry_after), 60))
                backoff = min(backoff * 2, 30)
