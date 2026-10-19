import asyncio
import tempfile
import time
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import AsyncMock, patch

from vidfetch_bot import media
from vidfetch_bot.app import Bot, Selection, delivery_caption, run_bot


class CaptionTests(unittest.TestCase):
    def test_caption_preserves_special_characters_and_long_clickable_url(self):
        class ParsedCaption(HTMLParser):
            def __init__(self):
                super().__init__()
                self.text = ""
                self.urls = []

            def handle_starttag(self, tag, attrs):
                self.assert_safe_tag(tag)
                self.urls.append(dict(attrs)["href"])

            def assert_safe_tag(self, tag):
                if tag != "a":
                    raise AssertionError("The title introduced unexpected HTML markup")

            def handle_data(self, data):
                self.text += data

        title = 'A <video> & "music" 🎵'
        for url in ("https://example.com/watch?v=1&list=2", "https://example.com/" + "x" * 2000):
            with self.subTest(url_length=len(url)):
                parser = ParsedCaption()
                parser.feed(delivery_caption(title, "720p · 12.0 MB", url))
                self.assertEqual(parser.urls, [url])
                self.assertTrue(parser.text.startswith(title + "\n720p · 12.0 MB\n\nSource: "))
                self.assertLessEqual(len(parser.text.encode("utf-16-le")) // 2, 1024)
                self.assertTrue(parser.text.endswith(url if len(url) < 1000 else "Original link"))


class FakeTelegram:
    def __init__(self):
        self.messages = []
        self.edits = []
        self.answers = []
        self.uploads = []
        self.audio_uploads = []

    async def message(self, chat_id, text, *, keyboard=None):
        message = {
            "chat": {"id": chat_id, "type": "private"},
            "message_id": len(self.messages) + 1,
            "text": text,
            "keyboard": keyboard,
        }
        self.messages.append(message)
        return message

    async def edit(self, chat_id, message_id, text, **kwargs):
        self.edits.append(text)

    async def acknowledge(self, query_id, text=""):
        self.answers.append(text)

    async def upload(self, chat_id, path, caption, **kwargs):
        self.uploads.append((chat_id, path.read_bytes(), caption, kwargs))

    async def upload_audio(self, chat_id, path, caption, **kwargs):
        self.audio_uploads.append((chat_id, path.read_bytes(), caption, kwargs))


def message(text, user=1, chat=None):
    return {
        "message": {
            "chat": {"id": chat or user, "type": "private"},
            "from": {"id": user},
            "text": text,
            "message_id": 1,
        }
    }


def callback(data, user=1, chat=None):
    return {
        "callback_query": {
            "id": "query",
            "from": {"id": user},
            "data": data,
            "message": {"message_id": 2, "chat": {"id": chat or user, "type": "private"}},
        }
    }


async def finish(bot):
    await asyncio.gather(*(job.task for job in list(bot.jobs.values())))


class ConversationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.api = FakeTelegram()
        self.directory = tempfile.TemporaryDirectory()
        self.bot = Bot(self.api, workspace=Path(self.directory.name))

    async def asyncTearDown(self):
        await self.bot.close()
        self.assertEqual(list(Path(self.directory.name).iterdir()), [])
        self.directory.cleanup()

    async def test_link_quality_compress_and_upload_conversation(self):
        analysis = media.Analysis("Example", (media.Quality(720, "v+a", 60_000_000),))

        async def download(url, quality, folder):
            source = folder / "source.mkv"
            source.write_bytes(b"download")
            return source

        async def prepare(source, status):
            await status("Compressing…")
            target = source.parent / "telegram.mp4"
            target.write_bytes(b"video-data")
            return media.PreparedVideo(
                target, media.Probe(12.3, 640, 360, "h264", "yuv420p", "aac"), True
            )

        with (
            patch.object(media, "analyze", AsyncMock(return_value=analysis)),
            patch.object(media, "download", side_effect=download),
            patch.object(media, "prepare_video", side_effect=prepare),
        ):
            await self.bot.handle(message("https://example.com/video"))
            await finish(self.bot)
            button = self.api.messages[-1]["keyboard"][0][0]
            self.assertIn("~60.0 MB", button["text"])
            self.assertIn("compress", button["text"])
            self.assertLessEqual(len(button["callback_data"].encode()), 64)
            await self.bot.handle(callback(button["callback_data"]))
            await finish(self.bot)
        self.assertEqual(self.api.uploads[0][1], b"video-data")
        self.assertIn("360p", self.api.uploads[0][2])
        self.assertIn("compressed", self.api.uploads[0][2])
        self.assertIn('Source: <a href="https://example.com/video">', self.api.uploads[0][2])
        self.assertEqual(self.api.uploads[0][3]["duration"], 13)
        self.assertFalse(self.bot.selections)

    async def test_expired_and_other_user_buttons_do_not_download(self):
        analysis = media.Analysis("Example", (media.Quality(360, "v", None),))
        self.bot.selections["key"] = Selection(
            (1, 1), "https://example.com", analysis, time.monotonic() + 10
        )
        await self.bot.handle(callback("q:key:0", user=2))
        self.assertFalse(self.bot.jobs)
        self.assertIn("expired", self.api.answers[-1])
        self.bot.selections["key"].expires = 0
        await self.bot.handle(callback("q:key:0"))
        self.assertFalse(self.bot.jobs)

    async def test_allowlist_and_group_messages(self):
        self.bot.allowed_users = {2}
        await self.bot.handle(message("https://example.com"))
        self.assertEqual(self.api.messages[-1]["text"], "This bot is private.")
        group = message("https://example.com", user=2)
        group["message"]["chat"]["type"] = "group"
        await self.bot.handle(group)
        self.assertFalse(self.bot.jobs)

    async def test_audio_menu_uses_audio_pipeline_and_telegram_audio_player(self):
        analysis = media.Analysis(
            "Example audio",
            (
                media.Quality(720, "v+a", 60_000_000),
                media.Quality(None, "a", 6_000_000, audio_only=True),
            ),
        )

        async def downloaded(url, quality, folder):
            self.assertTrue(quality.audio_only)
            source = folder / "source.m4a"
            source.write_bytes(b"source-audio")
            return source

        async def prepared(source, status):
            output = source.parent / "telegram.m4a"
            output.write_bytes(b"prepared-audio")
            return media.PreparedAudio(output, media.AudioProbe(12.3, "aac", 128_000, 0), True)

        with (
            patch.object(media, "analyze", AsyncMock(return_value=analysis)),
            patch.object(media, "download", side_effect=downloaded),
            patch.object(media, "prepare_audio", side_effect=prepared),
            patch.object(media, "prepare_video", AsyncMock()) as video,
        ):
            await self.bot.handle(message("https://example.com/video"))
            await finish(self.bot)
            buttons = self.api.messages[-1]["keyboard"]
            self.assertEqual(len(buttons), 2)
            self.assertEqual(buttons[-1][0]["text"], "Audio only · ~6.0 MB")
            await self.bot.handle(callback(buttons[-1][0]["callback_data"]))
            await finish(self.bot)
            video.assert_not_awaited()
        self.assertFalse(self.api.uploads)
        self.assertEqual(self.api.audio_uploads[0][1], b"prepared-audio")
        self.assertIn("compressed", self.api.audio_uploads[0][2])
        self.assertIn('Source: <a href="https://example.com/video">', self.api.audio_uploads[0][2])
        self.assertEqual(self.api.audio_uploads[0][3], {"title": "Example audio", "duration": 13})
        self.assertFalse(self.bot.selections)

    async def test_oversized_audio_is_not_uploaded(self):
        analysis = media.Analysis("Example", (media.Quality(None, "a", None, audio_only=True),))
        self.bot.selections["key"] = Selection(
            (1, 1), "https://example.com", analysis, time.monotonic() + 10
        )

        async def downloaded(url, quality, folder):
            source = folder / "source.m4a"
            source.write_bytes(b"source-audio")
            return source

        async def prepared(source, status):
            output = source.parent / "telegram.m4a"
            with output.open("wb") as file:
                file.truncate(media.UPLOAD_LIMIT + 1)
            return media.PreparedAudio(output, media.AudioProbe(10, "aac", 128_000, 0), True)

        with (
            patch.object(media, "download", side_effect=downloaded),
            patch.object(media, "prepare_audio", side_effect=prepared),
        ):
            await self.bot.handle(callback("q:key:0"))
            await finish(self.bot)
        self.assertFalse(self.api.audio_uploads)
        self.assertIn("exceeds", self.api.edits[-1])

    async def test_notebook_entrypoint_initializes_polls_and_shuts_down(self):
        async def updates():
            yield message("/start")

        self.api.call = AsyncMock(return_value={"username": "example_bot"})
        self.api.poll = updates
        self.api.close = AsyncMock()
        token = "123456:" + "x" * 35
        with (
            patch("vidfetch_bot.app.Telegram", return_value=self.api),
            patch("vidfetch_bot.app.shutil.which", return_value="installed"),
            patch("builtins.print") as output,
        ):
            await run_bot(token)
        methods = [call.args[0] for call in self.api.call.await_args_list]
        self.assertEqual(methods, ["getMe", "deleteWebhook", "setMyCommands"])
        self.assertIn("estimated", self.api.messages[0]["text"])
        self.api.close.assert_awaited_once()
        self.assertNotIn(token, str(output.call_args_list))

    async def test_cancel_active_job_and_remove_its_files(self):
        started = asyncio.Event()

        async def slow_analyze(url, folder):
            (folder / "partial.mp4").write_bytes(b"partial")
            started.set()
            await asyncio.Event().wait()

        with patch.object(media, "analyze", side_effect=slow_analyze):
            await self.bot.handle(message("https://example.com"))
            await started.wait()
            await self.bot.handle(message("/cancel"))
        self.assertFalse(self.bot.jobs)
        self.assertEqual(list(Path(self.directory.name).iterdir()), [])

    async def test_cancel_before_job_first_runs_does_not_leak_busy_state(self):
        await self.bot.schedule((1, 1), AsyncMock())
        await self.bot.handle(message("/cancel"))
        self.assertFalse(self.bot.jobs)

    async def test_bounded_queue_and_one_request_per_user(self):
        self.bot.max_jobs = 1
        gate = asyncio.Event()

        async def slow(status, folder):
            await gate.wait()

        self.assertTrue(await self.bot.schedule((1, 1), slow))
        self.assertFalse(await self.bot.schedule((1, 1), slow))
        self.assertIn("already", self.api.messages[-1]["text"])
        self.assertFalse(await self.bot.schedule((2, 2), slow))
        self.assertIn("full", self.api.messages[-1]["text"])
        gate.set()
        await finish(self.bot)

    async def test_oversized_output_never_reaches_telegram(self):
        analysis = media.Analysis("Example", (media.Quality(360, "v", 10),))
        self.bot.selections["key"] = Selection(
            (1, 1), "https://example.com", analysis, time.monotonic() + 10
        )

        async def oversized(source, status):
            output = source.parent / "telegram.mp4"
            with output.open("wb") as handle:
                handle.truncate(media.UPLOAD_LIMIT + 1)
            return media.PreparedVideo(
                output, media.Probe(10, 640, 360, "h264", "yuv420p", None), True
            )

        async def downloaded(url, quality, folder):
            source = folder / "source.mp4"
            source.write_bytes(b"source")
            return source

        with (
            patch.object(media, "download", side_effect=downloaded),
            patch.object(media, "prepare_video", side_effect=oversized),
        ):
            await self.bot.handle(callback("q:key:0"))
            await finish(self.bot)
        self.assertFalse(self.api.uploads)
        self.assertIn("exceeds", self.api.edits[-1])
