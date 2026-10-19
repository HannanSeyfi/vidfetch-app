import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

from vidfetch_bot.telegram import Telegram, TelegramError


class ApiTests(unittest.IsolatedAsyncioTestCase):
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
                b"VidFetch.m4a",
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
