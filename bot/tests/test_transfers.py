import asyncio
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from test_app import FakeTelegram, callback, finish, message

from vidfetch_bot import media
from vidfetch_bot.app import Bot, Selection


def inline_callback(data, user=1, inline_id="inline-chat-message"):
    return {"callback_query": {"id": "query", "from": {"id": user},
                               "inline_message_id": inline_id, "data": data}}


class TransferTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.api = FakeTelegram()
        self.bot = Bot(self.api, workspace=Path(self.directory.name))

    async def asyncTearDown(self):
        await self.bot.close()
        self.assertEqual(list(Path(self.directory.name).iterdir()), [])
        self.directory.cleanup()

    async def test_two_requests_run_together_and_cancel_only_the_selected_one(self):
        started = [asyncio.Event() for _ in range(3)]
        gates = [asyncio.Event() for _ in range(3)]

        def action(index):
            async def work(status, folder):
                (folder / "partial").write_bytes(b"partial")
                await status(f"Downloading {index} · 40%")
                started[index].set()
                await gates[index].wait()
            return work

        for index in range(3):
            self.assertTrue(await self.bot.schedule((1, 1), action(index), title=f"Video {index}"))
        keys = list(self.bot.jobs)
        await asyncio.wait_for(asyncio.gather(started[0].wait(), started[1].wait()), 2)
        self.assertFalse(started[2].is_set())
        await self.bot.handle(message("/status"))
        status = self.api.messages[-1]
        self.assertEqual(len(status["keyboard"]), 3)
        self.assertIn("Video 0", status["text"])
        self.assertIn("40%", status["text"])
        await self.bot.handle(callback(f"x:{keys[0]}", user=2))
        self.assertIn(keys[0], self.bot.jobs)
        await self.bot.handle(callback(f"x:{keys[0]}"))
        await asyncio.wait_for(started[2].wait(), 2)
        self.assertNotIn(keys[0], self.bot.jobs)
        self.assertEqual(set(self.bot.jobs), set(keys[1:]))
        self.assertEqual(len(list(Path(self.directory.name).iterdir())), 2)
        gates[1].set()
        gates[2].set()
        await finish(self.bot)

    async def test_cancel_command_with_multiple_jobs_offers_individual_buttons(self):
        async def wait(status, folder):
            await asyncio.Event().wait()

        await self.bot.schedule((1, 1), wait)
        await self.bot.schedule((1, 1), wait)
        await self.bot.handle(message("/cancel"))
        self.assertEqual(len(self.bot.jobs), 2)
        self.assertEqual(len(self.api.messages[-1]["keyboard"]), 2)
        await self.bot.handle(message("/cancel all"))
        self.assertFalse(self.bot.jobs)

    async def test_personal_queue_limit_does_not_block_a_different_user(self):
        self.bot.max_user_jobs = 2

        async def wait(status, folder):
            await asyncio.Event().wait()

        self.assertTrue(await self.bot.schedule((1, 1), wait))
        self.assertTrue(await self.bot.schedule((1, 1), wait))
        self.assertFalse(await self.bot.schedule((1, 1), wait))
        self.assertTrue(await self.bot.schedule((2, 2), wait))

    async def test_multiple_quality_menus_remain_usable(self):
        analysis = media.Analysis("Example", (media.Quality(720, "v+a", 10),))
        with patch.object(media, "analyze", AsyncMock(return_value=analysis)):
            await self.bot.handle(message("https://example.com/first"))
            await self.bot.handle(message("https://example.com/second"))
            await finish(self.bot)
        self.assertEqual({menu.url for menu in self.bot.selections.values()},
                         {"https://example.com/first", "https://example.com/second"})

    async def test_inline_menu_download_uses_the_originating_message_and_cached_file(self):
        analysis = media.Analysis("Inline video", (media.Quality(720, "v+a", 10),))
        await self.bot.handle({"inline_query": {"id": "search", "from": {"id": 1},
                                               "query": "https://example.com/video"}})
        result = self.api.inline_answers[-1][1][0]
        self.assertFalse(self.bot.jobs)  # Typing alone must not start a download.
        data = result["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
        with patch.object(media, "analyze", AsyncMock(return_value=analysis)) as analyze:
            await self.bot.handle(inline_callback(data, user=2))
            analyze.assert_not_called()
            await self.bot.handle(inline_callback(data))
            await finish(self.bot)
        menu = self.api.inline_edits[-1]
        self.assertEqual(menu[0], "inline-chat-message")
        quality = menu[2]["keyboard"][0][0]["callback_data"]
        await self.bot.handle(inline_callback(quality, inline_id="another-chat"))
        self.assertFalse(self.bot.jobs)

        async def download(url, chosen, folder, *, progress):
            await progress("Downloading 50% · 2 MiB/s")
            path = folder / "video.mp4"
            path.write_bytes(b"actual-video")
            return path

        async def prepare(path, status, **options):
            return media.PreparedVideo(path, media.Probe(2, 1280, 720, "h264", "yuv420p", "aac"), False)

        with patch.object(media, "download", side_effect=download), patch.object(media, "prepare_video", side_effect=prepare):
            await self.bot.handle(inline_callback(quality))
            await finish(self.bot)
        self.assertEqual(self.api.inline_media[0][:3], ("inline-chat-message", "video", "cached-video"))
        self.assertEqual(self.api.uploads[0][0], 1)  # Only the requesting user's private staging chat.
        self.assertEqual(self.api.deleted, [(1, 100)])
        self.assertTrue(any("50%" in entry[1] for entry in self.api.inline_edits))
        self.assertNotIn("Sent.", self.api.inline_edits[-1][1])  # Do not overwrite the video with text.
        # Late/repeated feedback must never turn the finished video back into a menu.
        count = len(self.api.inline_edits)
        await self.bot.handle({"chosen_inline_result": {"result_id": result["id"], "from": {"id": 1},
                                                       "inline_message_id": "inline-chat-message"}})
        self.assertFalse(self.bot.jobs)
        self.assertEqual(len(self.api.inline_edits), count)

    async def test_rejected_quality_selection_keeps_its_retry_buttons(self):
        self.bot.max_jobs = 0
        self.bot.selections["key"] = Selection((1, 1), "https://example.com", media.Analysis("Example", (media.Quality(360, "v", 1),)), time.monotonic() + 60, "inline-chat-message")
        await self.bot.handle(inline_callback("q:key:0"))
        self.assertIn("key", self.bot.selections)
        self.assertIn("full", self.api.inline_edits[-1][1])
        self.assertEqual(self.api.inline_edits[-1][2]["keyboard"][0][0]["callback_data"], "q:key:0")

    async def test_inline_audio_documents_and_failed_edits_clean_the_staging_copy(self):
        path = Path(self.directory.name) / "temporary.m4a"
        path.write_bytes(b"audio")
        try:
            notice = {"inline_message_id": "inline-chat-message"}
            await self.bot.send_media((1, 1), path, "Audio", "audio", notice, title="Example", duration=1)
            self.assertEqual(self.api.inline_media[-1][1:3], ("audio", "cached-audio"))
            self.assertTrue(notice["media_sent"])
            notice = {"inline_message_id": "inline-chat-message"}
            self.api.edit_inline_media = AsyncMock(side_effect=RuntimeError("edit failed"))
            with self.assertRaises(RuntimeError):
                await self.bot.send_media((1, 1), path, "Document", "document", notice)
            self.assertEqual(self.api.deleted[-1], (1, 102))
            self.assertNotIn("media_sent", notice)
        finally:
            path.unlink()

    async def test_inline_feedback_starts_analysis_and_manual_fallback_is_idempotent(self):
        await self.bot.handle({"inline_query": {"id": "search", "from": {"id": 1},
                                               "query": "https://example.com/video"}})
        key = self.api.inline_answers[-1][1][0]["id"]
        analysis = media.Analysis("Example", (media.Quality(360, "v", None),))
        with patch.object(media, "analyze", AsyncMock(return_value=analysis)) as analyze:
            await self.bot.handle({"chosen_inline_result": {"result_id": key, "from": {"id": 1},
                                                           "inline_message_id": "inline-chat-message"}})
            await finish(self.bot)
            await self.bot.handle(inline_callback(f"i:{key}"))
        self.assertEqual(analyze.await_count, 1)

    async def test_inline_cancel_is_bound_to_its_message(self):
        notice = {"inline_message_id": "inline-chat-message"}

        async def wait(status, folder):
            await asyncio.Event().wait()

        await self.bot.schedule((1, 1), wait, status_message=notice)
        key = next(iter(self.bot.jobs))
        await self.bot.handle(inline_callback(f"x:{key}", inline_id="different"))
        self.assertTrue(self.bot.jobs)
        await self.bot.handle(inline_callback(f"x:{key}"))
        self.assertFalse(self.bot.jobs)
        self.assertIn("Cancelled", self.api.inline_edits[-1][1])

    async def test_inline_access_and_expiry(self):
        self.bot.allowed_users = {1}
        await self.bot.handle({"inline_query": {"id": "search", "from": {"id": 2},
                                               "query": "https://example.com/video"}})
        self.assertEqual(self.api.inline_answers[-1][1], [])
        self.assertFalse(self.bot.inline_requests)
        analysis = media.Analysis("Example", (media.Quality(360, "v", 1),))
        self.bot.selections["old"] = Selection((1, 1), "https://example.com", analysis, time.monotonic() - 1, "inline-chat-message")
        await self.bot.handle(inline_callback("q:old:0"))
        self.assertFalse(self.bot.jobs)


class ProgressTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_subprocess_reports_progress_without_losing_the_final_path(self):
        with tempfile.TemporaryDirectory() as folder:
            status = AsyncMock()
            result = await media.command([
                sys.executable, "-c",
                "print('VIDFETCH_PROGRESS: 42% · 1 MiB/s', flush=True); print('completed.mp4')",
            ], timeout=10, folder=Path(folder), progress=status)
            self.assertIn("completed.mp4", result.splitlines()[-1])
            self.assertIn("42%", status.await_args.args[0])
