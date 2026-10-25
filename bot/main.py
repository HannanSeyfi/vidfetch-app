"""Non-interactive entry point for persistent Linux hosts such as Botkeep."""

import argparse
import asyncio
import os
import re
import shutil
import signal
import tempfile
from pathlib import Path

from dotenv import load_dotenv

from vidfetch_bot import media
from vidfetch_bot.app import run_bot
from vidfetch_bot.cookies import CookieStore
from vidfetch_bot.local_api import LocalAPIError, local_bot_api
from vidfetch_bot.telegram import TelegramError

ROOT = Path(__file__).resolve().parent
REQUIRED = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_API_ID", "TELEGRAM_API_HASH")


def configuration():
    """Validate without echoing credential values or falling back to input prompts."""
    missing = [name for name in REQUIRED if not os.environ.get(name, "").strip()]
    if missing:
        raise ValueError("Set these secrets in Environment: " + ", ".join(missing))
    token, api_id, api_hash = (os.environ[name].strip() for name in REQUIRED)
    if not re.fullmatch(r"\d{5,20}:[A-Za-z0-9_-]{20,}", token):
        raise ValueError("TELEGRAM_BOT_TOKEN is invalid.")
    if not api_id.isdecimal() or int(api_id) <= 0:
        raise ValueError("TELEGRAM_API_ID must be a positive number.")
    if not re.fullmatch(r"[a-fA-F0-9]{32}", api_hash):
        raise ValueError("TELEGRAM_API_HASH must contain 32 hexadecimal characters.")
    entries = [value.strip() for value in os.environ.get("VIDFETCH_ALLOWED_USERS", "").split(",")]
    if any(value and (not value.isdecimal() or int(value) <= 0) for value in entries):
        raise ValueError("VIDFETCH_ALLOWED_USERS must contain comma-separated positive user IDs.")
    return token, api_id, api_hash, {int(value) for value in entries if value}


async def serve(binary: Path, state: Path):
    token, api_id, api_hash, users = configuration()
    cookie_directory = os.environ.get("VIDFETCH_COOKIE_DIR")
    cookies = CookieStore(Path(cookie_directory)) if cookie_directory else None
    if cookies and cookies.has_enabled() and not users:
        raise ValueError("Set VIDFETCH_ALLOWED_USERS before enabling account cookies.")
    loop = asyncio.get_running_loop()
    task = asyncio.current_task()
    for name in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(name, task.cancel)
    try:
        async with local_bot_api(
            token, api_id, api_hash, binary=binary,
            directory=state / "telegram-api" / token.split(":", 1)[0],
        ) as api:
            await run_bot(token, allowed_users=users, api=api, cookie_store=cookies)
    finally:
        for name in (signal.SIGTERM, signal.SIGINT):
            loop.remove_signal_handler(name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check installation without contacting Telegram")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env", override=False, interpolate=False)
    os.umask(0o077)
    binary = Path(os.environ.get("VIDFETCH_API_BINARY", ROOT / "vendor" / "telegram-bot-api"))
    missing = [tool for tool in ("ffmpeg", "ffprobe") if not shutil.which(tool)]
    if missing or not binary.is_file():
        print("Missing runtime tools: " + ", ".join(missing + ([] if binary.is_file() else ["telegram-bot-api"])))
        return 1
    # ZIP extractors do not all retain Unix executable permissions.
    for path in (binary, ROOT / "vendor/bin/telegram-bot-api", ROOT / "vendor/lib/ld-linux-x86-64.so.2"):
        if path.is_file():
            path.chmod(0o700)
    state = ROOT / ".vidfetch"
    state.mkdir(exist_ok=True, mode=0o700)
    temporary = state / "tmp"
    temporary.mkdir(exist_ok=True, mode=0o700)
    tempfile.tempdir = str(temporary)
    try:
        limit = int(os.environ.get("VIDFETCH_STORAGE_LIMIT_MB", "1024"))
        if limit <= 0:
            raise ValueError
    except ValueError:
        print("VIDFETCH_STORAGE_LIMIT_MB must be a positive integer matching the host allocation.")
        return 1
    media.STORAGE_BUDGET = media.StorageBudget(ROOT, limit * 1_000_000)
    try:
        media.check_disk(ROOT)
        if args.check:
            print("Runtime tools and storage checks passed. No Telegram connection was made.")
            return 0
        configuration()
        asyncio.run(serve(binary, state))
    except (ValueError, LocalAPIError, TelegramError, media.MediaError) as error:
        print(str(error))
        return 1
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
