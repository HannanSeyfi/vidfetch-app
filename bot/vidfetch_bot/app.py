"""Private-chat bot with expiring, owner-bound quality menus and bounded jobs."""

from __future__ import annotations

import asyncio
import logging
import math
import re
import secrets
import shutil
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from html import escape
from pathlib import Path

from . import media
from .telegram import Telegram, TelegramError

HELP = (
    "Send a link and choose a video quality or Audio only. Each button shows an estimated file size; "
    "video sizes include audio where available. Audio only sends an M4A file in Telegram's audio player. "
    "Oversized videos and audio are automatically compressed for Telegram.\n\n"
    "Sizes are estimates; compression may reduce resolution and detail. "
    "Only one request is processed at a time in this Colab session.\n\n"
    "/cancel — cancel your current request\n/status — show your request status\n"
    "/id — show your Telegram user ID\n/help — show these instructions"
)


def delivery_caption(title: str, details: str, url: str) -> str:
    """Keep the full source URL clickable, including URLs beyond the caption limit."""
    visible = f"{title}\n{details}\n\nSource: {url}"
    # Telegram counts entities in UTF-16 units. Use a short link label when the
    # full visible URL would exceed the caption budget; the href stays intact.
    label = url if len(visible.encode("utf-16-le")) // 2 <= 1024 else "Original link"
    return (
        f"{escape(title)}\n{escape(details)}\n\n"
        f'Source: <a href="{escape(url, quote=True)}">{escape(label)}</a>'
    )


@dataclass
class Selection:
    owner: tuple[int, int]
    url: str
    analysis: media.Analysis
    expires: float


@dataclass
class Job:
    task: asyncio.Task
    status: str = "Waiting in the queue…"


class Bot:
    def __init__(
        self,
        api: Telegram,
        *,
        allowed_users: set[int] | None = None,
        workspace: Path | None = None,
        max_jobs: int = 5,
    ):
        self.api = api
        self.allowed_users = allowed_users or set()
        self.workspace = workspace
        self.max_jobs = max_jobs
        self.jobs: dict[tuple[int, int], Job] = {}
        self.selections: dict[str, Selection] = {}
        self.slot = asyncio.Semaphore(1)

    def expire_menus(self, owner: tuple[int, int] | None = None) -> None:
        now = time.monotonic()
        self.selections = {
            key: value
            for key, value in self.selections.items()
            if value.expires > now and value.owner != owner
        }
        # Bound memory even if many people discover an unrestricted bot.
        while len(self.selections) >= 200:
            self.selections.pop(next(iter(self.selections)))

    async def handle(self, update: dict) -> None:
        callback = update.get("callback_query")
        message = callback.get("message", {}) if callback else update.get("message", {})
        user = callback.get("from", {}) if callback else message.get("from", {})
        chat = message.get("chat", {})
        if not user.get("id") or not chat.get("id"):
            return
        if chat.get("type") != "private":
            if callback:
                await self.api.acknowledge(callback["id"], "Use the bot in a private chat.")
            return
        owner = (chat["id"], user["id"])
        if self.allowed_users and user["id"] not in self.allowed_users:
            if callback:
                await self.api.acknowledge(callback["id"], "This bot is private.")
            else:
                await self.api.message(chat["id"], "This bot is private.")
            return
        if callback:
            await self.choose(callback, owner)
            return
        text = (message.get("text") or "").strip()
        command = text.split(maxsplit=1)[0].split("@")[0].lower() if text else ""
        if command in {"/start", "/help"}:
            await self.api.message(chat["id"], HELP)
        elif command == "/id":
            await self.api.message(chat["id"], f"Your Telegram user ID: {user['id']}")
        elif command == "/cancel":
            self.expire_menus(owner)
            job = self.jobs.get(owner)
            if job:
                job.task.cancel()
                await asyncio.gather(job.task, return_exceptions=True)
            await self.api.message(
                chat["id"], "Cancelled." if job else "No active request. Old quality menus cleared."
            )
        elif command == "/status":
            await self.api.message(
                chat["id"],
                self.jobs[owner].status
                if owner in self.jobs
                else "Ready. Send a link or choose a quality from your latest menu.",
            )
        elif text.startswith(("https://", "http://")) and len(text.split()) == 1:
            await self.schedule(
                owner, lambda status, folder: self.inspect(text, owner, status, folder)
            )
        else:
            await self.api.message(chat["id"], "Send one video link, or use /help.")

    async def schedule(
        self, owner: tuple[int, int], action: Callable, *, status_message: dict | None = None
    ) -> bool:
        if owner in self.jobs:
            await self.api.message(
                owner[0], "You already have a request. Use /cancel before starting another."
            )
            return False
        if len(self.jobs) >= self.max_jobs:
            await self.api.message(
                owner[0], "The queue is full. Please try again after a video finishes."
            )
            return False
        notice = status_message or await self.api.message(owner[0], "Waiting in the queue…")

        async def status(text: str) -> None:
            if job := self.jobs.get(owner):
                job.status = text
            await self.api.edit(owner[0], notice["message_id"], text)

        async def work() -> None:
            try:
                await status("Waiting in the queue…")
                async with self.slot:
                    with tempfile.TemporaryDirectory(
                        prefix="vidfetch-", dir=self.workspace
                    ) as folder:
                        await action(status, Path(folder))
            except asyncio.CancelledError:
                await status("Cancelled.")
                raise
            except (media.MediaError, TelegramError) as error:
                await status(str(error))
            except Exception as error:
                logging.getLogger(__name__).warning("Request failed (%s)", type(error).__name__)
                await status("Something went wrong. Send the link again or try another quality.")
            finally:
                self.jobs.pop(owner, None)

        task = asyncio.create_task(work())
        self.jobs[owner] = Job(task)

        def finished(done: asyncio.Task) -> None:
            if (job := self.jobs.get(owner)) and job.task is done:
                self.jobs.pop(owner, None)
            if not done.cancelled() and (error := done.exception()):
                logging.getLogger(__name__).warning("Request stopped (%s)", type(error).__name__)

        task.add_done_callback(finished)
        return True

    async def inspect(
        self, url: str, owner: tuple[int, int], status: media.Status, folder: Path
    ) -> None:
        await status("Finding available video qualities…")
        analysis = await media.analyze(url, folder)
        self.expire_menus(owner)
        key = secrets.token_urlsafe(8)
        self.selections[key] = Selection(owner, url, analysis, time.monotonic() + 1800)
        keyboard = [
            [{"text": quality.label, "callback_data": f"q:{key}:{index}"}]
            for index, quality in enumerate(analysis.qualities)
        ]
        try:
            await self.api.message(
                owner[0],
                f"{analysis.title}\n\nChoose a quality. Sizes include audio "
                "when known. Audio only sends an M4A audio track. "
                "“compress” means the estimate exceeds the upload budget; "
                "the delivered file may have lower quality.\n\nMenu expires in 30 minutes.",
                keyboard=keyboard,
            )
        except BaseException:
            self.selections.pop(key, None)
            raise
        await status("Qualities ready. Choose a button in the message below.")

    async def choose(self, callback: dict, owner: tuple[int, int]) -> None:
        self.expire_menus()
        match = re.fullmatch(r"q:([A-Za-z0-9_-]+):(\d{1,3})", callback.get("data", ""))
        selection = self.selections.get(match[1]) if match else None
        index = int(match[2]) if match else -1
        if (
            not selection
            or selection.owner != owner
            or not 0 <= index < len(selection.analysis.qualities)
        ):
            await self.api.acknowledge(callback["id"], "This menu expired. Send the link again.")
            return
        await self.api.acknowledge(callback["id"])
        quality = selection.analysis.qualities[index]

        async def deliver(status: media.Status, folder: Path) -> None:
            choice = (
                "audio"
                if quality.audio_only
                else (f"{quality.height}p" if quality.height else "best available video")
            )
            await status(f"Downloading {choice}…")
            source = await media.download(selection.url, quality, folder)
            if quality.audio_only:
                audio = await media.prepare_audio(source, status)
                size = audio.path.stat().st_size
                if size > media.UPLOAD_LIMIT:
                    raise media.MediaError(
                        "The prepared audio exceeds the upload budget. Try a shorter clip."
                    )
                await status(f"Uploading {media.format_size(size)} of audio to Telegram…")
                details = f"Audio only · {media.format_size(size)}"
                if audio.compressed:
                    details += " · compressed for Telegram"
                await self.api.upload_audio(
                    owner[0],
                    audio.path,
                    delivery_caption(selection.analysis.title, details, selection.url),
                    title=selection.analysis.title,
                    duration=math.ceil(audio.probe.duration),
                )
                await status("Audio sent. Send another link whenever you're ready.")
                return
            prepared = await media.prepare_video(source, status)
            size = prepared.path.stat().st_size
            if size > media.UPLOAD_LIMIT:
                raise media.MediaError(
                    "The prepared file exceeds the upload budget. Try a shorter video."
                )
            await status(f"Uploading {media.format_size(size)} to Telegram…")
            result_quality = f"{prepared.probe.height}p"
            details = f"{result_quality} · {media.format_size(size)}"
            if prepared.compressed:
                details += " · compressed for Telegram"
            await self.api.upload(
                owner[0],
                prepared.path,
                delivery_caption(selection.analysis.title, details, selection.url),
                width=prepared.probe.width,
                height=prepared.probe.height,
                duration=math.ceil(prepared.probe.duration),
            )
            await status("Sent. Send another video link whenever you're ready.")

        if await self.schedule(owner, deliver, status_message=callback["message"]):
            self.selections.pop(match[1], None)

    async def close(self) -> None:
        tasks = [job.task for job in self.jobs.values()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.jobs.clear()
        self.selections.clear()


async def run_bot(token: str, *, allowed_users: set[int] | None = None) -> None:
    """Await directly in Colab; interrupt the running cell to shut down cleanly."""
    if not re.fullmatch(r"\d{5,20}:[A-Za-z0-9_-]{20,}", token.strip()):
        print("Enter the complete bot token from @BotFather, including the colon.")
        return
    # Even DEBUG logging must not expose URLs containing Telegram credentials.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            print(f"Missing {tool}. Run the setup cell first.")
            return
    api = Telegram(token.strip())
    bot = Bot(api, allowed_users=allowed_users)
    try:
        identity = await api.call("getMe")
        await api.call("deleteWebhook", {"drop_pending_updates": False})
        await api.call(
            "setMyCommands",
            {
                "commands": [
                    {"command": "start", "description": "Send a link and choose video or audio"},
                    {"command": "cancel", "description": "Cancel your current request"},
                    {"command": "status", "description": "Show request status"},
                    {"command": "id", "description": "Show your Telegram user ID"},
                    {"command": "help", "description": "Show instructions"},
                ]
            },
        )
        print(
            f"VidFetch is running: https://t.me/{identity['username']}\n"
            "Open that bot in Telegram and send /start, then a video link.\n"
            "Keep this cell running. Use its stop button to stop the bot."
        )
        async for update in api.poll():
            try:
                await bot.handle(update)
            except TelegramError as error:
                if error.code in {401, 409}:
                    raise
    except TelegramError as error:
        print(str(error))
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        await bot.close()
        await api.close()
        print("VidFetch stopped. Run this cell again to restart it.")
