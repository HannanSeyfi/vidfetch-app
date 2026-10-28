import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from test_app import FakeTelegram, callback, finish, message
from test_personal import cookie

from vidfetch_bot import media
from vidfetch_bot.access import AccessStore
from vidfetch_bot.app import Bot, Selection
from vidfetch_bot.cookie_routing import RoutedCookieStore
from vidfetch_bot.cookies import CookieError, CookieStore, UserCookieStores, normalize_site


class WebsiteCookieTests(unittest.TestCase):
    def test_domains_normalize_and_reject_public_suffixes_ips_credentials_and_paths(self):
        self.assertEqual(normalize_site("https://WWW.Example.COM/"), "example.com")
        self.assertEqual(normalize_site(".youtube.com"), "youtube.com")
        self.assertEqual(normalize_site("youtu.be"), "youtube.com")
        self.assertEqual(normalize_site("example.co.uk"), "example.co.uk")
        self.assertEqual(normalize_site("bücher.de"), "xn--bcher-kva.de")
        for value in ("../private", "com", "co.uk", "github.io", "127.0.0.1", "[::1]", "localhost", "site.local", "example.com:443", "user:pass@example.com", "https://example.com/path", "https://example.com/?secret=value", "example.com#fragment"):
            with self.subTest(value=value), self.assertRaises(CookieError):
                normalize_site(value)

    def test_custom_exports_match_subdomains_not_lookalikes_and_survive_reload_delete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = CookieStore(root / "private")
            store.import_bytes("example.com", cookie("example.com", "custom-private"))
            store = CookieStore(store.directory)
            self.assertIn("example.com", store.sites())
            self.assertIn("session validity unverified", store.status())
            with store.snapshot_for("https://video.example.com/watch", root) as path:
                self.assertIn("custom-private", path.read_text())
            self.assertFalse(path.exists())
            for url in ("https://example.com.evil.com/watch", "https://anotherexample.com/watch", "https://other.com/watch"):
                with store.snapshot_for(url, root) as path:
                    self.assertIsNone(path)
            store.set_enabled("example.com", False)
            with store.snapshot_for("https://example.com/watch", root) as path:
                self.assertIsNone(path)
            store.set_enabled("example.com", True)
            store.delete("example.com")
            self.assertNotIn("example.com", store.sites())

    def test_long_domain_filenames_are_bounded_and_discoverable(self):
        site = ".".join(["a" * 60] * 4 + ["com"])
        with tempfile.TemporaryDirectory() as directory:
            store = CookieStore(Path(directory))
            store.import_bytes(site, cookie(site, "long-site-private"))
            self.assertIn(site, CookieStore(store.directory).sites())
            self.assertTrue(all(len(path.name) <= 255 for path in store.directory.iterdir()))
            store.set_enabled(site, False)
            self.assertFalse(store.is_enabled(site))
            store.delete(site)
            self.assertFalse(list(store.directory.iterdir()))


class SharingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.access = AccessStore(self.root / "access.json", {1}, {2, 3})
        self.stores = UserCookieStores(self.root / "cookies")
        self.api = FakeTelegram()
        self.api.read_document = AsyncMock(return_value=cookie("example.com", "new-owner-cookie"))
        self.bot = Bot(self.api, access=self.access, user_cookies=self.stores, workspace=self.root)
        self.stores.for_user(1).import_bytes("youtube.com", cookie(value="owner-private"))
        self.stores.for_user(2).import_bytes("youtube.com", cookie(value="member-private"))

    async def asyncTearDown(self):
        await self.bot.close()
        self.directory.cleanup()

    def read_cookie(self, user=2, url="https://youtu.be/video"):
        routing = RoutedCookieStore(self.access, self.stores, user)
        with routing.snapshot_for(url, self.root) as path:
            return path.read_text() if path else None

    async def test_only_owners_can_share_only_with_approved_users(self):
        for command in ("/sharecookies 3 youtube.com", "/unsharecookies 2"):
            await self.bot.handle(message(command, user=2))
            self.assertFalse(self.access.shares)
        await self.bot.handle(message("/sharecookies 99", user=1))
        self.assertFalse(self.access.shares)
        self.assertFalse(self.access.allows(99))
        await self.bot.handle(message("/sharecookies 2 youtube.com", user=1))
        text = self.read_cookie()
        self.assertIn("owner-private", text)
        self.assertNotIn("member-private", text)
        self.assertIsNone(self.read_cookie(user=3))
        self.assertNotIn("owner-private", str(self.api.messages))

    async def test_entire_set_future_imports_site_exceptions_and_removal_are_persistent(self):
        await self.bot.handle(message("/sharecookies 2", user=1))
        self.assertIn("owner-private", self.read_cookie())
        self.stores.for_user(1).import_bytes("example.com", cookie("example.com", "future-owner-site"))
        self.assertIn("future-owner-site", self.read_cookie(url="https://example.com/watch"))
        self.stores.for_user(2).import_bytes("other.com", cookie("other.com", "must-not-fallback"))
        self.assertIsNone(self.read_cookie(url="https://other.com/watch"))
        await self.bot.handle(message("/unsharecookies 2 youtube.com", user=1))
        self.assertIn("member-private", self.read_cookie())
        self.assertIn("future-owner-site", self.read_cookie(url="https://example.com/watch"))
        restored = AccessStore(self.access.path, {1}, {2})
        self.assertEqual(restored.shares, self.access.shares)
        await self.bot.handle(message("/unsharecookies 2", user=1))
        self.assertFalse(self.access.shares)
        self.assertIn("member-private", self.read_cookie())
        self.assertTrue(self.access.allows(2))

    async def test_disabled_expired_missing_or_removed_owner_never_uses_member_cookie_instead(self):
        self.access.share_cookies(2, 1, "youtube.com")
        self.stores.for_user(1).set_enabled("youtube.com", False)
        with self.assertRaisesRegex(CookieError, "disabled"):
            self.read_cookie()
        self.stores.for_user(1).set_enabled("youtube.com", True)
        path = self.stores.for_user(1).directory / "youtube.com.cookies"
        path.write_text("not valid cookie data")
        with self.assertRaisesRegex(CookieError, "expired or invalid"):
            self.read_cookie()
        self.stores.for_user(1).delete("youtube.com")
        with self.assertRaisesRegex(CookieError, "missing"):
            self.read_cookie()
        self.access = AccessStore(self.access.path, {4})
        with self.assertRaisesRegex(CookieError, "no longer available"):
            self.read_cookie()

    async def test_user_can_only_delete_their_own_export_even_with_shared_cookies(self):
        self.access.share_cookies(2, 1)
        await self.bot.handle(message("/cookies", user=2))
        self.assertIn("Owner-cookie mode", self.api.messages[-1]["text"])
        delete = next(button["callback_data"] for row in self.api.messages[-1]["keyboard"] for button in row if button["text"] == "Delete YouTube")
        await self.bot.handle(callback(delete, user=2))
        confirm = self.api.messages[-1]["keyboard"][0][0]["callback_data"]
        await self.bot.handle(callback(confirm, user=2))
        self.assertFalse(self.stores.for_user(2).has_enabled())
        self.assertTrue(self.stores.for_user(1).has_enabled())
        self.assertIn("owner-private", self.read_cookie())

    async def test_revoke_cancels_active_shared_request_and_removes_its_snapshot(self):
        self.access.share_cookies(2, 1)
        started = asyncio.Event()
        snapshots = []

        async def analyze(url, folder, *, cookie_store, **kwargs):
            with cookie_store.snapshot_for(url, folder) as snapshot:
                snapshots.append(snapshot)
                self.assertIn("owner-private", snapshot.read_text())
                started.set()
                await asyncio.Event().wait()

        with patch.object(media, "analyze", side_effect=analyze):
            await self.bot.handle(message("https://youtu.be/video", user=2))
            await started.wait()
            await self.bot.handle(message("/unsharecookies 2", user=1))
        self.assertFalse(self.bot.jobs)
        self.assertTrue(all(not path.exists() for path in snapshots))
        self.assertIn("member-private", self.read_cookie())

    async def test_deny_removes_sharing_and_only_the_recipients_personal_exports(self):
        self.access.share_cookies(2, 1)
        await self.bot.handle(message("/deny 2", user=1))
        self.assertFalse(self.access.allows(2))
        self.assertNotIn(2, self.access.shares)
        self.assertFalse((self.stores.root / "2").exists())
        self.assertTrue(self.stores.for_user(1).has_enabled())
        self.assertFalse(AccessStore(self.access.path, {1}, {2}).allows(2))
        with self.assertRaises(CookieError):
            self.read_cookie()
        self.assertFalse((self.stores.root / "2").exists())

    async def test_actual_delivery_uses_owner_session_but_sends_only_video_to_recipient(self):
        self.access.share_cookies(2, 1, "youtube.com")
        import time

        self.bot.selections["share"] = Selection((2, 2), "https://youtu.be/video", media.Analysis("Video", (media.Quality(360, "v", 1),)), time.monotonic() + 60)

        async def download(url, quality, folder, *, cookie_store, progress=None):
            with cookie_store.snapshot_for(url, folder) as snapshot:
                self.assertIn("owner-private", snapshot.read_text())
                self.assertNotIn("member-private", snapshot.read_text())
            video = folder / "video.mp4"
            video.write_bytes(b"video-content-only")
            return video

        async def prepare(source, status, **kwargs):
            return media.PreparedVideo(source, media.Probe(1, 640, 360, "h264", "yuv420p", "aac"), False)

        with patch.object(media, "download", side_effect=download), patch.object(media, "prepare_video", side_effect=prepare):
            await self.bot.handle(callback("q:share:0", user=2))
            await finish(self.bot)
        self.assertEqual(self.api.uploads[0][:2], (2, b"video-content-only"))
        self.assertNotIn("owner-private", str(self.api.messages) + str(self.api.edits) + str(self.api.uploads))

    async def test_owner_import_stops_dependent_requests_and_new_export_is_used(self):
        self.access.share_cookies(2, 1)
        started = asyncio.Event()
        snapshots = []

        async def analyze(url, folder, *, cookie_store, **kwargs):
            with cookie_store.snapshot_for(url, folder) as snapshot:
                snapshots.append(snapshot)
                started.set()
                await asyncio.Event().wait()

        with patch.object(media, "analyze", side_effect=analyze):
            await self.bot.handle(message("https://youtu.be/video", user=2))
            await started.wait()
            await self.bot.handle(message("/cookies example.com", user=1))
        self.assertFalse(self.bot.jobs)
        self.assertTrue(all(not path.exists() for path in snapshots))
        update = message("", user=1)
        update["message"]["document"] = {"file_id": "owner-export", "file_size": 100}
        await self.bot.handle(update)
        await finish(self.bot)
        self.assertIn("new-owner-cookie", self.read_cookie(url="https://example.com/video"))

    async def test_custom_site_import_button_remove_and_private_contact(self):
        await self.bot.handle(message("/cookies example.com", user=2))
        self.assertEqual(self.bot.controls.pending[(2, 2)][0], "example.com")
        update = message("", user=2)
        update["message"]["document"] = {"file_id": "file", "file_size": 100, "file_name": "../../access.json"}
        await self.bot.handle(update)
        await finish(self.bot)
        self.assertTrue(self.stores.for_user(2).has_site("example.com"))
        remove = next(button["callback_data"] for row in self.api.messages[-1]["keyboard"] for button in row if button["text"] == "Delete example.com")
        await self.bot.handle(callback(remove, user=3, chat=2))
        self.assertTrue(self.stores.for_user(2).has_site("example.com"))
        await self.bot.handle(callback(remove, user=2))
        await self.bot.handle(callback(self.api.messages[-1]["keyboard"][0][0]["callback_data"], user=2))
        self.assertFalse(self.stores.for_user(2).has_site("example.com"))
        add = next(button["callback_data"] for row in self.api.messages[-1]["keyboard"] for button in row if button["text"] == "Add another site")
        await self.bot.handle(callback(add, user=2))
        await self.bot.handle(message("another.com", user=2))
        self.assertEqual(self.bot.controls.pending[(2, 2)][0], "another.com")
        await self.bot.handle(message("/start", user=99))
        self.assertIn("@sorrow_climax", self.api.messages[-1]["text"])

    async def test_version_one_migration_and_atomic_sharing_failure_preserve_membership(self):
        path = self.root / "old.json"
        path.write_text(json.dumps({"version": 1, "allowed_users": [2]}))
        access = AccessStore(path, {1})
        self.assertTrue(access.allows(2))
        with patch("vidfetch_bot.access.os.fsync", side_effect=OSError):
            with self.assertRaises(OSError):
                access.share_cookies(2, 1)
        self.assertFalse(access.shares)
        self.assertEqual(json.loads(path.read_text())["version"], 1)
        access.share_cookies(2, 1)
        self.assertEqual(json.loads(path.read_text())["version"], 2)
        self.assertEqual(AccessStore(path, {1}).shares[2], {"*": 1})

    async def test_large_domain_lists_have_bounded_messages_and_callback_payloads(self):
        for index in range(10):
            site = ("a" * 60) + f".site{index}.example.com"
            self.stores.for_user(2).import_bytes(site, cookie(site))
        await self.bot.handle(message("/cookies", user=2))
        for _ in range(3):
            current = self.api.messages[-1]
            self.assertLess(len(current["text"].encode("utf-16-le")) // 2, 4096)
            buttons = [button for row in current["keyboard"] for button in row]
            self.assertTrue(all(len(button["callback_data"].encode()) <= 64 for button in buttons))
            next_button = next((button for button in buttons if button["text"] == "More sites"), None)
            if next_button:
                await self.bot.handle(callback(next_button["callback_data"], user=2))
