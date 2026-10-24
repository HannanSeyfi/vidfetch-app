import asyncio
import json
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from vidfetch_bot import media


def fmt(identifier, *, height=None, video="h264", audio="none", size=None, bitrate=None):
    return {
        "format_id": identifier,
        "height": height,
        "width": height * 2 if height else None,
        "vcodec": video,
        "acodec": audio,
        "filesize": size,
        "tbr": bitrate,
        "ext": "m4a" if video == "none" else "mp4",
        "url": "https://example.com/video",
    }


class QualityTests(unittest.TestCase):
    def test_original_audio_estimate_uses_original_bytes_instead_of_aac_bitrate(self):
        opus = fmt("a", video="none", audio="opus", size=10_000_000, bitrate=128)
        self.assertEqual(media.estimate_audio_size(opus, 100, preserve_quality=True), 10_000_000)
        self.assertIsNone(
            media.estimate_audio_size(
                fmt("combined", height=720, audio="opus", size=99_000_000),
                100,
                preserve_quality=True,
            )
        )

    def test_separate_audio_is_included_in_each_size(self):
        info = {
            "duration": 100,
            "formats": [
                fmt("audio", video="none", audio="aac", size=2_000_000),
                fmt("v360", height=360, size=10_000_000),
                fmt("v720", height=720, size=40_000_000),
            ],
        }
        qualities = media.qualities_from_info(info)
        self.assertEqual(
            [(q.height, q.selector, q.size) for q in qualities],
            [
                (720, "v720+audio", 42_000_000),
                (360, "v360+audio", 12_000_000),
                (None, "audio", 2_000_000),
            ],
        )
        self.assertEqual(qualities[0].label, "720p · ~42.0 MB")
        self.assertTrue(qualities[-1].audio_only)
        self.assertEqual(qualities[-1].label, "Audio only · ~2.0 MB")

    def test_missing_audio_size_does_not_understate_total(self):
        qualities = media.qualities_from_info(
            {
                "formats": [
                    fmt("a", video="none", audio="aac"),
                    fmt("v", height=720, size=40_000_000),
                ]
            }
        )
        self.assertIsNone(qualities[0].size)
        self.assertIn("size unknown", qualities[0].label)

    def test_estimate_precedence_and_bitrate_units(self):
        self.assertEqual(
            media.estimate_size({"filesize": 40, "filesize_approx": 80, "tbr": 8}, 5), 40
        )
        self.assertEqual(media.estimate_size({"filesize_approx": 80, "tbr": 8}, 5), 80)
        self.assertEqual(media.estimate_size({"tbr": 800}, 10), 1_000_000)
        self.assertIsNone(media.estimate_size({"tbr": 800}, 0))
        self.assertIsNone(media.estimate_size({"filesize": float("inf")}, 10))

    def test_combined_unknown_codec_resolution_and_duplicate_height(self):
        info = {
            "formats": [
                fmt("low", height=360, video=None, audio=None, size=10_000_000),
                fmt("mid", height=720, video=None, audio=None, size=20_000_000),
                fmt("high", height=720, video=None, audio=None, size=60_000_000),
            ]
        }
        qualities = media.qualities_from_info(info)
        self.assertEqual(len([q for q in qualities if not q.audio_only]), 2)
        self.assertEqual(qualities[0].selector, "high")
        self.assertIn("compress", qualities[0].label)

    def test_silent_video_and_unknown_resolution_are_supported(self):
        self.assertEqual(
            media.qualities_from_info({"formats": [fmt("silent", height=360)]})[0].selector,
            "silent",
        )
        self.assertEqual(
            media.qualities_from_info({"formats": [fmt("direct", audio="aac")]})[0].height, None
        )

    def test_audio_only_link_has_only_an_audio_option(self):
        qualities = media.qualities_from_info({"formats": [fmt("a", video="none", audio="aac")]})
        self.assertEqual(len(qualities), 1)
        self.assertTrue(qualities[0].audio_only)
        self.assertEqual(qualities[0].selector, "a")

    def test_drm_video_and_audio_are_rejected(self):
        for formats in (
            [dict(fmt("a", video="none", audio="aac"), has_drm=True)],
            [dict(fmt("v", height=720), has_drm=True)],
        ):
            with self.subTest(formats=formats), self.assertRaises(media.MediaError):
                media.qualities_from_info({"formats": formats})

    def test_combined_source_audio_estimate_excludes_video_bytes(self):
        info = {
            "duration": 100,
            "formats": [
                dict(fmt("low", height=360, audio="aac", size=10_000_000), abr=96),
                dict(fmt("high", height=720, audio="aac", size=30_000_000), abr=128),
            ],
        }
        audio = media.qualities_from_info(info)[-1]
        self.assertTrue(audio.audio_only)
        self.assertEqual(audio.selector, "low")
        self.assertEqual(audio.size, 1_224_000)

    def test_known_silent_video_has_no_audio_option(self):
        qualities = media.qualities_from_info({"formats": [fmt("silent", height=720)]})
        self.assertFalse(any(q.audio_only for q in qualities))

    def test_transcoded_audio_estimates_follow_output_bitrate_and_unknown_duration(self):
        opus = fmt("a", video="none", audio="opus", size=10_000_000, bitrate=128)
        self.assertEqual(media.estimate_audio_size(opus, 100), 2_448_000)
        self.assertIsNone(media.estimate_audio_size(opus, 0))
        self.assertIsNone(media.estimate_audio_size(fmt("v", height=720, audio="aac"), 100))

    def test_large_audio_button_shows_compression_marker(self):
        audio = media.Quality(None, "audio", 60_000_000, audio_only=True)
        self.assertEqual(audio.label, "Audio only · ~60.0 MB · compress")

    def test_direct_mp4_preference_on_the_same_site_as_android(self):
        info = {
            "webpage_url": "https://www.pornhub.com/view_video.php?viewkey=example",
            "formats": [
                fmt("direct", height=720, audio="aac", size=30_000_000),
                dict(fmt("hls", height=720, audio="aac", size=35_000_000), ext="ts"),
            ],
        }
        self.assertEqual(media.qualities_from_info(info)[0].selector, "direct")

    def test_encoding_budget_accounts_for_audio_and_never_upscales(self):
        info = media.Probe(600, 1920, 1080, "vp9", "yuv420p", "opus")
        video_rate, audio_rate, filters = media.encoding_plan(info, 46_000_000)
        self.assertLess((video_rate + audio_rate) * info.duration / 8, 46_000_000)
        self.assertGreater(video_rate, 0)
        self.assertIn("setsar=1", filters)
        self.assertLess(media.encoding_plan(info, 46_000_000, 1)[0], video_rate)


class ProcessTests(unittest.IsolatedAsyncioTestCase):
    async def test_download_has_no_artificial_file_size_cap(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.mp4"
            source.write_bytes(b"fixture")
            with (
                patch.object(media, "validate_url", AsyncMock()),
                patch.object(
                    media, "command", AsyncMock(return_value=json.dumps(str(source)))
                ) as run,
            ):
                self.assertEqual(
                    await media.download(
                        "https://example.com/v", media.Quality(720, "v", None), source.parent
                    ),
                    source.resolve(),
                )
                self.assertNotIn("--max-filesize", run.call_args.args[0])

    async def test_low_disk_space_still_stops_downloads(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("shutil.disk_usage", return_value=type("Disk", (), {"free": 1})()):
                with self.assertRaisesRegex(media.MediaError, "disk space"):
                    await media.command(
                        [sys.executable, "-c", "pass"],
                        timeout=1,
                        folder=Path(directory),
                        download_guard=True,
                    )

    async def test_incompatible_original_video_is_a_document_without_transcoding(self):
        info = media.Probe(20, 1920, 1080, "vp9", "yuv420p", "opus")
        source = Path("original.webm")
        with (
            patch.object(media, "probe", AsyncMock(return_value=info)),
            patch.object(media, "command", AsyncMock()) as encode,
        ):
            prepared = await media.prepare_video(source, AsyncMock(), preserve_quality=True)
            self.assertEqual(prepared.path, source)
            self.assertTrue(prepared.document)
            self.assertFalse(prepared.compressed)
            encode.assert_not_awaited()

    async def test_cancel_also_stops_an_extractors_child_process(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            pidfile = folder / "child.json"
            child = (
                "import pathlib, os, time; "
                f"pathlib.Path({str(pidfile)!r}).write_text(str(os.getpid())); time.sleep(60)"
            )
            parent = f"import subprocess, sys; subprocess.run([sys.executable, '-c', {child!r}])"
            task = asyncio.create_task(
                media.command([sys.executable, "-c", parent], timeout=70, folder=folder)
            )
            for _ in range(100):
                if pidfile.exists() and pidfile.read_text():
                    break
                await asyncio.sleep(0.02)
            self.assertTrue(pidfile.exists())
            pid = int(pidfile.read_text())
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            if sys.platform == "win32":
                status = subprocess.check_output(
                    ["tasklist", "/FI", f"PID eq {pid}", "/NH"], text=True
                )
                self.assertNotIn(str(pid), status)
            else:
                # A terminated orphan can briefly be a zombie until init reaps it.
                state = Path(f"/proc/{pid}/stat")
                self.assertTrue(not state.exists() or state.read_text().split()[2] == "Z")

    async def test_rejects_non_public_urls_and_credentials(self):
        for url in (
            "file:///etc/passwd",
            "ftp://example.com/video",
            "https://user:pass@example.com/",
            "http://127.0.0.1/",
            "http://[::1]/",
            "https://example.com:2222/video",
        ):
            with self.subTest(url=url), self.assertRaises(media.MediaError):
                await media.validate_url(url)

    async def test_public_dns_allowed_and_mixed_dns_rejected(self):
        loop = asyncio.get_running_loop()
        public = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        private = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 443))
        with patch.object(loop, "getaddrinfo", AsyncMock(return_value=[public])):
            self.assertEqual(
                await media.validate_url("https://example.com/video"), "https://example.com/video"
            )
        with patch.object(loop, "getaddrinfo", AsyncMock(return_value=[public, private])):
            with self.assertRaises(media.MediaError):
                await media.validate_url("https://example.com/video")

    async def test_cancel_terminates_the_real_child_before_return(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            pidfile = folder / "started.json"
            code = (
                "import json, os, pathlib, time; "
                f"pathlib.Path({str(pidfile)!r}).write_text(json.dumps(os.getpid())); time.sleep(60)"
            )
            task = asyncio.create_task(
                media.command([sys.executable, "-c", code], timeout=70, folder=folder)
            )
            for _ in range(100):
                if pidfile.exists():
                    break
                await asyncio.sleep(0.02)
            self.assertTrue(pidfile.exists())
            pid = json.loads(pidfile.read_text())
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            # Checking the PID must not signal/kill an unrelated process.
            if sys.platform != "win32":
                import os

                with self.assertRaises(ProcessLookupError):
                    os.kill(pid, 0)
            # Windows cannot remove this directory if the child still owns the stderr handle.

    async def test_timeout_is_actionable_and_reaps_process(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(media.MediaError, "too long"):
                await media.command(
                    [sys.executable, "-c", "import time; time.sleep(60)"],
                    timeout=0.05,
                    folder=Path(directory),
                )

    async def test_subprocess_errors_do_not_expose_urls(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(media.MediaError) as caught:
                await media.command(
                    [
                        sys.executable,
                        "-c",
                        "import sys; print('secret-url HTTP 403', file=sys.stderr); sys.exit(1)",
                    ],
                    timeout=5,
                    folder=Path(directory),
                )
            self.assertIn("HTTP 403", str(caught.exception))
            self.assertNotIn("secret-url", str(caught.exception))
