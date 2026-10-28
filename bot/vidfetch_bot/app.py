"""Private and inline downloads with owner-bound menus and individually cancellable jobs."""

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
from dataclasses import dataclass, field
from html import escape
from pathlib import Path

from . import files, media
from .access import AccessStore, valid_id
from .cookie_routing import RoutedCookieStore
from .cookies import CookieStore, UserCookieStores
from .personal import OWNER_HELP, PersonalControls
from .telegram import Telegram, TelegramError

HELP = (
    "Send a link and choose a video quality or Audio only. Each button shows an estimated file size; "
    "video sizes include audio where available. Audio only extracts the original audio track. "
    "Original quality is preserved with the local Telegram server. Files above its per-file limit "
    "are delivered as numbered parts with a verified Python joiner. Download every part to rejoin.\n\n"
    "Sizes are estimates. "
    "Two requests run at once; additional requests wait in the queue. Each has its own Cancel button.\n\n"
    "/cancel — choose a request to cancel\n/status — show all your requests\n"
    "Inline: type @VidFetchRobot followed by a link in another chat, select the result, "
    "then tap Show qualities if needed. Start this bot privately once before using inline downloads.\n"
    "/id — show your Telegram user ID\n/cookies — show site cookie status\n/help — show these instructions"
)
PRIVATE_NOTICE = "This bot is private. Contact @sorrow_climax for approval. Send /id and include your Telegram user ID."


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
    inline_message_id: str | None = None


@dataclass
class InlineRequest:
    user_id: int
    url: str
    expires: float
    messages: set[str] = field(default_factory=set)


@dataclass
class Job:
    task: asyncio.Task
    owner: tuple[int, int]
    title: str
    notice: dict
    status: str = "Waiting in the queue…"


class Bot:
    def __init__(
        self,
        api: Telegram,
        *,
        allowed_users: set[int] | None = None,
        workspace: Path | None = None,
        max_jobs: int = 20,
        concurrent_jobs: int = 2,
        max_user_jobs: int = 5,
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
        self.max_user_jobs = max_user_jobs
        self.jobs: dict[str, Job] = {}
        self.selections: dict[str, Selection] = {}
        self.inline_requests: dict[str, InlineRequest] = {}
        self.slot = asyncio.Semaphore(concurrent_jobs)
        self.scheduling = asyncio.Lock()
        self.controls = PersonalControls(self, access, user_cookies) if user_cookies else None

    def is_allowed(self, user_id: int) -> bool:
        return self.access.allows(user_id) if self.access else not self.allowed_users or user_id in self.allowed_users

    def cookie_options(self, owner: tuple[int, int]) -> dict:
        if not self.is_allowed(owner[1]):
            raise media.MediaError("Your access to this bot was removed.")
        if self.controls:
            return {"cookie_store": RoutedCookieStore(self.access, self.controls.stores, owner[1])}
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
        if query := update.get("inline_query"):
            await self.inline_query(query)
            return
        if chosen := update.get("chosen_inline_result"):
            if chosen.get("inline_message_id"):
                await self.start_inline(chosen["result_id"], chosen.get("from", {}).get("id"), chosen["inline_message_id"])
            return
        callback = update.get("callback_query")
        if callback and callback.get("inline_message_id"):
            await self.inline_callback(callback)
            return
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
                await self.api.acknowledge(callback["id"], "This bot is private. Contact @sorrow_climax for approval." if self.access else "This bot is private.")
            else:
                await self.api.message(
                    chat["id"], PRIVATE_NOTICE
                    if self.access else "This bot is private."
                )
            return
        if callback:
            if callback.get("data", "").startswith("x:"):
                await self.cancel_callback(callback)
            elif self.controls and callback.get("data", "").startswith("c:"):
                await self.controls.callback(callback, owner)
            else:
                await self.choose(callback, owner)
            return
        if self.controls and await self.controls.admin(owner, text or " "):
            return
        if self.controls and message.get("document"):
            await self.controls.document(message, owner)
            return
        if self.controls and await self.controls.domain_message(owner, text):
            return
        if command in {"/start", "/help"}:
            extra = OWNER_HELP if self.access and user["id"] in self.access.owners else ""
            await self.api.message(chat["id"], HELP + extra)
        elif command == "/cookies":
            if self.controls:
                argument = text.split(maxsplit=1)
                if len(argument) == 2:
                    await self.controls.start_import(owner, argument[1])
                else:
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
                self.controls.pending_domain.pop(owner, None)
                self.controls.expire(owner)
            requested = text.split(maxsplit=1)[1].strip() if len(text.split(maxsplit=1)) == 2 else ""
            owned = {key: job for key, job in self.jobs.items() if job.owner[1] == owner[1]}
            if requested == "all":
                for key in list(owned):
                    await self.cancel_job(key)
                self.expire_menus(owner)
                await self.api.message(chat["id"], "Cancelled all your requests.")
            elif requested in owned or (not requested and len(owned) == 1):
                await self.cancel_job(requested or next(iter(owned)))
                await self.api.message(chat["id"], "Cancelled.")
            elif owned:
                await self.show_jobs(owner)
            else:
                self.expire_menus(owner)
                await self.api.message(chat["id"], "No active request. Old quality menus cleared.")
        elif command == "/status":
            await self.show_jobs(owner)
        elif text.startswith(("https://", "http://")) and len(text.split()) == 1:
            await self.schedule(
                owner, lambda status, folder: self.inspect(text, owner, status, folder), title=text
            )
        else:
            await self.api.message(chat["id"], "Send one video link, or use /help.")

    async def edit_notice(self, notice: dict, owner: tuple[int, int], text: str, *, keyboard=None):
        if notice.get("media_sent"):
            return
        if inline_id := notice.get("inline_message_id"):
            await self.api.edit_inline(inline_id, text, keyboard=keyboard)
        else:
            await self.api.edit(owner[0], notice["message_id"], text, keyboard=keyboard)

    async def show_jobs(self, owner: tuple[int, int]) -> None:
        owned = [(key, job) for key, job in self.jobs.items() if job.owner[1] == owner[1]]
        if not owned:
            await self.api.message(owner[0], "Ready. Send a link or choose a quality from a menu.")
            return
        text = "\n\n".join(f"#{key} · {job.title[:150]}\n{job.status}" for key, job in owned)
        keyboard = [[{"text": f"Cancel #{key} · {job.title[:40]}", "callback_data": f"x:{key}"}] for key, job in owned]
        await self.api.message(owner[0], text, keyboard=keyboard)

    async def cancel_job(self, key: str) -> None:
        job = self.jobs.get(key)
        if not job:
            return
        job.task.cancel()
        await asyncio.gather(job.task, return_exceptions=True)
        self.jobs.pop(key, None)
        await self.edit_notice(job.notice, job.owner, f"{job.title}\n\nCancelled.")

    async def cancel_callback(self, callback: dict) -> None:
        key = callback.get("data", "")[2:]
        job = self.jobs.get(key)
        user_id = callback.get("from", {}).get("id")
        inline_id = callback.get("inline_message_id")
        if not job or job.owner[1] != user_id or (inline_id and job.notice.get("inline_message_id") != inline_id):
            await self.api.acknowledge(callback["id"], "This request is finished or belongs to someone else.")
            return
        await self.api.acknowledge(callback["id"], "Cancelling this request…")
        await self.cancel_job(key)

    async def schedule(
        self, owner: tuple[int, int], action: Callable, *, status_message: dict | None = None,
        title: str = "VidFetch request",
    ) -> bool:
        title = title[:250]
        async with self.scheduling:
            if not self.is_allowed(owner[1]):
                if status_message:
                    await self.edit_notice(status_message, owner, "Your access to this bot was removed.")
                else:
                    await self.api.message(owner[0], PRIVATE_NOTICE if self.access else "This bot is private.")
                return False
            rejection = None
            if len(self.jobs) >= self.max_jobs:
                rejection = "The queue is full. Please try again after a video finishes."
            elif sum(job.owner[1] == owner[1] for job in self.jobs.values()) >= self.max_user_jobs:
                rejection = f"You have {self.max_user_jobs} active requests. Cancel one or wait for it to finish."
            if rejection:
                if status_message:
                    await self.edit_notice(status_message, owner, rejection, keyboard=status_message.get("retry_keyboard"))
                else:
                    await self.api.message(owner[0], rejection)
                return False
            if status_message and (inline_id := status_message.get("inline_message_id")):
                if any(job.notice.get("inline_message_id") == inline_id for job in self.jobs.values()):
                    return False
            notice = status_message or await self.api.message(owner[0], "Waiting in the queue…")
            key = secrets.token_hex(4)
            keyboard = [[{"text": "Cancel this request", "callback_data": f"x:{key}"}]]

            async def status(text: str) -> None:
                if job := self.jobs.get(key):
                    job.status = text
                await self.edit_notice(notice, owner, f"{title}\n\n{text}", keyboard=keyboard)

            async def work() -> None:
                try:
                    await status("Waiting in the queue…")
                    async with self.slot:
                        if not self.is_allowed(owner[1]):
                            await status("Your access to this bot was removed.")
                            return
                        with tempfile.TemporaryDirectory(prefix="vidfetch-", dir=self.workspace) as folder:
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
                    if job := self.jobs.get(key):
                        try:
                            # Keep a newly generated quality keyboard in place.
                            if not notice.get("quality_menu"):
                                await self.edit_notice(notice, owner, f"{title}\n\n{job.status}")
                        finally:
                            self.jobs.pop(key, None)

            task = asyncio.create_task(work())
            self.jobs[key] = Job(task, owner, title[:250], notice)

            def finished(done: asyncio.Task) -> None:
                if (job := self.jobs.get(key)) and job.task is done:
                    self.jobs.pop(key, None)
                if not done.cancelled() and (error := done.exception()):
                    logging.getLogger(__name__).warning("Request stopped (%s)", type(error).__name__)

            task.add_done_callback(finished)
            return True

    async def inline_query(self, query: dict) -> None:
        user_id = query.get("from", {}).get("id")
        if not valid_id(user_id):
            return
        if not self.is_allowed(user_id):
            await self.api.answer_inline(query["id"], [], button={"text": "Open VidFetch to request access", "start_parameter": "inline"})
            return
        url = query.get("query", "").strip()
        if not re.fullmatch(r"https?://\S+", url) or len(url) > 3500:
            await self.api.answer_inline(query["id"], [], button={"text": "Open VidFetch · paste a video link after the username", "start_parameter": "inline"})
            return
        now = time.monotonic()
        self.inline_requests = {key: request for key, request in self.inline_requests.items() if request.expires > now}
        while len(self.inline_requests) >= 200:
            self.inline_requests.pop(next(iter(self.inline_requests)))
        key = secrets.token_urlsafe(8)
        self.inline_requests[key] = InlineRequest(user_id, url, now + 1800)
        await self.api.answer_inline(query["id"], [{
            "type": "article", "id": key, "title": "Download video or audio · choose quality",
            "description": url[:200],
            "input_message_content": {
                "message_text": "VidFetch\n\n" + url + "\n\nTap Show qualities to choose video quality or audio.",
                "link_preview_options": {"is_disabled": True},
            },
            "reply_markup": {"inline_keyboard": [[{"text": "Show qualities", "callback_data": f"i:{key}"}]]},
        }])

    async def start_inline(self, key: str, user_id: int, inline_id: str) -> None:
        request = self.inline_requests.get(key)
        if not request or request.expires <= time.monotonic() or request.user_id != user_id or not self.is_allowed(user_id):
            return
        if inline_id in request.messages or len(request.messages) >= 100:
            return
        notice = {"inline_message_id": inline_id, "retry_keyboard": [[{"text": "Show qualities", "callback_data": f"i:{key}"}]]}
        owner = (user_id, user_id)
        if await self.schedule(
            owner, lambda status, folder: self.inspect(request.url, owner, status, folder, notice=notice),
            status_message=notice, title=request.url,
        ):
            request.messages.add(inline_id)

    async def inline_callback(self, callback: dict) -> None:
        user_id = callback.get("from", {}).get("id")
        if not valid_id(user_id) or not self.is_allowed(user_id):
            await self.api.acknowledge(callback["id"], "Open the bot privately to request access.")
            return
        data = callback.get("data", "")
        if data.startswith("x:"):
            await self.cancel_callback(callback)
        elif data.startswith("i:"):
            request = self.inline_requests.get(data[2:])
            if not request or request.user_id != user_id or request.expires <= time.monotonic():
                await self.api.acknowledge(callback["id"], "This result expired or belongs to someone else. Enter the link again.")
                return
            await self.api.acknowledge(callback["id"])
            await self.start_inline(data[2:], user_id, callback["inline_message_id"])
        elif data.startswith("q:"):
            await self.choose(callback, (user_id, user_id))

    def quality_keyboard(self, key: str, analysis: media.Analysis) -> list:
        return [[{"text": quality.label_for(self.api.upload_limit, preserve_quality=self.api.local_files),
                  "callback_data": f"q:{key}:{index}"}]
                for index, quality in enumerate(analysis.qualities)]

    async def inspect(
        self, url: str, owner: tuple[int, int], status: media.Status, folder: Path,
        *, notice: dict | None = None,
    ) -> None:
        await status("Finding available video qualities…")
        options = self.cookie_options(owner)
        analysis = await media.analyze(
            url, folder, preserve_quality=self.api.local_files, **options
        )
        self.expire_menus()
        key = secrets.token_urlsafe(8)
        inline_id = notice.get("inline_message_id") if notice else None
        self.selections[key] = Selection(owner, url, analysis, time.monotonic() + 1800, inline_id)
        keyboard = self.quality_keyboard(key, analysis)
        if inline_id:
            try:
                await self.api.edit_inline(inline_id, f"{analysis.title}\n\nChoose video quality or Audio only. Sizes are estimates.\nMenu expires in 30 minutes.", keyboard=keyboard)
                notice["quality_menu"] = True
            except BaseException:
                self.selections.pop(key, None)
                raise
            return
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
            or selection.inline_message_id != callback.get("inline_message_id")
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
            source = await media.download(selection.url, quality, folder, progress=status, **options)
            if quality.audio_only:
                audio = await media.prepare_audio(
                    source,
                    status,
                    limit=self.api.upload_limit,
                    preserve_quality=self.api.local_files,
                )
                size = audio.path.stat().st_size
                if size > self.api.upload_limit:
                    if selection.inline_message_id:
                        await status("This file exceeds Telegram's single-file limit. Sending original-quality parts to your private bot chat…")
                    await self.deliver_parts(owner[0], audio.path, selection, status)
                    return
                await status(f"Uploading {media.format_size(size)} of audio to Telegram…")
                details = f"Audio only · {media.format_size(size)}"
                if audio.compressed:
                    details += " · compressed for Telegram"
                caption = delivery_caption(selection.analysis.title, details, selection.url)
                if audio.document:
                    await self.send_media(owner, audio.path, caption, "document", notice)
                else:
                    await self.send_media(
                        owner,
                        audio.path,
                        caption,
                        "audio", notice,
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
                if selection.inline_message_id:
                    await status("This file exceeds Telegram's single-file limit. Sending original-quality parts to your private bot chat…")
                await self.deliver_parts(owner[0], prepared.path, selection, status)
                return
            await status(f"Uploading {media.format_size(size)} to Telegram…")
            result_quality = f"{prepared.probe.height}p"
            details = f"{result_quality} · {media.format_size(size)}"
            if prepared.compressed:
                details += " · compressed for Telegram"
            caption = delivery_caption(selection.analysis.title, details, selection.url)
            if prepared.document:
                await self.send_media(owner, prepared.path, caption, "document", notice)
            else:
                await self.send_media(
                    owner,
                    prepared.path,
                    caption,
                    "video", notice,
                    width=prepared.probe.width,
                    height=prepared.probe.height,
                    duration=math.ceil(prepared.probe.duration),
                )
            await status("Sent. Send another video link whenever you're ready.")

        notice = {"inline_message_id": selection.inline_message_id} if selection.inline_message_id else callback["message"]
        notice["retry_keyboard"] = self.quality_keyboard(match[1], selection.analysis)
        if await self.schedule(owner, deliver, status_message=notice, title=f"{selection.analysis.title} · {quality.label_for(self.api.upload_limit, preserve_quality=self.api.local_files)}"):
            self.selections.pop(match[1], None)

    async def send_media(self, owner: tuple[int, int], path: Path, caption: str, kind: str, notice: dict, **metadata) -> None:
        sender = {"video": self.api.upload, "audio": self.api.upload_audio, "document": self.api.upload_document}[kind]
        try:
            result = await sender(owner[0], path, caption, **metadata)
        except TelegramError as error:
            if notice.get("inline_message_id") and error.code == 403:
                raise media.MediaError("Open VidFetch privately and send /start once, then try this inline download again.") from None
            raise
        if not notice.get("inline_message_id"):
            return
        try:
            # Inline messages accept cached file IDs, not direct uploads. Stage the
            # file in the requesting user's private bot chat, then remove that copy.
            actual_kind = "document" if "document" in result else kind
            file_id = result[actual_kind]["file_id"]
            await self.api.edit_inline_media(notice["inline_message_id"], actual_kind, file_id, caption)
            notice["media_sent"] = True
        finally:
            if result.get("message_id"):
                await self.api.delete_message(owner[0], result["message_id"])

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
            f"Sent all {count} parts and the joiner{' to your private bot chat' if selection.inline_message_id else ''}. Download them together to restore the file."
        )

    async def cancel_user(self, user_id: int) -> None:
        self.selections = {key: menu for key, menu in self.selections.items() if menu.owner[1] != user_id}
        if self.controls:
            self.controls.forget_controls(user_id)
        self.inline_requests = {key: request for key, request in self.inline_requests.items() if request.user_id != user_id}
        tasks = [job.task for job in self.jobs.values() if job.owner[1] == user_id]
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
        self.inline_requests.clear()
        if self.controls:
            self.controls.menus.clear()
            self.controls.pending.clear()
            self.controls.pending_domain.clear()


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
                    {"command": "cancel", "description": "Choose a request to cancel"},
                    {"command": "status", "description": "Show all your requests and Cancel buttons"},
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
                "Website cookie imports: /cookies DOMAIN. Owner cookie sharing: /sharecookies and /unsharecookies."
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
