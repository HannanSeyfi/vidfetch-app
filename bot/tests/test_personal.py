import asyncio
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from test_app import FakeTelegram, callback, finish, message

from vidfetch_bot import media
from vidfetch_bot.access import AccessStore
from vidfetch_bot.app import Bot, Selection
from vidfetch_bot.cookies import CookieError, UserCookieStores


def cookie(site="youtube.com", value="private-user-one", name="SID"):
    return f"# Netscape HTTP Cookie File\n.{site}\tTRUE\t/\tTRUE\t0\t{name}\t{value}\n".encode()


class AccessTests(unittest.TestCase):
    def test_empty_list_is_private_and_revocations_survive_restart_and_environment_seed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state/access.json"
            store = AccessStore(path, {1}, {2})
            self.assertTrue(store.allows(1))
            self.assertTrue(store.allows(2))
            self.assertFalse(store.allows(3))
            store.deny({2})
            reloaded = AccessStore(path, {1}, {2})
            self.assertFalse(reloaded.allows(2))
            self.assertTrue(reloaded.allows(1))
            self.assertNotIn("private-user", path.read_text())

    def test_invalid_state_and_failed_writes_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "access.json"
            with self.assertRaises(ValueError):
                AccessStore(path, set())
            store = AccessStore(path, {1})
            with patch("vidfetch_bot.access.os.fsync", side_effect=OSError):
                with self.assertRaises(OSError):
                    store.allow({2})
            self.assertFalse(store.allows(2))
            self.assertEqual(json.loads(path.read_text())["allowed_users"], [])
            path.write_text('{"version": 1, "allowed_users": [true]}')
            with self.assertRaises(ValueError):
                AccessStore(path, {1})

    def test_users_cannot_select_another_directory_and_cookies_stay_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            stores = UserCookieStores(Path(directory) / "cookies")
            for invalid in ("../1", "1/2", 0, -1, True):
                with self.assertRaises(CookieError):
                    stores.for_user(invalid)
            first, second = stores.for_user(1), stores.for_user(2)
            first.import_bytes("youtube.com", cookie())
            second.import_bytes("youtube.com", cookie(value="private-user-two"))
            with tempfile.TemporaryDirectory() as job:
                for store, expected, absent in ((first, "one", "two"), (second, "two", "one")):
                    with store.snapshot_for("https://youtu.be/example", Path(job)) as path:
                        text = path.read_text()
                        self.assertIn("private-user-" + expected, text)
                        self.assertNotIn("private-user-" + absent, text)
                    self.assertFalse(path.exists())
            stores.forget(1)
            self.assertFalse(first.has_enabled())
            self.assertTrue(second.has_enabled())
            if os.name != "nt":
                self.assertEqual(second.directory.stat().st_mode & 0o777, 0o700)
                self.assertEqual((second.directory / "youtube.com.cookies").stat().st_mode & 0o777, 0o600)


class PersonalTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.api = FakeTelegram()
        self.api.read_document = AsyncMock(return_value=cookie())
        self.access = AccessStore(self.root / "access.json", {1}, {2, 3})
        self.stores = UserCookieStores(self.root / "cookies")
        self.bot = Bot(self.api, access=self.access, user_cookies=self.stores, workspace=self.root)

    async def asyncTearDown(self):
        await self.bot.close()
        self.directory.cleanup()

    def button(self, label):
        return next(button["callback_data"] for row in self.api.messages[-1]["keyboard"] for button in row if button["text"] == label)

    async def arm(self, user=2, site="YouTube"):
        await self.bot.handle(message("/cookies", user=user))
        data = self.button(f"Import / replace {site}")
        await self.bot.handle(callback(data, user=user))

    async def upload(self, user=2, size=100, name="../../somebody-elses.cookies"):
        update = message("", user=user)
        update["message"]["document"] = {"file_id": "test-cookie-file", "file_size": size, "file_name": name}
        await self.bot.handle(update)
        await finish(self.bot)

    async def test_unauthorized_users_cannot_extract_upload_or_grant_access_but_can_get_their_id(self):
        with patch.object(media, "analyze", AsyncMock()) as analyze:
            for text in ("https://example.com", "/cookies", "/allow 99", "/users"):
                await self.bot.handle(message(text, user=99))
                self.assertIn("private", self.api.messages[-1]["text"])
            await self.upload(user=99)
            await self.bot.handle(message("/id", user=99))
            self.assertIn("99", self.api.messages[-1]["text"])
            analyze.assert_not_awaited()
            self.api.read_document.assert_not_awaited()
            self.assertFalse(self.access.allows(99))
            self.assertFalse((self.stores.root / "99").exists())

    async def test_only_owner_can_manage_users_and_changes_persist(self):
        await self.bot.handle(message("/allow 99", user=2))
        self.assertFalse(self.access.allows(99))
        await self.bot.handle(message("/allow 99 100", user=1))
        self.assertTrue(self.access.allows(99))
        self.assertTrue(self.access.allows(100))
        await self.bot.handle(message("/deny 1", user=1))
        self.assertTrue(self.access.allows(1))
        await self.bot.handle(message("/users", user=1))
        self.assertIn("99", self.api.messages[-1]["text"])
        self.assertTrue(AccessStore(self.access.path, {1}).allows(100))

    async def test_cookie_import_needs_explicit_choice_is_scoped_and_ignores_uploaded_name(self):
        await self.upload()
        self.api.read_document.assert_not_awaited()
        await self.arm()
        await self.upload(size=2_000_001)
        self.api.read_document.assert_not_awaited()
        self.api.read_document.return_value = cookie() + cookie("reddit.com", "other-site", "reddit_session").split(b"\n", 1)[1]
        await self.upload()
        saved = self.stores.for_user(2).directory / "youtube.com.cookies"
        self.assertIn("private-user-one", saved.read_text())
        self.assertNotIn("other-site", saved.read_text())
        self.assertFalse(self.stores.for_user(3).has_enabled())
        output = str(self.api.messages) + str(self.api.edits)
        self.assertNotIn("private-user-one", output)
        self.assertFalse((self.root / "somebody-elses.cookies").exists())

    async def test_cookie_menus_are_owner_bound_expire_and_delete_requires_confirmation(self):
        self.stores.for_user(2).import_bytes("youtube.com", cookie())
        await self.bot.handle(message("/cookies", user=2))
        delete = self.button("Delete YouTube")
        await self.bot.handle(callback(delete, user=3, chat=2))
        self.assertTrue(self.stores.for_user(2).has_enabled())
        self.assertIn("expired", self.api.answers[-1])
        key = delete.split(":")[1]
        await self.bot.handle(callback(f"c:{key}:confirm:youtube", user=2))
        self.assertTrue(self.stores.for_user(2).has_enabled())
        await self.bot.handle(callback(delete, user=2))
        confirm = self.button("Delete my cookies")
        await self.bot.handle(callback(confirm, user=2))
        self.assertFalse(self.stores.for_user(2).has_enabled())
        await self.arm(user=2)
        self.bot.controls.pending[(2, 2)] = ("youtube.com", time.monotonic() - 1)
        await self.upload()
        self.api.read_document.assert_not_awaited()

    async def test_bad_export_preserves_working_cookies_and_groups_cannot_import(self):
        store = self.stores.for_user(2)
        store.import_bytes("youtube.com", cookie(value="keep-this-session"))
        await self.arm()
        self.api.read_document.return_value = b"not cookies: never-echo-this-private-data"
        await self.upload()
        self.assertIn("keep-this-session", (store.directory / "youtube.com.cookies").read_text())
        self.assertNotIn("never-echo", str(self.api.edits) + str(self.api.messages))
        await self.arm()
        update = message("", user=2)
        update["message"]["chat"]["type"] = "group"
        update["message"]["document"] = {"file_id": "file", "file_size": 100}
        self.api.read_document.reset_mock()
        await self.bot.handle(update)
        self.api.read_document.assert_not_awaited()

    async def test_download_uses_the_requesting_users_store_after_quality_selection(self):
        self.stores.for_user(2).import_bytes("youtube.com", cookie())
        self.stores.for_user(3).import_bytes("youtube.com", cookie(value="private-user-two"))
        seen = []

        async def download(url, quality, folder, *, cookie_store, progress=None):
            with cookie_store.snapshot_for(url, folder) as snapshot:
                seen.append(snapshot.read_text())
            source = folder / "video.mp4"
            source.write_bytes(b"video-fixture")
            return source

        async def prepare(source, status, **options):
            return media.PreparedVideo(source, media.Probe(1, 640, 360, "h264", "yuv420p", "aac"), False)

        with patch.object(media, "download", side_effect=download), patch.object(media, "prepare_video", side_effect=prepare):
            for user in (2, 3):
                key = f"choice{user}"
                self.bot.selections[key] = Selection((user, user), "https://youtu.be/example", media.Analysis("Video", (media.Quality(360, "v", 1),)), time.monotonic() + 30)
                await self.bot.handle(callback(f"q:{key}:0", user=user))
                await finish(self.bot)
        self.assertIn("private-user-one", seen[0])
        self.assertNotIn("private-user-two", seen[0])
        self.assertIn("private-user-two", seen[1])
        self.assertEqual([upload[0] for upload in self.api.uploads], [2, 3])

    async def test_disable_and_enable_are_personal_and_extraction_never_falls_back_to_other_user(self):
        self.stores.for_user(2).import_bytes("youtube.com", cookie())
        self.stores.for_user(3).import_bytes("youtube.com", cookie(value="private-user-two"))
        await self.bot.handle(message("/cookies", user=2))
        await self.bot.handle(callback(self.button("Disable YouTube"), user=2))
        self.assertFalse(self.stores.for_user(2).has_enabled())
        self.assertTrue(self.stores.for_user(3).has_enabled())
        await self.bot.handle(callback(self.button("Enable YouTube"), user=2))
        seen = []

        async def analyze(url, folder, *, cookie_store, **options):
            with cookie_store.snapshot_for(url, folder) as snapshot:
                seen.append(snapshot.read_text() if snapshot else None)
            return media.Analysis("Video", (media.Quality(360, "v", 1),))

        with patch.object(media, "analyze", side_effect=analyze):
            for user in (2, 3, 1):
                await self.bot.handle(message("https://youtu.be/example", user=user))
                await finish(self.bot)
        self.assertIn("private-user-one", seen[0])
        self.assertIn("private-user-two", seen[1])
        self.assertIsNone(seen[2])

    async def test_deny_cancels_import_before_it_can_persist_and_forgets_only_that_users_cookies(self):
        self.stores.for_user(2).import_bytes("reddit.com", cookie("reddit.com", "first", "reddit_session"))
        self.stores.for_user(3).import_bytes("youtube.com", cookie(value="other-user"))
        started = asyncio.Event()

        async def slow_file(*args, **kwargs):
            started.set()
            await asyncio.Event().wait()

        self.api.read_document.side_effect = slow_file
        await self.arm(user=2)
        update = message("", user=2)
        update["message"]["document"] = {"file_id": "file", "file_size": 100}
        await self.bot.handle(update)
        await started.wait()
        self.bot.selections["old"] = Selection((2, 2), "https://example.com", media.Analysis("old", ()), time.monotonic() + 20)
        await self.bot.handle(message("/deny 2", user=1))
        self.assertFalse(self.bot.jobs)
        self.assertFalse(self.bot.selections)
        self.assertFalse(self.access.allows(2))
        self.assertFalse((self.stores.root / "2").exists())
        self.assertTrue(self.stores.for_user(3).has_enabled())
        self.assertNotIn((2, 2), self.bot.controls.pending)
