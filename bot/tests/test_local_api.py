import asyncio
import logging
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from vidfetch_bot.credentials import read_secret
from vidfetch_bot.local_api import (
    API_REVISION,
    LocalAPIError,
    install_server,
    local_bot_api,
    migrate_from_cloud,
    wait_for_server,
)
from vidfetch_bot.telegram import TelegramError

TOKEN = "123456:" + "x" * 35
API_HASH = "a" * 32


class InstallTests(unittest.TestCase):
    def test_builds_pinned_sources_and_reuses_completed_installation(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            binary = cache / API_REVISION / "install" / "bin" / "telegram-bot-api"
            calls = []

            def build(args, **kwargs):
                calls.append(args)
                if args[:2] == ["cmake", "--build"]:
                    binary.parent.mkdir(parents=True)
                    binary.write_bytes(b"fixture-executable")

            with patch("sys.platform", "linux"), patch("subprocess.run", side_effect=build):
                self.assertEqual(install_server(cache), binary)
                count = len(calls)
                self.assertEqual(install_server(cache), binary)
                self.assertEqual(len(calls), count)
            self.assertTrue(any(API_REVISION in call and "checkout" in call for call in calls))
            self.assertTrue(any("--recursive" in call for call in calls))
            self.assertTrue(any("--parallel" in call for call in calls))


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_server_process_is_bound_to_loopback_and_stopped_on_exit(self):
        real_spawn = asyncio.create_subprocess_exec
        processes = []
        spawn_arguments = []

        async def spawn(*args, **kwargs):
            spawn_arguments.append((args, kwargs))
            port = int(next(arg.split("=")[1] for arg in args if arg.startswith("--http-port=")))
            code = (
                "import socket,time; s=socket.socket(); "
                f"s.bind(('127.0.0.1',{port})); s.listen(); time.sleep(90)"
            )
            process = await real_spawn(sys.executable, "-c", code, **kwargs)
            processes.append(process)
            return process

        for cancel in (False, True):
            with self.subTest(cancel=cancel), tempfile.TemporaryDirectory() as directory:
                api = SimpleNamespace(close=AsyncMock())
                migrate = AsyncMock()
                with (
                    patch("asyncio.create_subprocess_exec", side_effect=spawn),
                    patch("vidfetch_bot.local_api.migrate_from_cloud", migrate),
                    patch("vidfetch_bot.local_api.Telegram", return_value=api) as client,
                ):

                    async def run(api=api, cancel=cancel):
                        async with local_bot_api(
                            TOKEN,
                            "12345",
                            API_HASH,
                            binary=Path(sys.executable),
                            directory=Path(directory),
                        ) as connected:
                            self.assertIs(connected, api)
                            if cancel:
                                raise asyncio.CancelledError

                    if cancel:
                        with self.assertRaises(asyncio.CancelledError):
                            await run()
                    else:
                        await run()
                        # Restarting on the same runtime must reuse its migration marker.
                        await run()
                    migrate.assert_awaited_once_with(TOKEN)
                    self.assertTrue(client.call_args.kwargs["local_files"])
                    self.assertTrue(
                        client.call_args.kwargs["api_root"].startswith("http://127.0.0.1:")
                    )
                self.assertIsNotNone(processes[-1].returncode)
                self.assertGreaterEqual(api.close.await_count, 1)
        for args, kwargs in spawn_arguments:
            self.assertIn("--local", args)
            self.assertIn("--http-ip-address=127.0.0.1", args)
            self.assertNotIn(API_HASH, " ".join(args))
            self.assertEqual(kwargs["env"]["TELEGRAM_API_HASH"], API_HASH)
            self.assertEqual(kwargs["stdout"], subprocess.DEVNULL)
            self.assertEqual(kwargs["stderr"], subprocess.DEVNULL)

    async def test_startup_failure_and_timeout_are_actionable(self):
        with self.assertRaisesRegex(LocalAPIError, "stopped"):
            await wait_for_server(SimpleNamespace(returncode=1), 1)
        with self.assertRaisesRegex(LocalAPIError, "ready"):
            await wait_for_server(SimpleNamespace(returncode=None), 1, timeout=0)

    async def test_invalid_credentials_do_not_start_a_process(self):
        for token, identifier, secret in [
            ("invalid", "1", API_HASH),
            (TOKEN, "x", API_HASH),
            (TOKEN, "1", "bad"),
        ]:
            with (
                self.subTest(identifier=identifier),
                patch("asyncio.create_subprocess_exec") as spawn,
            ):
                with self.assertRaises(LocalAPIError):
                    async with local_bot_api(token, identifier, secret):
                        self.fail("Invalid credentials were accepted")
                spawn.assert_not_called()

    async def test_migration_closes_cloud_client_and_hides_debug_urls(self):
        for error in (None, TelegramError(429, "login cooldown", 600)):
            api = SimpleNamespace(call=AsyncMock(side_effect=error), close=AsyncMock())
            with patch("vidfetch_bot.local_api.Telegram", return_value=api):
                await migrate_from_cloud(TOKEN)
            api.call.assert_awaited_once_with("logOut")
            api.close.assert_awaited_once()
            self.assertEqual(logging.getLogger("httpx").level, logging.CRITICAL)

    async def test_invalid_bot_token_is_not_ignored_during_migration(self):
        api = SimpleNamespace(
            call=AsyncMock(side_effect=TelegramError(401, "invalid")), close=AsyncMock()
        )
        with patch("vidfetch_bot.local_api.Telegram", return_value=api):
            with self.assertRaises(TelegramError):
                await migrate_from_cloud(TOKEN)
        api.close.assert_awaited_once()


class SecretTests(unittest.TestCase):
    def test_environment_colab_secret_and_hidden_prompt_precedence(self):
        colab = SimpleNamespace(userdata=SimpleNamespace(get=lambda name: "colab-secret"))
        with patch.dict("sys.modules", {"google.colab": colab}), patch("os.environ", {}):
            self.assertEqual(read_secret("TEST_SECRET", "Hidden: "), "colab-secret")
            with patch.dict("os.environ", {"TEST_SECRET": "environment-secret"}):
                self.assertEqual(read_secret("TEST_SECRET", "Hidden: "), "environment-secret")
            colab.userdata.get = lambda name: (_ for _ in ()).throw(RuntimeError("private"))
            with patch(
                "vidfetch_bot.credentials.getpass", return_value=" hidden-secret "
            ) as prompt:
                self.assertEqual(read_secret("TEST_SECRET", "Hidden: "), "hidden-secret")
                prompt.assert_called_once_with("Hidden: ")
