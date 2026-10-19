"""Extraction, size estimates, and verified Telegram-compatible compression."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import math
import os
import re
import shutil
import signal
import socket
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

UPLOAD_LIMIT = 49_000_000  # Below the cloud Bot API's 50 MB limit, in bytes.
TARGET_BYTES = 46_000_000
DOWNLOAD_LIMIT = 2_000_000_000
MAX_DURATION = 4 * 60 * 60
Status = Callable[[str], Awaitable[None]]


class MediaError(Exception):
    """A safe, actionable message that can be displayed in Telegram."""


@dataclass(frozen=True)
class Quality:
    height: int | None
    selector: str
    size: int | None

    @property
    def label(self) -> str:
        resolution = f"{self.height}p" if self.height else "Best available"
        size = f"~{format_size(self.size)}" if self.size else "size unknown"
        compress = " · compress" if self.size and self.size > UPLOAD_LIMIT else ""
        return f"{resolution} · {size}{compress}"


@dataclass(frozen=True)
class Analysis:
    title: str
    qualities: tuple[Quality, ...]


@dataclass(frozen=True)
class Probe:
    duration: float
    width: int
    height: int
    video_codec: str
    pixel_format: str
    audio_codec: str | None
    fps: float = 30
    video_index: int = 0
    audio_index: int | None = None


@dataclass(frozen=True)
class PreparedVideo:
    path: Path
    probe: Probe
    compressed: bool


def number(value: object) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) and result > 0 else 0
    except (TypeError, ValueError):
        return 0


def format_size(size: int) -> str:
    # Decimal MB matches the upload budget and avoids MiB/MB ambiguity.
    return f"{size / 1_000_000:.1f} MB"


def estimate_size(fmt: dict, duration: float) -> int | None:
    for key in ("filesize", "filesize_approx"):
        if value := number(fmt.get(key)):
            return math.ceil(value)
    bitrate = number(fmt.get("tbr"))
    if not bitrate:
        bitrate = number(fmt.get("vbr")) + number(fmt.get("abr"))
    return math.ceil(duration * bitrate * 1000 / 8) if duration and bitrate else None


def qualities_from_info(info: dict) -> tuple[Quality, ...]:
    """Ask yt-dlp to select formats so displayed sizes match the download selector."""
    from yt_dlp import YoutubeDL

    formats = [f for f in info.get("formats", [info]) if not f.get("has_drm")]
    heights = sorted(
        {int(h) for f in formats if f.get("vcodec") != "none" and (h := number(f.get("height")))},
        reverse=True,
    )
    duration = number(info.get("duration"))
    result = []
    host = (urlsplit(info.get("webpage_url") or "").hostname or "").lower()
    direct_mp4_first = host == "pornhub.com" or host.endswith(".pornhub.com")
    # The extractor returns formats sorted by yt-dlp's configured preference.
    context = {
        "formats": formats,
        "has_merged_format": any(
            f.get("vcodec") != "none" and f.get("acodec") != "none" for f in formats
        ),
        "incomplete_formats": not any(f.get("vcodec") == "none" for f in formats),
    }
    with YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
        for height in heights or [None]:
            ceiling = f"[height<={height}]" if height else ""
            selector = f"bv{ceiling}+ba/b{ceiling}/bv{ceiling}"
            if direct_mp4_first:
                selector = f"b[ext=mp4]{ceiling}/" + selector
            selected = list(ydl.build_format_selector(selector)(context))
            if not selected:
                continue
            chosen = selected[-1]
            actual_height = int(number(chosen.get("height"))) or None
            if any(q.height == actual_height for q in result):
                continue
            streams = chosen.get("requested_formats") or [chosen]
            sizes = [estimate_size(stream, duration) for stream in streams]
            size = sum(sizes) if all(s is not None for s in sizes) else None
            # Use the exact selected IDs on re-extraction, rather than guessing again.
            identifiers = [str(stream.get("format_id", "")) for stream in streams]
            if not all(re.fullmatch(r"[\w.-]+", value, flags=re.ASCII) for value in identifiers):
                continue
            result.append(Quality(actual_height, "+".join(identifiers), size))
    if not result:
        raise MediaError("No downloadable video qualities were found for this link.")
    return tuple(result)


async def validate_url(url: str) -> str:
    try:
        parts = urlsplit(url)
        host = parts.hostname
        port = parts.port
        if parts.scheme not in {"http", "https"} or not host or parts.username or parts.password:
            raise ValueError
        if port not in {None, 80, 443} or len(url) > 4096:
            raise ValueError
        addresses = await asyncio.get_running_loop().getaddrinfo(
            host, port or (443 if parts.scheme == "https" else 80), type=socket.SOCK_STREAM
        )
        if not addresses or any(
            not ipaddress.ip_address(item[4][0]).is_global for item in addresses
        ):
            raise ValueError
    except (ValueError, OSError):
        raise MediaError("Send a public http:// or https:// video link.") from None
    return url


async def command(
    args: list[str], *, timeout: int, folder: Path, download_guard: bool = False
) -> str:
    """Cancel/timeout always reaps the child before the caller deletes its files."""
    log_path = folder / "process.stderr"
    with log_path.open("wb") as log:
        process = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=log, start_new_session=os.name != "nt"
        )
        communicate = asyncio.create_task(process.communicate())
        try:
            async with asyncio.timeout(timeout):
                while not communicate.done():
                    await asyncio.wait({communicate}, timeout=1)
                    if download_guard:
                        total = 0
                        for path in folder.rglob("*"):
                            try:
                                if path.is_file():
                                    total += path.stat().st_size
                            except FileNotFoundError:
                                pass  # yt-dlp removes intermediates when merging finishes.
                        if total > DOWNLOAD_LIMIT or shutil.disk_usage(folder).free < 256_000_000:
                            raise MediaError(
                                "This download exceeds the session's 2 GB storage budget."
                            )
                output, _ = await communicate
        except TimeoutError:
            raise MediaError(
                "This operation took too long. Try a shorter video or lower quality."
            ) from None
        finally:
            if process.returncode is None:
                if os.name == "nt":
                    # yt-dlp can itself spawn FFmpeg; reap that child as well.
                    killer = await asyncio.create_subprocess_exec(
                        "taskkill",
                        "/PID",
                        str(process.pid),
                        "/T",
                        "/F",
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL,
                    )
                    await killer.wait()
                else:
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                try:
                    await asyncio.wait_for(process.wait(), timeout=5)
                except TimeoutError:
                    try:
                        if os.name == "nt":
                            process.kill()
                        else:
                            os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    await process.wait()
            if os.name != "nt":
                # The parent may exit before a Deno/FFmpeg descendant releases stdout.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if not communicate.done():
                communicate.cancel()
            await asyncio.gather(communicate, return_exceptions=True)
    if process.returncode:
        # Never forward extractor URLs, cookies or arbitrary subprocess logs to chats.
        detail = log_path.read_text(encoding="utf-8", errors="replace").lower()
        if "sign in" in detail or "cookies" in detail or "login" in detail:
            raise MediaError(
                "This site requires sign-in or rejected this session. Try a public video."
            )
        if "403" in detail or "429" in detail or "not a bot" in detail:
            raise MediaError(
                "The site blocked this Colab connection. Try again later or use the Android app."
            )
        if "requested format" in detail:
            raise MediaError(
                "That quality is no longer available. Send the link again to refresh it."
            )
        raise MediaError(
            "The media tool could not finish. The link may be unsupported or unavailable."
        )
    if len(output) > 16_000_000:
        raise MediaError("The site returned too much metadata. Send a single-video link.")
    return output.decode("utf-8", errors="replace").strip()


def extractor_args() -> list[str]:
    import deno

    return [
        sys.executable,
        "-m",
        "yt_dlp",
        "--ignore-config",
        "--no-cache-dir",
        "--no-playlist",
        "--playlist-items",
        "1",
        "--socket-timeout",
        "25",
        "--retries",
        "3",
        "--fragment-retries",
        "3",
        "--abort-on-unavailable-fragments",
        "--no-progress",
        "--no-warnings",
        "--js-runtimes",
        f"deno:{deno.find_deno_bin()}",
        "--format-sort",
        "res,vcodec:h264,acodec:aac",
    ]


async def analyze(url: str, folder: Path) -> Analysis:
    await validate_url(url)
    raw = await command(
        extractor_args() + ["--dump-single-json", "--skip-download", "--", url],
        timeout=180,
        folder=folder,
    )
    try:
        info = json.loads(raw)
        if info.get("_type") in {"playlist", "multi_video"} or info.get("entries") is not None:
            raise MediaError("Send a single-video link rather than a playlist.")
        if info.get("is_live") or info.get("live_status") == "is_live":
            raise MediaError("Live streams are not supported. Send a finished video.")
        if number(info.get("duration")) > MAX_DURATION:
            raise MediaError("Choose a video shorter than four hours for this Colab session.")
        return Analysis(str(info.get("title") or "Video")[:200], qualities_from_info(info))
    except (ValueError, TypeError, KeyError):
        raise MediaError("The site did not return usable video information.") from None


async def download(url: str, quality: Quality, folder: Path) -> Path:
    # Recheck the initial host when a button is used later in the session.
    await validate_url(url)
    raw = await command(
        extractor_args()
        + [
            "--format",
            quality.selector,
            "--merge-output-format",
            "mkv",
            "--max-filesize",
            str(DOWNLOAD_LIMIT),
            "--output",
            str(folder / "source.%(ext)s"),
            "--print",
            "after_move:%(filepath)j",
            "--",
            url,
        ],
        timeout=1800,
        folder=folder,
        download_guard=True,
    )
    try:
        path = Path(json.loads(raw.splitlines()[-1])).resolve()
        if path.parent != folder.resolve() or not path.is_file() or not path.stat().st_size:
            raise ValueError
        if path.stat().st_size > DOWNLOAD_LIMIT:
            raise MediaError("This download exceeds the session's 2 GB storage budget.")
        return path
    except (ValueError, IndexError, TypeError):
        raise MediaError("The extractor did not produce a completed video file.") from None


async def probe(path: Path) -> Probe:
    raw = await command(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        timeout=30,
        folder=path.parent,
    )
    try:
        info = json.loads(raw)
        streams = info.get("streams", [])
        video = next(
            s
            for s in streams
            if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")
        )
        audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
        duration = number(info.get("format", {}).get("duration")) or number(video.get("duration"))
        width, height = int(video["width"]), int(video["height"])
        rotation = next(
            (s.get("rotation", 0) for s in video.get("side_data_list", []) if "rotation" in s), 0
        )
        if abs(float(rotation)) % 180 == 90:
            width, height = height, width
        fps_parts = video.get("avg_frame_rate", "30/1").split("/")
        fps = number(fps_parts[0]) / (number(fps_parts[-1]) or 1)
        if not duration or width < 2 or height < 2:
            raise ValueError
        if duration > MAX_DURATION:
            raise MediaError("Choose a video shorter than four hours for this Colab session.")
        return Probe(
            duration,
            width,
            height,
            video.get("codec_name", ""),
            video.get("pix_fmt", ""),
            audio.get("codec_name", "") if audio else None,
            fps or 30,
            int(video.get("index", 0)),
            int(audio["index"]) if audio else None,
        )
    except (ValueError, KeyError, StopIteration, TypeError):
        raise MediaError("The downloaded file does not contain a valid, finished video.") from None


def encoding_plan(info: Probe, target_bytes: int, attempt: int = 0) -> tuple[int, int, str]:
    total_rate = int(target_bytes * 8 / info.duration * 0.94 * 0.82**attempt)
    audio_rate = (
        (96_000 if total_rate >= 400_000 else 48_000 if total_rate >= 120_000 else 16_000)
        if info.audio_codec
        else 0
    )
    video_rate = total_rate - audio_rate
    if video_rate < 8_000:
        raise MediaError(
            "This video is too long to fit a single Telegram upload. Try a shorter clip."
        )
    fps = min(info.fps, 30 if video_rate >= 250_000 else 20 if video_rate >= 80_000 else 10)
    scale = min(
        1,
        1920 / max(info.width, info.height),
        math.sqrt(video_rate / (max(fps, 1) * 0.07 * info.width * info.height)),
    )
    width = max(2, int(info.width * scale) // 2 * 2)
    height = max(2, int(info.height * scale) // 2 * 2)
    return video_rate, audio_rate, f"scale={width}:{height},setsar=1,fps={fps:.3f}"


async def prepare_video(
    source: Path, status: Status, *, limit: int = UPLOAD_LIMIT, target: int = TARGET_BYTES
) -> PreparedVideo:
    info = await probe(source)
    output = source.parent / "telegram.mp4"
    base = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", str(source)]
    if (
        source.stat().st_size <= limit
        and info.video_codec == "h264"
        and info.pixel_format == "yuv420p"
    ):
        await status("Preparing your video for Telegram…")
        await command(
            base
            + [
                "-map",
                f"0:{info.video_index}",
                "-map",
                f"0:{info.audio_index}?" if info.audio_index is not None else "0:a:0?",
                "-sn",
                "-dn",
                "-c:v",
                "copy",
                "-c:a",
                "copy" if info.audio_codec in {None, "aac"} else "aac",
                "-movflags",
                "+faststart",
                str(output),
            ],
            timeout=300,
            folder=source.parent,
        )
        final = await probe(output)
        if output.stat().st_size <= limit:
            return PreparedVideo(output, final, False)
    await status("Compressing for Telegram… Quality may be reduced to fit the upload limit.")
    for attempt in range(3):
        rate, audio_rate, filters = encoding_plan(info, min(target, int(limit * 0.94)), attempt)
        video_args = [
            "-map",
            f"0:{info.video_index}",
            "-vf",
            filters,
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-pix_fmt",
            "yuv420p",
            "-b:v",
            str(rate),
            "-threads",
            "2",
            "-passlogfile",
            str(source.parent / "encode-pass"),
        ]
        await command(
            base + video_args + ["-pass", "1", "-an", "-sn", "-dn", "-f", "null", os.devnull],
            timeout=1800,
            folder=source.parent,
        )
        audio_args = (
            [
                "-map",
                f"0:{info.audio_index}?",
                "-c:a",
                "aac",
                "-b:a",
                str(audio_rate),
                "-ac",
                "1" if audio_rate < 48_000 else "2",
            ]
            if info.audio_codec
            else ["-an"]
        )
        await command(
            base
            + video_args
            + ["-pass", "2"]
            + audio_args
            + ["-sn", "-dn", "-movflags", "+faststart", "-metadata:s:v:0", "rotate=0", str(output)],
            timeout=1800,
            folder=source.parent,
        )
        final = await probe(output)
        if output.stat().st_size <= limit:
            # A complete clip must survive compression, including any original audio.
            if abs(final.duration - info.duration) > max(2, info.duration * 0.01):
                raise MediaError("The compressed video was incomplete. Please try a shorter clip.")
            if info.audio_codec and not final.audio_codec:
                raise MediaError("Audio was missing after compression. Please try another quality.")
            return PreparedVideo(output, final, True)
    raise MediaError("This video could not fit Telegram's limit. Try a shorter clip.")
