"""Real synthetic videos and local HTTP; no bot credential or external video site."""

import asyncio
import functools
import http.server
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from vidfetch_bot import media


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def copyfile(self, source, outputfile):
        try:
            super().copyfile(source, outputfile)
        except (BrokenPipeError, ConnectionResetError):
            pass  # yt-dlp intentionally closes metadata sniffing requests early.


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg/ffprobe required")
class RealMediaTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.root = Path(cls.directory.name)
        cls.source = cls.root / "fixture.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=960x540:rate=30:duration=6",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:sample_rate=48000:duration=6",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-crf",
                "8",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-shortest",
                str(cls.source),
            ],
            check=True,
        )
        cls.silent = cls.root / "silent.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(cls.source),
                "-c:v",
                "copy",
                "-an",
                str(cls.silent),
            ],
            check=True,
        )
        cls.audio = cls.root / "track.m4a"
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(cls.source),
                "-vn",
                "-c:a",
                "copy",
                str(cls.audio),
            ],
            check=True,
        )
        cls.opus = cls.root / "track.opus"
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(cls.source),
                "-vn",
                "-c:a",
                "libopus",
                "-b:a",
                "96k",
                str(cls.opus),
            ],
            check=True,
        )

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    async def test_video_above_50_mb_is_not_reencoded_or_reduced(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "original.mp4"
            shutil.copy2(self.source, source)
            with source.open("ab") as stream:
                stream.truncate(60_000_000)
            prepared = await media.prepare_video(source, AsyncMock(), preserve_quality=True)
            self.assertEqual(prepared.path, source)
            self.assertEqual(prepared.path.stat().st_size, 60_000_000)
            self.assertEqual(prepared.probe.height, 540)
            self.assertFalse(prepared.compressed)
            self.assertFalse(prepared.document)

    async def test_original_audio_codec_survives_even_when_above_a_simulated_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.opus"
            shutil.copy2(self.opus, source)
            prepared = await media.prepare_audio(
                source, AsyncMock(), limit=100, preserve_quality=True
            )
            self.assertGreater(prepared.path.stat().st_size, 100)
            self.assertEqual(prepared.probe.audio_codec, "opus")
            self.assertFalse(prepared.compressed)
            self.assertTrue(prepared.document)
            self.assertAlmostEqual(prepared.probe.duration, 6, delta=0.2)

    async def test_original_mkv_is_remuxed_without_changing_video_or_audio_packets(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.mkv"
            subprocess.run(
                ["ffmpeg", "-v", "error", "-i", str(self.source), "-c", "copy", str(source)],
                check=True,
            )
            prepared = await media.prepare_video(
                source, AsyncMock(), limit=100, preserve_quality=True
            )
            self.assertFalse(prepared.compressed)
            self.assertGreater(prepared.path.stat().st_size, 100)

            def packets(path):
                import json

                data = json.loads(
                    subprocess.check_output(
                        [
                            "ffprobe",
                            "-v",
                            "error",
                            "-show_packets",
                            "-show_data_hash",
                            "sha256",
                            "-show_entries",
                            "packet=stream_index,data_hash",
                            "-of",
                            "json",
                            str(path),
                        ]
                    )
                )
                return data["packets"]

            # Container interleaving can change, so compare packets within each stream.
            before, after = packets(source), packets(prepared.path)
            for stream in (0, 1):
                self.assertEqual(
                    [p["data_hash"] for p in before if p["stream_index"] == stream],
                    [p["data_hash"] for p in after if p["stream_index"] == stream],
                )

    async def test_full_duration_and_audio_survive_forced_size_compression(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.mp4"
            shutil.copy2(self.source, source)
            self.assertGreater(source.stat().st_size, 500_000)
            updates = []

            async def status(text):
                updates.append(text)

            prepared = await media.prepare_video(source, status, limit=500_000, target=430_000)
            self.assertTrue(prepared.compressed)
            self.assertLessEqual(prepared.path.stat().st_size, 500_000)
            self.assertEqual(prepared.probe.video_codec, "h264")
            self.assertEqual(prepared.probe.audio_codec, "aac")
            self.assertAlmostEqual(prepared.probe.duration, 6, delta=0.2)
            self.assertLessEqual(prepared.probe.height, 540)
            self.assertTrue(any("Compressing" in update for update in updates))
            # Decode every frame, detecting truncation/corrupt output rather than just a valid header.
            await media.command(
                ["ffmpeg", "-v", "error", "-i", str(prepared.path), "-f", "null", "-"],
                timeout=30,
                folder=source.parent,
            )

    async def test_small_compatible_video_is_remuxed_without_quality_loss(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.mp4"
            shutil.copy2(self.source, source)
            prepared = await media.prepare_video(source, AsyncMock())
            self.assertFalse(prepared.compressed)
            self.assertEqual((prepared.probe.width, prepared.probe.height), (960, 540))
            self.assertEqual(prepared.probe.audio_codec, "aac")
            self.assertAlmostEqual(prepared.probe.duration, 6, delta=0.2)

    async def test_silent_video_remains_silent_after_compression(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.mp4"
            shutil.copy2(self.silent, source)
            prepared = await media.prepare_video(source, AsyncMock(), limit=400_000, target=330_000)
            self.assertTrue(prepared.compressed)
            self.assertIsNone(prepared.probe.audio_codec)
            self.assertAlmostEqual(prepared.probe.duration, 6, delta=0.2)
            self.assertLessEqual(prepared.path.stat().st_size, 400_000)

    async def test_extract_audio_from_video_without_reencoding_aac_or_retaining_video(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.mp4"
            shutil.copy2(self.source, source)
            prepared = await media.prepare_audio(source, AsyncMock())
            self.assertFalse(prepared.compressed)
            self.assertEqual(prepared.path.suffix, ".m4a")
            final = await media.probe_audio(prepared.path, audio_only=True)
            self.assertEqual(final.audio_codec, "aac")
            self.assertAlmostEqual(final.duration, 6, delta=0.2)
            self.assertLess(prepared.path.stat().st_size, source.stat().st_size)

            # Compare the actual AAC packets, proving that the successful copy path
            # preserves the original audio rather than silently recompressing it.
            def packets(path):
                return subprocess.check_output(
                    [
                        "ffmpeg",
                        "-v",
                        "error",
                        "-i",
                        str(path),
                        "-map",
                        "0:a:0",
                        "-c:a",
                        "copy",
                        "-f",
                        "adts",
                        "-",
                    ]
                )

            self.assertEqual(packets(source), packets(prepared.path))

    async def test_audio_compression_fits_budget_and_keeps_full_track(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.m4a"
            shutil.copy2(self.audio, source)
            self.assertGreater(source.stat().st_size, 40_000)
            prepared = await media.prepare_audio(source, AsyncMock(), limit=40_000, target=32_000)
            self.assertTrue(prepared.compressed)
            self.assertLessEqual(prepared.path.stat().st_size, 40_000)
            final = await media.probe_audio(prepared.path, audio_only=True)
            self.assertAlmostEqual(final.duration, 6, delta=0.2)
            await media.command(
                ["ffmpeg", "-v", "error", "-i", str(prepared.path), "-f", "null", "-"],
                timeout=30,
                folder=source.parent,
            )

    async def test_opus_audio_is_converted_to_aac_m4a(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.opus"
            shutil.copy2(self.opus, source)
            prepared = await media.prepare_audio(source, AsyncMock())
            self.assertEqual(prepared.path.suffix, ".m4a")
            final = await media.probe_audio(prepared.path, audio_only=True)
            self.assertEqual(final.audio_codec, "aac")
            self.assertAlmostEqual(final.duration, 6, delta=0.2)

    async def test_requesting_audio_from_silent_clip_returns_a_clear_error(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.mp4"
            shutil.copy2(self.silent, source)
            with self.assertRaisesRegex(media.MediaError, "valid audio track"):
                await media.prepare_audio(source, AsyncMock())

    async def test_real_audio_only_link_analysis_download_and_preparation(self):
        handler = functools.partial(QuietHandler, directory=str(self.root))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_port}/track.m4a"
        try:
            with (
                tempfile.TemporaryDirectory() as directory,
                patch.object(media, "validate_url", AsyncMock(side_effect=lambda value: value)),
            ):
                folder = Path(directory)
                analysis = await media.analyze(url, folder)
                # Generic extractor metadata may omit codec information. Prefer
                # the explicit audio choice even when it also offers a video guess.
                quality = next(q for q in analysis.qualities if q.audio_only)
                downloaded = await media.download(url, quality, folder)
                prepared = await media.prepare_audio(downloaded, AsyncMock())
                final = await media.probe_audio(prepared.path, audio_only=True)
                self.assertEqual(final.audio_codec, "aac")
                self.assertAlmostEqual(final.duration, 6, delta=0.2)
                self.assertFalse(prepared.compressed)
        finally:
            await asyncio.to_thread(server.shutdown)
            server.server_close()
            thread.join(timeout=5)

    async def test_actual_ytdlp_analysis_download_and_final_video_validation(self):
        handler = functools.partial(QuietHandler, directory=str(self.root))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_port}/fixture.mp4"
        try:
            with (
                tempfile.TemporaryDirectory() as directory,
                patch.object(media, "validate_url", AsyncMock(side_effect=lambda value: value)),
            ):
                folder = Path(directory)
                analysis = await media.analyze(url, folder)
                self.assertEqual(len([q for q in analysis.qualities if not q.audio_only]), 1)
                downloaded = await media.download(url, analysis.qualities[0], folder)
                self.assertEqual(downloaded.read_bytes(), self.source.read_bytes())
                prepared = await media.prepare_video(downloaded, AsyncMock())
                self.assertEqual(prepared.probe.audio_codec, "aac")
                self.assertEqual(prepared.probe.height, 540)
        finally:
            await asyncio.to_thread(server.shutdown)
            server.server_close()
            thread.join(timeout=5)

    async def test_audio_only_file_is_never_accepted_as_a_video(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "audio.m4a"
            subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(self.source),
                    "-vn",
                    "-c:a",
                    "copy",
                    str(source),
                ],
                check=True,
            )
            with self.assertRaisesRegex(media.MediaError, "valid, finished video"):
                await media.prepare_video(source, AsyncMock())
