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
