import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

from vidfetch_bot.telegram import LOCAL_UPLOAD_LIMIT, Telegram, TelegramError


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_incoming_cookie_file_is_bounded_and_cache_copy_is_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            api = Telegram("unused", api_root="http://127.0.0.1:8081", local_files=True)
            api.file_directory = root / "server"
            api.file_directory.mkdir()
            path = api.file_directory / "bot/documents/document.txt"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"private-cookie")
            api.call = AsyncMock(return_value={"file_path": str(path), "file_size": 14})
            try:
                self.assertEqual(await api.read_document("file", max_bytes=20), b"private-cookie")
                self.assertFalse(path.exists())
                path.write_bytes(b"private-cookie" * 10)
                api.call.return_value = {"file_path": str(path), "file_size": 2}
                with self.assertRaises(TelegramError):
                    await api.read_document("file", max_bytes=20)
                self.assertFalse(path.exists())
                outside = root / "secret.txt"
                outside.write_bytes(b"must-not-read-or-delete")
                api.call.return_value = {"file_path": str(outside), "file_size": 2}
                with self.assertRaises(TelegramError):
                    await api.read_document("file", max_bytes=20)
                self.assertTrue(outside.exists())
                protected = api.file_directory / "state.binlog"
                protected.write_bytes(b"authorization-state")
                api.call.return_value = {"file_path": str(protected), "file_size": 2}
                with self.assertRaises(TelegramError):
                    await api.read_document("file", max_bytes=20)
                self.assertTrue(protected.exists())
            finally:
                await api.close()

    async def test_cloud_incoming_cookie_stream_is_bounded_and_rejects_redirects_and_traversal(self):
        requests = []
        result = {"file_path": "documents/cookies.txt", "file_size": 2}
        status = 200

        def transport(request):
            requests.append(request)
            if request.method == "POST":
                return httpx.Response(200, json={"ok": True, "result": result})
            return httpx.Response(status, content=b"private-cookie", headers={"location": "https://untrusted.invalid"})

        api = Telegram("private-test-token", transport=httpx.MockTransport(transport))
        try:
            self.assertEqual(await api.read_document("file", max_bytes=20), b"private-cookie")
            with self.assertRaises(TelegramError) as error:
                await api.read_document("file", max_bytes=3)
            self.assertNotIn("private", str(error.exception))
            status = 302
            with self.assertRaises(TelegramError):
                await api.read_document("file", max_bytes=20)
            self.assertTrue(all(request.url.host == "api.telegram.org" for request in requests))
            for name in ("../private", "/etc/passwd", "documents\\private"):
                result["file_path"] = name
                before = len(requests)
                with self.assertRaises(TelegramError):
                    await api.read_document("file", max_bytes=20)
                self.assertEqual(len(requests), before + 1)
        finally:
            await api.close()

    async def test_local_server_exit_stops_polling_instead_of_retrying_forever(self):
        api = Telegram("unused", api_root="http://127.0.0.1:8081", local_files=True)
        api.server_process = SimpleNamespace(returncode=1)
        try:
            updates = api.poll()
            with self.assertRaisesRegex(TelegramError, "server stopped"):
                await anext(updates)
            await updates.aclose()
        finally:
            await api.close()

    async def test_large_files_use_local_paths_for_video_audio_and_documents(self):
        requests = []

        def transport(request):
            requests.append(request)
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 7}})

        api = Telegram(
            "unused-test-credential",
            api_root="http://127.0.0.1:8081",
            local_files=True,
            transport=httpx.MockTransport(transport),
        )
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "original video.mp4"
                with path.open("wb") as stream:
                    stream.truncate(60_000_000)
                await api.upload(12, path, "Original", width=1920, height=1080, duration=60)
                await api.upload_audio(12, path, "Original", title="Track", duration=60)
                await api.upload_document(12, path, "Original")
                self.assertEqual(api.upload_limit, LOCAL_UPLOAD_LIMIT)
                for request, field in zip(requests, ["video", "audio", "document"], strict=True):
                    self.assertEqual(request.url.host, "127.0.0.1")
                    self.assertEqual(json.loads(request.content)[field], path.resolve().as_uri())
                    self.assertLess(len(request.content), 1000)
                    self.assertEqual(request.extensions["timeout"]["read"], 3600)
        finally:
            await api.close()

    async def test_local_paths_cannot_be_sent_to_a_remote_server(self):
        for origin in ("http://example.com", "https://example.com"):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                Telegram("unused", api_root=origin, local_files=True)

    async def test_format_rejection_falls_back_but_network_failure_never_duplicates_upload(self):
        for code, description, methods in [
            (400, "VIDEO_CONTENT_INVALID", ["sendVideo", "sendDocument"]),
            (0, "network", ["sendVideo"]),
            (413, "file too big", ["sendVideo"]),
        ]:
            api = Telegram("unused")
            api.send_file = AsyncMock(side_effect=[TelegramError(code, description), None])
            try:
                if code == 400:
                    await api.upload(1, Path("video.mp4"), "Caption", width=2, height=2, duration=1)
                else:
                    with self.assertRaises(TelegramError):
                        await api.upload(
                            1, Path("video.mp4"), "Caption", width=2, height=2, duration=1
                        )
                self.assertEqual([c.args[0] for c in api.send_file.await_args_list], methods)
            finally:
                await api.close()

    async def test_m4a_upload_uses_send_audio_with_music_player_metadata(self):
        calls = []

        def transport(request):
            calls.append((request.url.path.split("/")[-1], request.read()))
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 7}})

        api = Telegram("unused-test-credential", transport=httpx.MockTransport(transport))
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "audio.m4a"
                path.write_bytes(b"actual-audio-payload")
                await api.upload_audio(12, path, "Example", title="Track title", duration=10)
            self.assertEqual(calls[0][0], "sendAudio")
            self.assertIn(b'name="parse_mode"', calls[0][1])
            self.assertIn(b"HTML", calls[0][1])
            for expected in (
                b"actual-audio-payload",
                b'name="audio"',
                b"audio/mp4",
                b"audio.m4a",
                b'name="duration"',
                b"Track title",
            ):
                self.assertIn(expected, calls[0][1])
        finally:
            await api.close()

    async def test_keyboard_and_multipart_video_payloads(self):
        calls = []

        def transport(request):
            calls.append((request.url.path.split("/")[-1], request.headers, request.read()))
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 7}})

        api = Telegram("unused-test-credential", transport=httpx.MockTransport(transport))
        try:
            keyboard = [[{"text": "720p · ~12.0 MB", "callback_data": "q:key:0"}]]
            await api.message(12, "Choose", keyboard=keyboard)
            self.assertEqual(json.loads(calls[0][2])["reply_markup"]["inline_keyboard"], keyboard)
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "video.mp4"
                path.write_bytes(b"actual-video-payload")
                await api.upload(12, path, "Example", width=640, height=360, duration=10)
            self.assertEqual(calls[1][0], "sendVideo")
            self.assertIn(b'name="parse_mode"', calls[1][2])
            self.assertIn(b"HTML", calls[1][2])
            self.assertIn(b"actual-video-payload", calls[1][2])
            self.assertIn(b'name="supports_streaming"', calls[1][2])
        finally:
            await api.close()

    async def test_inline_results_are_personal_and_media_edits_reuse_cached_files(self):
        calls = []

        def transport(request):
            calls.append((request.url.path.split("/")[-1], json.loads(request.read())))
            return httpx.Response(200, json={"ok": True, "result": True})

        api = Telegram("unused-test-credential", transport=httpx.MockTransport(transport))
        try:
            await api.answer_inline("query", [{"type": "article", "id": "request"}])
            self.assertEqual(calls[0][1]["cache_time"], 0)
            self.assertTrue(calls[0][1]["is_personal"])
            await api.edit_inline("inline", "Downloading", keyboard=[[{"text": "Cancel", "callback_data": "x:job"}]])
            self.assertEqual(calls[1][1]["inline_message_id"], "inline")
            self.assertNotIn("chat_id", calls[1][1])
            await api.edit_inline_media("inline", "video", "cached-file", "Caption")
            self.assertEqual(calls[2][0], "editMessageMedia")
            self.assertEqual(calls[2][1]["media"]["media"], "cached-file")
            self.assertEqual(calls[2][1]["reply_markup"], {"inline_keyboard": []})
            await api.updates(3)
            self.assertIn("inline_query", calls[3][1]["allowed_updates"])
            self.assertIn("chosen_inline_result", calls[3][1]["allowed_updates"])
        finally:
            await api.close()

    async def test_network_error_never_contains_credential(self):
        def transport(request):
            raise httpx.ConnectError("secret-credential-in-url", request=request)

        api = Telegram("secret-credential-in-url", transport=httpx.MockTransport(transport))
        try:
            with self.assertRaises(TelegramError) as caught:
                await api.call("getMe")
            self.assertNotIn("secret-credential", str(caught.exception))
        finally:
            await api.close()

    async def test_poll_offsets_reconnect_and_conflicting_instance(self):
        api = Telegram("unused-test-credential")
        api.updates = AsyncMock(
            side_effect=[
                [{"update_id": 10, "message": {}}, {"update_id": 11, "message": {}}],
                TelegramError(429, "slow", 2),
                [{"update_id": 12}],
                TelegramError(409, "conflict"),
            ]
        )
        updates = api.poll()
        try:
            self.assertEqual((await anext(updates))["update_id"], 10)
            self.assertEqual((await anext(updates))["update_id"], 11)
            with patch.object(asyncio, "sleep", AsyncMock()) as sleep:
                self.assertEqual((await anext(updates))["update_id"], 12)
                sleep.assert_awaited_once_with(2)
            with self.assertRaisesRegex(TelegramError, "Another copy"):
                await anext(updates)
            self.assertEqual([c.args[0] for c in api.updates.await_args_list], [0, 12, 12, 13])
        finally:
            await updates.aclose()
            await api.close()
