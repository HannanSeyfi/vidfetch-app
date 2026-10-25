import asyncio
import http.cookiejar
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from vidfetch_bot import media
from vidfetch_bot.app import Bot
from vidfetch_bot.cookies import CookieError, CookieStore, scoped_cookies, site_for_url

HEADER = b"# Netscape HTTP Cookie File\n"
REDDIT = HEADER + b"#HttpOnly_.reddit.com\tTRUE\t/\tTRUE\t0\treddit_session\tprivate-fixture\n"
YOUTUBE = HEADER + b".youtube.com\tTRUE\t/\tTRUE\t0\tSID\tprivate-fixture\n"


class CookieTests(unittest.TestCase):
    def test_aliases_and_deceptive_hosts(self):
        for host in ("reddit.com", "old.reddit.com", "redd.it", "v.redd.it", "redditmedia.com"):
            self.assertEqual(site_for_url("https://" + host + "/v"), "reddit.com")
        self.assertEqual(site_for_url("https://youtu.be/v"), "youtube.com")
        for url in ("https://reddit.com.bad.example/v", "https://reddit.com@bad.example/v"):
            self.assertIsNone(site_for_url(url))

    def test_scopes_cookies_and_rejects_expired_and_malformed_exports(self):
        text = REDDIT + b".example.com\tTRUE\t/\tTRUE\t0\tother\tother-secret\n"
        self.assertNotIn("other-secret", scoped_cookies(text, "reddit.com"))
        for data in (
            YOUTUBE,
            b"[]",
            HEADER + b".reddit.com\tFALSE\t/\tTRUE\t0\tname\tsecret\n",
            HEADER + b".reddit.com\tTRUE\t/\tTRUE\t1\treddit_session\texpired\n",
            b"x" * 2_000_001,
        ):
            with self.subTest(size=len(data)), self.assertRaises(CookieError):
                scoped_cookies(data, "reddit.com")

    def test_private_isolated_snapshots_cleanup_disable_delete_and_failed_replace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = CookieStore(root / "private")
            store.import_bytes("reddit.com", REDDIT)
            self.assertNotIn("private-fixture", store.status())
            self.assertIn("sign-in cookie present", store.status())
            with self.assertRaises(CookieError):
                store.import_bytes("reddit.com", YOUTUBE)
            with store.snapshot_for("https://redd.it/v", root) as snapshot:
                jar = http.cookiejar.MozillaCookieJar(str(snapshot))
                jar.load(ignore_discard=True, ignore_expires=True)
                self.assertEqual(next(iter(jar)).name, "reddit_session")
                snapshot.write_text("changed")
                if os.name != "nt":
                    self.assertEqual(snapshot.stat().st_mode & 0o777, 0o600)
            self.assertFalse(snapshot.exists())
            with self.assertRaisesRegex(RuntimeError, "cancelled"):
                with store.snapshot_for("https://reddit.com/v", root) as snapshot:
                    self.assertIn("private-fixture", snapshot.read_text())
                    raise RuntimeError("cancelled")
            self.assertFalse(snapshot.exists())
            store.set_enabled("reddit.com", False)
            with store.snapshot_for("https://reddit.com/v", root) as snapshot:
                self.assertIsNone(snapshot)
            store.set_enabled("reddit.com", True)
            self.assertTrue(store.has_enabled())
            store.delete("reddit.com")
            self.assertFalse(store.has_enabled())

    def test_cookie_accounts_require_explicit_bot_allowlist(self):
        with tempfile.TemporaryDirectory() as directory:
            store = CookieStore(Path(directory))
            store.import_bytes("youtube.com", YOUTUBE)
            with self.assertRaisesRegex(ValueError, "allowed_user_ids"):
                Bot(object(), cookie_store=store)
            Bot(object(), allowed_users={123}, cookie_store=store)

    def test_enabling_cookies_after_start_cannot_enable_public_account_access(self):
        with tempfile.TemporaryDirectory() as directory:
            store = CookieStore(Path(directory))
            bot = Bot(object(), cookie_store=store)
            store.import_bytes("youtube.com", YOUTUBE)
            with self.assertRaisesRegex(media.MediaError, "allowlist"):
                bot.cookie_options((123, 123))


class CookieExtractionTests(unittest.IsolatedAsyncioTestCase):
    async def test_analysis_and_download_receive_scoped_snapshots_and_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            store = CookieStore(folder / "private")
            store.import_bytes("youtube.com", YOUTUBE)
            source = folder / "source.mp4"
            source.write_bytes(b"fixture")
            calls = []

            async def command(args, **kwargs):
                snapshot = Path(args[args.index("--cookies") + 1])
                self.assertIn("private-fixture", snapshot.read_text())
                self.assertNotIn("--impersonate", args)
                calls.append(snapshot)
                if "--dump-single-json" in args:
                    return json.dumps(
                        {
                            "title": "fixture",
                            "formats": [
                                {
                                    "format_id": "v",
                                    "url": "https://example.com/v",
                                    "height": 240,
                                    "vcodec": "h264",
                                    "acodec": "aac",
                                }
                            ],
                        }
                    )
                return json.dumps(str(source))

            with (
                patch.object(media, "command", command),
                patch.object(media, "validate_url", AsyncMock()),
            ):
                await media.analyze("https://youtu.be/v", folder, cookie_store=store)
                await media.download(
                    "https://youtube.com/watch?v=v",
                    media.Quality(240, "v", None),
                    folder,
                    cookie_store=store,
                )
            self.assertEqual(len(calls), 2)
            self.assertNotEqual(calls[0], calls[1])
            self.assertTrue(all(not path.exists() for path in calls))

    async def test_reddit_retry_is_bounded_and_never_retries_rate_limits_or_cancel(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            blocked = media.tool_error(
                "ERROR: [Reddit] Your IP address is unable to access the Reddit API",
                ["-m", "yt_dlp", "https://reddit.com/comments/v"],
            )
            with patch.object(media, "command", AsyncMock(side_effect=[blocked, "ok"])) as run:
                self.assertEqual(
                    await media.extract("https://redd.it/v", [], folder, timeout=10), "ok"
                )
                self.assertIn("--impersonate", run.call_args_list[0].args[0])
                self.assertNotIn("--impersonate", run.call_args_list[1].args[0])
            for error in (asyncio.CancelledError(), media.MediaError("HTTP 429")):
                with patch.object(media, "command", AsyncMock(side_effect=error)) as run:
                    with self.assertRaises(type(error)):
                        await media.extract("https://reddit.com/comments/v", [], folder, timeout=10)
                    self.assertEqual(run.await_count, 1)

    def test_terminal_error_classification_does_not_use_cookie_warnings(self):
        args = ["-m", "yt_dlp", "https://reddit.com/comments/v"]
        error = media.tool_error("WARNING: cookies optional\nERROR: HTTP 429 secret-value", args)
        self.assertIn("rate limiting", str(error))
        self.assertFalse(error.retryable)
        self.assertNotIn("secret-value", str(error))
