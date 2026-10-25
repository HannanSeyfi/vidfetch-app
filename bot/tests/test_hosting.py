import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from vidfetch_bot import media

SPEC = importlib.util.spec_from_file_location("hosting_main", Path(__file__).resolve().parents[1] / "main.py")
hosting = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hosting)


class HostingTests(unittest.TestCase):
    def test_missing_or_invalid_secrets_do_not_connect_or_echo_values(self):
        for environment in ({}, {
            "TELEGRAM_BOT_TOKEN": "private-invalid-value",
            "TELEGRAM_API_ID": "12345",
            "TELEGRAM_API_HASH": "a" * 32,
        }):
            with patch.dict(os.environ, environment, clear=True), patch.object(hosting, "local_bot_api") as api:
                with self.assertRaises(ValueError) as error:
                    hosting.configuration()
                self.assertNotIn("private-invalid-value", str(error.exception))
                api.assert_not_called()

    def test_allowlist_rejects_invalid_values_and_accepts_only_positive_ids(self):
        environment = {
            "TELEGRAM_BOT_TOKEN": "123456:" + "x" * 35,
            "TELEGRAM_API_ID": "12345",
            "TELEGRAM_API_HASH": "a" * 32,
        }
        with patch.dict(os.environ, environment, clear=True):
            for invalid in ("one", "0", "-123", "1,2,secret"):
                os.environ["VIDFETCH_ALLOWED_USERS"] = invalid
                with self.assertRaisesRegex(ValueError, "positive user IDs"):
                    hosting.configuration()
            os.environ["VIDFETCH_ALLOWED_USERS"] = "123, 456,123"
            self.assertEqual(hosting.configuration()[-1], {123, 456})

    def test_shared_disk_free_space_cannot_override_host_quota(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "environment").write_bytes(b"x" * 20)
            budget = media.StorageBudget(root, media.MIN_FREE_BYTES + 10)
            with patch.object(media, "STORAGE_BUDGET", budget), patch.object(
                media.shutil, "disk_usage", return_value=SimpleNamespace(free=20_000_000_000)
            ):
                with self.assertRaisesRegex(media.MediaError, "storage allowance"):
                    media.check_disk(root)
                (root / "environment").unlink()
                media.check_disk(root)


class HostingRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_server_state_is_persistent_and_bot_uses_local_transport(self):
        from contextlib import asynccontextmanager

        calls = []
        client = object()

        @asynccontextmanager
        async def local_api(*args, **kwargs):
            calls.append(kwargs)
            yield client

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(hosting, "configuration") as config,
            patch.object(hosting, "local_bot_api", local_api),
            patch.object(hosting, "run_bot", AsyncMock()) as bot,
            patch.dict(os.environ, {}, clear=True),
            patch("asyncio.get_running_loop") as get_loop,
        ):
            root = Path(directory)
            for token in ("123456:first", "123456:rotated", "654321:another"):
                config.return_value = (token, "12345", "hash", {123})
                await hosting.serve(root / "api", root / "state")
            self.assertEqual(calls[0]["directory"], root / "state/telegram-api/123456")
            self.assertEqual(calls[0]["directory"], calls[1]["directory"])
            self.assertEqual(calls[2]["directory"], root / "state/telegram-api/654321")
            self.assertEqual(calls[0]["binary"], root / "api")
            self.assertIs(bot.call_args.kwargs["api"], client)
            self.assertEqual(get_loop.return_value.add_signal_handler.call_count, 6)
            self.assertEqual(get_loop.return_value.remove_signal_handler.call_count, 6)
