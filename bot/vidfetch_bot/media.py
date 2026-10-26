"""Extraction and media preparation, with lossless delivery through a local Bot API."""

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
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from .cookies import CookieError, CookieStore, site_for_url

UPLOAD_LIMIT = 49_000_000  # Below the cloud Bot API's 50 MB limit, in bytes.
TARGET_BYTES = 46_000_000
MIN_FREE_BYTES = 256_000_000
AUDIO_BITRATE = 192_000
Status = Callable[[str], Awaitable[None]]


@dataclass(frozen=True)
class StorageBudget:
    """Account for a hosting quota even when statvfs reports the entire shared disk."""

    root: Path
    limit: int

    def free(self) -> int:
        used = 0
        for path in self.root.rglob("*"):
            try:
                if path.is_file():
                    used += path.stat().st_size
            except FileNotFoundError:
                # A concurrent upload or cleanup can remove a temporary file.
                continue
        return self.limit - used


STORAGE_BUDGET: StorageBudget | None = None


class MediaError(Exception):
    """A safe, actionable message that can be displayed in Telegram."""

    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


def tool_error(log: str, args: list[str]) -> MediaError:
    # Use the terminal failure, not a startup warning mentioning cookies or a URL.
    errors = [line for line in log.splitlines() if line.lstrip().startswith("ERROR:")]
    detail = (errors[-1] if errors else log).lower()
    site = site_for_url(args[-1]) if "yt_dlp" in args and args else None
    if "429" in detail or "too many requests" in detail:
        return MediaError("This site is rate limiting requests (HTTP 429). Wait before retrying.")
    if "private subreddit" in detail or "quarantined" in detail:
        return MediaError("Reddit requires cookies from an account with access to this community.")
    blocked = any(
        item in detail
        for item in (
            "403",
            "forbidden",
            "unable to access the reddit api",
            "account authentication is required",
            "impersonate target",
            "impersonation target",
        )
    )
    if site == "reddit.com" and blocked:
        return MediaError(
            "Reddit rejected this session or connection. Import fresh reddit.com cookies from "
            "Chrome, then send the full post link again. If it still fails, "
            "Reddit may be rejecting this host's network.",
            retryable=True,
        )
    if any(item in detail for item in ("sign in", "login", "authentication", "not a bot")):
        return MediaError(
            "This site requires verification or rejected the session. Import or replace its "
            "cookies, then send the link again. The site may also reject "
            "the host's network."
        )
    if blocked:
        return MediaError(
            "This site rejected the request (HTTP 403). Refresh its cookies and extractor. "
            "If it continues, try a host on another network."
        )
    if "requested format" in detail:
        return MediaError("That quality is no longer available. Send the link again to refresh it.")
    return MediaError(
        "The media tool could not finish. The link may be unsupported or unavailable."
    )


def check_disk(folder: Path) -> None:
    if STORAGE_BUDGET and STORAGE_BUDGET.free() < MIN_FREE_BYTES:
        raise MediaError(
            "This host is running out of its storage allowance. Choose a smaller quality or file."
        )
    if shutil.disk_usage(folder).free < MIN_FREE_BYTES:
        raise MediaError(
            "This session is running out of disk space. Try a smaller quality or restart."
        )


@dataclass(frozen=True)
class Quality:
    height: int | None
    selector: str
    size: int | None
    audio_only: bool = False

    @property
    def label(self) -> str:
        return self.label_for(UPLOAD_LIMIT, preserve_quality=False)

    def label_for(self, limit: int, *, preserve_quality: bool) -> str:
        resolution = (
            "Audio only"
            if self.audio_only
            else (f"{self.height}p" if self.height else "Best available")
        )
        size = f"~{format_size(self.size)}" if self.size else "size unknown"
        marker = (
            (" · split into files" if preserve_quality else " · compress")
            if self.size and self.size > limit
            else ""
        )
        return f"{resolution} · {size}{marker}"


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
    document: bool = False


@dataclass(frozen=True)
class AudioProbe:
    duration: float
    audio_codec: str
    bitrate: int
    audio_index: int


@dataclass(frozen=True)
class PreparedAudio:
    path: Path
    probe: AudioProbe
    compressed: bool
    document: bool = False


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


def is_aac(codec: str | None) -> bool:
    return codec == "aac" or bool(codec and codec.startswith("mp4a"))


def audio_bitrate(source_bitrate: float) -> int:
    return min(AUDIO_BITRATE, max(32_000, int(source_bitrate))) if source_bitrate else AUDIO_BITRATE


def estimate_audio_size(
    fmt: dict, duration: float, *, preserve_quality: bool = False
) -> int | None:
    """Estimate the delivered audio, never the full video used as a fallback source."""
    separate = fmt.get("vcodec") == "none"
    if preserve_quality:
        if separate:
            return estimate_size(fmt, duration)
        bitrate = number(fmt.get("abr"))
        return math.ceil(duration * bitrate * 1000 / 8 * 1.02) if duration and bitrate else None
    if is_aac(fmt.get("acodec")) and separate:
        return estimate_size(fmt, duration)
    bitrate = number(fmt.get("abr")) or (number(fmt.get("tbr")) if separate else 0)
    if not duration:
        return None
    if is_aac(fmt.get("acodec")):
        return math.ceil(duration * bitrate * 1000 / 8 * 1.02) if bitrate else None
    # Non-AAC sources use one known conversion bitrate, so the menu does not
    # depend on source bitrate fields that ffprobe may omit (notably for Opus).
    return math.ceil(duration * AUDIO_BITRATE / 8 * 1.02)


def qualities_from_info(info: dict, *, preserve_quality: bool = False) -> tuple[Quality, ...]:
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
        # Download a standalone audio stream if available. Otherwise take the
        # smallest-preference combined format, avoiding a full-resolution video download.
        audio_formats = list(ydl.build_format_selector("ba")(context))
        audio = (
            audio_formats[-1]
            if audio_formats
            else next(
                (f for f in formats if f.get("acodec") != "none" and f.get("vcodec") != "none"),
                None,
            )
        )
        if audio and audio.get("acodec") != "none":
            identifier = str(audio.get("format_id", ""))
            if re.fullmatch(r"[\w.-]+", identifier, flags=re.ASCII):
                result.append(
                    Quality(
                        None,
                        identifier,
                        estimate_audio_size(audio, duration, preserve_quality=preserve_quality),
                        audio_only=True,
                    )
                )
    if not result:
        raise MediaError("No downloadable video or audio was found for this link.")
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
    if download_guard:
        check_disk(folder)
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
                        check_disk(folder)
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
        raise tool_error(log_path.read_text(encoding="utf-8", errors="replace"), args)
    if len(output) > 16_000_000:
        raise MediaError("The site returned too much metadata. Send a single-video link.")
    return output.decode("utf-8", errors="replace").strip()


def extractor_args(*, cookie: Path | None = None, chrome: bool = False) -> list[str]:
    import deno

    args = [
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
    if cookie:
        args += ["--cookies", str(cookie)]
    if chrome:
        args += ["--impersonate", "chrome"]
    return args


async def extract(
    url: str,
    arguments: list[str],
    folder: Path,
    *,
    timeout: int,
    cookie_store: CookieStore | None = None,
    download_guard: bool = False,
) -> str:
    reddit = site_for_url(url) == "reddit.com"
    plugins = folder / "extractor-plugins"
    plugin = plugins / "vidfetch" / "yt_dlp_plugins" / "extractor" / "reddit_public.py"
    plugin.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(Path(__file__).with_name("reddit_public.py"), plugin)
    for chrome in (True, False) if reddit else (False,):
        context = cookie_store.snapshot_for(url, folder) if cookie_store else nullcontext(None)
        try:
            with context as cookie:
                restart = (
                    ["--force-overwrites", "--no-continue"] if reddit and download_guard else []
                )
                return await command(
                    extractor_args(cookie=cookie, chrome=chrome)
                    + ["--plugin-dirs", str(plugins)]
                    + restart
                    + arguments
                    + ["--", url],
                    timeout=timeout,
                    folder=folder,
                    download_guard=download_guard,
                )
        except CookieError as error:
            raise MediaError(str(error)) from None
        except MediaError as error:
            if not chrome or not error.retryable:
                raise
    raise AssertionError("No extraction attempt")


async def analyze(
    url: str,
    folder: Path,
    *,
    preserve_quality: bool = False,
    cookie_store: CookieStore | None = None,
) -> Analysis:
    await validate_url(url)
    raw = await extract(
        url,
        ["--dump-single-json", "--skip-download"],
        folder,
        timeout=180,
        cookie_store=cookie_store,
    )
    try:
        info = json.loads(raw)
        if info.get("_type") in {"playlist", "multi_video"} or info.get("entries") is not None:
            raise MediaError("Send a single-video link rather than a playlist.")
        if info.get("is_live") or info.get("live_status") == "is_live":
            raise MediaError("Live streams are not supported. Send a finished video.")
        return Analysis(
            str(info.get("title") or "Video")[:200],
            qualities_from_info(info, preserve_quality=preserve_quality),
        )
    except (ValueError, TypeError, KeyError):
        raise MediaError("The site did not return usable video information.") from None


async def download(
    url: str, quality: Quality, folder: Path, *, cookie_store: CookieStore | None = None
) -> Path:
    # Recheck the initial host when a button is used later in the session.
    await validate_url(url)
    raw = await extract(
        url,
        [
            "--format",
            quality.selector,
            "--merge-output-format",
            "mkv",
            "--output",
            str(folder / "source.%(ext)s"),
            "--print",
            "after_move:%(filepath)j",
        ],
        folder,
        timeout=7200,
        cookie_store=cookie_store,
        download_guard=True,
    )
    try:
        path = Path(json.loads(raw.splitlines()[-1])).resolve()
        if path.parent != folder.resolve() or not path.is_file() or not path.stat().st_size:
            raise ValueError
        return path
    except (ValueError, IndexError, TypeError):
        kind = "audio" if quality.audio_only else "video"
        raise MediaError(f"The extractor did not produce a completed {kind} file.") from None


async def probe_audio(path: Path, *, audio_only: bool = False) -> AudioProbe:
    raw = await command(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        timeout=30,
        folder=path.parent,
    )
    try:
        info = json.loads(raw)
        streams = info.get("streams", [])
        audio = next(s for s in streams if s.get("codec_type") == "audio")
        if audio_only and any(s.get("codec_type") == "video" for s in streams):
            raise ValueError
        duration = number(audio.get("duration")) or number(info.get("format", {}).get("duration"))
        if not duration or not audio.get("codec_name"):
            raise ValueError
        return AudioProbe(
            duration, audio["codec_name"], int(number(audio.get("bit_rate"))), int(audio["index"])
        )
    except (ValueError, KeyError, StopIteration, TypeError):
        raise MediaError(
            "This file does not contain a valid audio track. Try another link."
        ) from None


def check_audio_duration(original: AudioProbe, final: AudioProbe) -> None:
    if abs(final.duration - original.duration) > max(2, original.duration * 0.01):
        raise MediaError("The prepared audio was incomplete. Please try a shorter clip.")


async def prepare_audio(
    source: Path,
    status: Status,
    *,
    limit: int = UPLOAD_LIMIT,
    target: int = TARGET_BYTES,
    preserve_quality: bool = False,
) -> PreparedAudio:
    info = await probe_audio(source)
    if preserve_quality:
        extension = {"aac": ".m4a", "mp3": ".mp3"}.get(info.audio_codec, ".mka")
        output = source.parent / ("VidFetch" + extension)
        await status("Extracting the original audio without reducing quality…")
        check_disk(source.parent)
        await command(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-y",
                "-i",
                str(source),
                "-map",
                f"0:{info.audio_index}",
                "-vn",
                "-sn",
                "-dn",
                "-c:a",
                "copy",
                str(output),
            ],
            timeout=7200,
            folder=source.parent,
            download_guard=True,
        )
        final = await probe_audio(output, audio_only=True)
        check_audio_duration(info, final)
        return PreparedAudio(output, final, False, document=extension == ".mka")
    output = source.parent / "telegram.m4a"
    base = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-y",
        "-i",
        str(source),
        "-map",
        f"0:{info.audio_index}",
        "-vn",
        "-sn",
        "-dn",
    ]
    await status("Extracting audio for Telegram…")
    compressed = False
    if info.audio_codec == "aac":
        # Copying only the audio also avoids needless compression when the source
        # video is large but its AAC track already fits Telegram's upload budget.
        await command(
            base + ["-c:a", "copy", "-movflags", "+faststart", str(output)],
            timeout=300,
            folder=source.parent,
        )
        final = await probe_audio(output, audio_only=True)
        check_audio_duration(info, final)
        if output.stat().st_size <= limit:
            return PreparedAudio(output, final, False)
        compressed = True
        await status("Compressing audio to fit Telegram's upload limit…")
    preferred_rate = audio_bitrate(info.bitrate) if info.audio_codec == "aac" else AUDIO_BITRATE
    for attempt in range(3):
        budget_rate = int(min(target, limit * 0.94) * 8 / info.duration * 0.95 * 0.8**attempt)
        rate = min(preferred_rate, budget_rate)
        if rate < 16_000:
            raise MediaError(
                "This audio is too long to fit a single Telegram upload. Try a shorter clip."
            )
        if rate < preferred_rate or attempt:
            compressed = True
            await status("Compressing audio to fit Telegram's upload limit…")
        await command(
            base
            + [
                "-c:a",
                "aac",
                "-b:a",
                str(rate),
                "-ac",
                "1" if rate < 64_000 else "2",
                "-movflags",
                "+faststart",
                str(output),
            ],
            timeout=1800,
            folder=source.parent,
        )
        final = await probe_audio(output, audio_only=True)
        check_audio_duration(info, final)
        if output.stat().st_size <= limit:
            return PreparedAudio(output, final, compressed)
    raise MediaError("This audio could not fit Telegram's limit. Try a shorter clip.")


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
    source: Path,
    status: Status,
    *,
    limit: int = UPLOAD_LIMIT,
    target: int = TARGET_BYTES,
    preserve_quality: bool = False,
) -> PreparedVideo:
    info = await probe(source)
    if preserve_quality:
        # An original codec that cannot play inline is delivered as a document, not transcoded.
        compatible = (
            info.video_codec == "h264"
            and info.pixel_format == "yuv420p"
            and info.audio_codec in {None, "aac"}
        )
        if not compatible or source.suffix.lower() == ".mp4":
            return PreparedVideo(source, info, False, document=not compatible)
        output = source.parent / "VidFetch.mp4"
        await status("Preparing the original video without reducing quality…")
        check_disk(source.parent)
        await command(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-y",
                "-i",
                str(source),
                "-map",
                f"0:{info.video_index}",
                "-map",
                "0:a:0?",
                "-c",
                "copy",
                "-sn",
                "-dn",
                "-movflags",
                "+faststart",
                str(output),
            ],
            timeout=7200,
            folder=source.parent,
            download_guard=True,
        )
        final = await probe(output)
        if abs(final.duration - info.duration) > max(2, info.duration * 0.01) or (
            info.audio_codec and not final.audio_codec
        ):
            raise MediaError("The prepared video was incomplete. Try the original format again.")
        return PreparedVideo(output, final, False)
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
