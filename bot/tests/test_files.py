import asyncio
import hashlib
import subprocess
import sys
import tempfile
import unittest
from contextlib import aclosing
from pathlib import Path

from vidfetch_bot.files import file_hash, file_parts, join_program


class FileTests(unittest.IsolatedAsyncioTestCase):
    async def test_parts_rejoin_byte_for_byte_and_are_cleaned_after_delivery(self):
        for size in (32, 33, 64, 65):
            with self.subTest(size=size), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                original = root / "source.mp4"
                payload = bytes(range(size))
                original.write_bytes(payload)
                digest = await file_hash(original)
                self.assertEqual(digest, hashlib.sha256(payload).hexdigest())
                received = root / "received"
                received.mkdir()
                async with aclosing(file_parts(original, 32, "restored.mp4")) as parts:
                    async for path, index, count in parts:
                        self.assertLessEqual(index, count)
                        self.assertLessEqual(path.stat().st_size, 32)
                        (received / path.name).write_bytes(path.read_bytes())
                self.assertFalse(list(root.glob("*.part*")))
                script = received / "join.py"
                script.write_text(
                    join_program("restored.mp4", count, size, digest), encoding="utf-8"
                )
                await asyncio.to_thread(
                    subprocess.run, [sys.executable, str(script)], check=True, capture_output=True
                )
                self.assertEqual((received / "restored.mp4").read_bytes(), payload)

    async def test_corrupt_or_missing_parts_do_not_create_a_completed_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "join.py"
            script.write_text(join_program("video.mp4", 2, 4, "0" * 64), encoding="utf-8")
            for contents in (None, b"bad"):
                if contents:
                    (root / "video.mp4.part0001").write_bytes(contents)
                    (root / "video.mp4.part0002").write_bytes(contents)
                result = await asyncio.to_thread(
                    subprocess.run, [sys.executable, str(script)], capture_output=True
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((root / "video.mp4").exists())
                self.assertFalse((root / "video.mp4.joining").exists())

    async def test_cancel_or_failed_send_releases_current_part_and_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.mp4"
            source.write_bytes(b"x" * 100)
            for exception in (asyncio.CancelledError, RuntimeError):
                with self.assertRaises(exception):
                    async with aclosing(file_parts(source, 32, "video.mp4")) as parts:
                        async for path, _, _ in parts:
                            self.assertTrue(path.exists())
                            raise exception
                self.assertFalse(list(root.glob("*.part*")))
            source.unlink()  # On Windows an unclosed source handle would prevent this.
