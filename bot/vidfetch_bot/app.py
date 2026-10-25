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
from contextlib import aclosing
from dataclasses import dataclass
from html import escape
from pathlib import Path

from . import files, media
from .access import AccessStore, valid_id
from .cookies import CookieStore, UserCookieStores
from .personal import OWNER_HELP, PersonalControls
from .telegram import Telegram, TelegramError

HELP = (
    "Send a link and choose a video quality or Audio only. Each button shows an estimated file size; "
    "video sizes include audio where available. Audio only extracts the original audio track. "
    "Original quality is preserved with the local Telegram server. Files above its per-file limit "
    "are delivered as numbered parts with a verified Python joiner. Download every part to rejoin.\n\n"
    "Sizes are estimates. "
    "Only one request is processed at a time by this bot.\n\n"
    "/cancel — cancel your current request\n/status — show your request status\n"
    "/id — show your Telegram user ID\n/cookies — show site cookie status\n/help — show these instructions"
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
        cookie_store: CookieStore | None = None,
        access: AccessStore | None = None,
        user_cookies: UserCookieStores | None = None,
    ):
        self.api = api
        self.allowed_users = allowed_users or set()
        if cookie_store and cookie_store.has_enabled() and not self.allowed_users:
            raise ValueError("Set allowed_user_ids before enabling account cookies.")
        self.cookie_store = cookie_store
        if user_cookies and (not access or cookie_store):
            raise ValueError("Personal cookies require private access and cannot share a global cookie store.")
        self.access = access
        self.workspace = workspace
        self.max_jobs = max_jobs
        self.jobs: dict[tuple[int, int], Job] = {}
        self.selections: dict[str, Selection] = {}
        self.slot = asyncio.Semaphore(1)
        self.controls = PersonalControls(self, access, user_cookies) if user_cookies else None

    def is_allowed(self, user_id: int) -> bool:
        return self.access.allows(user_id) if self.access else not self.allowed_users or user_id in self.allowed_users

    def cookie_options(self, owner: tuple[int, int]) -> dict:
        if not self.is_allowed(owner[1]):
            raise media.MediaError("Your access to this bot was removed.")
        if self.controls:
            return {"cookie_store": self.controls.stores.for_user(owner[1])}
        if self.cookie_store and self.cookie_store.has_enabled() and not self.allowed_users:
            raise media.MediaError(
                "Account cookies require an explicit Telegram user allowlist. Stop the bot and set allowed_user_ids."
            )
        return {"cookie_store": self.cookie_store} if self.cookie_store else {}

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
        if not valid_id(user.get("id")) or not chat.get("id"):
            return
        if chat.get("type") != "private":
            if callback:
                await self.api.acknowledge(callback["id"], "Use the bot in a private chat.")
            return
        owner = (chat["id"], user["id"])
        text = (message.get("text") or "").strip()
        command = text.split(maxsplit=1)[0].split("@")[0].lower() if text else ""
        if not callback and command == "/id":
            await self.api.message(chat["id"], f"Your Telegram user ID: {user['id']}")
            return
        if not self.is_allowed(user["id"]):
            if callback:
                await self.api.acknowledge(callback["id"], "This bot is private.")
            else:
                await self.api.message(
                    chat["id"], "This bot is private. Ask its owner for approval. Use /id to find your Telegram user ID."
                    if self.access else "This bot is private."
                )
            return
        if callback:
            if self.controls and callback.get("data", "").startswith("c:"):
                await self.controls.callback(callback, owner)
            else:
                await self.choose(callback, owner)
            return
        if self.controls and await self.controls.admin(owner, text or " "):
            return
        if self.controls and message.get("document"):
            await self.controls.document(message, owner)
            return
        if command in {"/start", "/help"}:
            extra = OWNER_HELP if self.access and user["id"] in self.access.owners else ""
            await self.api.message(chat["id"], HELP + extra)
        elif command == "/cookies":
            if self.controls:
                await self.controls.show(owner)
                return
            await self.api.message(
                chat["id"],
                self.cookie_store.status()
                if self.cookie_store
                else "No imported cookies. Configure optional cookies on the bot host.",
            )
        elif command == "/cancel":
            if self.controls:
                self.controls.pending.pop(owner, None)
                self.controls.expire(owner)
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
        if not self.is_allowed(owner[1]):
            await self.api.message(owner[0], "This bot is private.")
            return False
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
                    if not self.is_allowed(owner[1]):
                        await status("Your access to this bot was removed.")
                        return
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
        options = self.cookie_options(owner)
        analysis = await media.analyze(
            url, folder, preserve_quality=self.api.local_files, **options
        )
        self.expire_menus(owner)
        key = secrets.token_urlsafe(8)
        self.selections[key] = Selection(owner, url, analysis, time.monotonic() + 1800)
        keyboard = [
            [
                {
                    "text": quality.label_for(
                        self.api.upload_limit, preserve_quality=self.api.local_files
                    ),
                    "callback_data": f"q:{key}:{index}",
                }
            ]
            for index, quality in enumerate(analysis.qualities)
        ]
        try:
            await self.api.message(
                owner[0],
                f"{analysis.title}\n\nChoose a quality. Sizes include audio "
                "when known. Audio only extracts the audio track. "
                + (
                    "Original quality is preserved. Files above the per-file limit are sent as "
                    "numbered file parts that must be rejoined after download."
                    if self.api.local_files
                    else "Cloud mode compresses files to fit 49 MB."
                )
                + "\n\nMenu expires in 30 minutes.",
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
            options = self.cookie_options(owner)
            source = await media.download(selection.url, quality, folder, **options)
            if quality.audio_only:
                audio = await media.prepare_audio(
                    source,
                    status,
                    limit=self.api.upload_limit,
                    preserve_quality=self.api.local_files,
                )
                size = audio.path.stat().st_size
                if size > self.api.upload_limit:
                    await self.deliver_parts(owner[0], audio.path, selection, status)
                    return
                await status(f"Uploading {media.format_size(size)} of audio to Telegram…")
                details = f"Audio only · {media.format_size(size)}"
                if audio.compressed:
                    details += " · compressed for Telegram"
                caption = delivery_caption(selection.analysis.title, details, selection.url)
                if audio.document:
                    await self.api.upload_document(owner[0], audio.path, caption)
                else:
                    await self.api.upload_audio(
                        owner[0],
                        audio.path,
                        caption,
                        title=selection.analysis.title,
                        duration=math.ceil(audio.probe.duration),
                    )
                await status("Audio sent. Send another link whenever you're ready.")
                return
            prepared = await media.prepare_video(
                source, status, limit=self.api.upload_limit, preserve_quality=self.api.local_files
            )
            size = prepared.path.stat().st_size
            if size > self.api.upload_limit:
                await self.deliver_parts(owner[0], prepared.path, selection, status)
                return
            await status(f"Uploading {media.format_size(size)} to Telegram…")
            result_quality = f"{prepared.probe.height}p"
            details = f"{result_quality} · {media.format_size(size)}"
            if prepared.compressed:
                details += " · compressed for Telegram"
            caption = delivery_caption(selection.analysis.title, details, selection.url)
            if prepared.document:
                await self.api.upload_document(owner[0], prepared.path, caption)
            else:
                await self.api.upload(
                    owner[0],
                    prepared.path,
                    caption,
                    width=prepared.probe.width,
                    height=prepared.probe.height,
                    duration=math.ceil(prepared.probe.duration),
                )
            await status("Sent. Send another video link whenever you're ready.")

        if await self.schedule(owner, deliver, status_message=callback["message"]):
            self.selections.pop(match[1], None)

    async def deliver_parts(
        self, chat_id: int, path: Path, selection: Selection, status: media.Status
    ) -> None:
        if not self.api.local_files:
            raise media.MediaError("The prepared file exceeds the cloud upload budget.")
        name = f"VidFetch-{secrets.token_hex(4)}{path.suffix}"
        size = path.stat().st_size
        count = (size + self.api.upload_limit - 1) // self.api.upload_limit
        await self.api.message(
            chat_id,
            f"This file needs {count} parts because Telegram limits individual files. "
            "Quality is preserved. Download all parts and the joiner into one folder, then run "
            "the joiner with Python 3 to restore the original file. Parts do not play separately.",
        )
        await status("Verifying the original file before sending its parts…")
        digest = await files.file_hash(path)
        async with aclosing(files.file_parts(path, self.api.upload_limit, name)) as parts:
            async for part, index, total in parts:
                await status(f"Uploading file part {index}/{total}…")
                await self.api.upload_document(
                    chat_id,
                    part,
                    delivery_caption(
                        selection.analysis.title,
                        f"Original quality · file part {index}/{total}",
                        selection.url,
                    ),
                )
        joiner = path.parent / f"join-{name}.py"
        joiner.write_text(files.join_program(name, count, size, digest), encoding="utf-8")
        await self.api.upload_document(
            chat_id,
            joiner,
            "Save beside all parts and run with Python 3. "
            "The original file is restored only after its size and SHA-256 match.",
        )
        await status(
            f"Sent all {count} parts and the joiner. Download them together to restore the file."
        )

    async def cancel_user(self, user_id: int) -> None:
        self.selections = {key: menu for key, menu in self.selections.items() if menu.owner[1] != user_id}
        if self.controls:
            self.controls.forget_controls(user_id)
        tasks = [job.task for owner, job in self.jobs.items() if owner[1] == user_id]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def close(self) -> None:
        tasks = [job.task for job in self.jobs.values()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.jobs.clear()
        self.selections.clear()
        if self.controls:
            self.controls.menus.clear()
            self.controls.pending.clear()


async def run_bot(
    token: str,
    *,
    allowed_users: set[int] | None = None,
    api: Telegram | None = None,
    cookie_store: CookieStore | None = None,
    access: AccessStore | None = None,
    user_cookies: UserCookieStores | None = None,
) -> None:
    """Await directly in Colab; interrupt the running cell to shut down cleanly."""
    if not re.fullmatch(r"\d{5,20}:[A-Za-z0-9_-]{20,}", token.strip()):
        print("Enter the complete bot token from @BotFather, including the colon.")
        return
    # Even DEBUG logging must not expose URLs containing Telegram credentials.
    if cookie_store and cookie_store.has_enabled() and not allowed_users:
        print(
            "Set allowed_user_ids to your Telegram user ID before enabling account cookies. Use /id with cookies disabled to find it."
        )
        return
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            print(f"Missing {tool}. Run the setup cell first.")
            return
    owns_api = api is None
    api = api or Telegram(token.strip())
    bot = Bot(api, allowed_users=allowed_users, cookie_store=cookie_store, access=access, user_cookies=user_cookies)
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
                    {"command": "cookies", "description": "Manage your personal site cookies" if user_cookies else "Show site cookie status"},
                    {"command": "help", "description": "Show instructions"},
                ]
            },
        )
        print(
            f"VidFetch is running: https://t.me/{identity['username']}\n"
            "Open that bot in Telegram and send /start, then a video link.\n"
            "Keep this process running. Stop it before starting another copy."
        )
        if access:
            print(
                f"Private access enabled: {len(access.owners)} owner(s), {len(access.users)} approved user(s). "
                "Personal cookie controls are available through /cookies."
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
        if owns_api:
            await api.close()
        print("VidFetch stopped. Start the process again to restart it.")
