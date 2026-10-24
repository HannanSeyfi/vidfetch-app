"""Optional local entry point; Colab uses the same asynchronous run_bot function."""

import asyncio
import os
from pathlib import Path

from .app import run_bot
from .cookies import CookieStore
from .credentials import read_secret
from .local_api import LocalAPIError, local_bot_api
from .telegram import TelegramError


def main() -> None:
    token = read_secret("TELEGRAM_BOT_TOKEN", "Telegram bot token from @BotFather: ")
    try:
        users = {
            int(value.strip())
            for value in os.environ.get("VIDFETCH_ALLOWED_USERS", "").split(",")
            if value.strip()
        }
    except ValueError:
        raise SystemExit(
            "VIDFETCH_ALLOWED_USERS must contain comma-separated Telegram user IDs."
        ) from None
    cookie_directory = os.environ.get("VIDFETCH_COOKIE_DIR")
    cookies = CookieStore(Path(cookie_directory)) if cookie_directory else None
    if cookies and cookies.has_enabled() and not users:
        raise SystemExit("Set VIDFETCH_ALLOWED_USERS before enabling account cookies.")
    try:
        api_id = read_secret("TELEGRAM_API_ID", "Telegram api_id from my.telegram.org: ")
        api_hash = read_secret("TELEGRAM_API_HASH", "Telegram api_hash from my.telegram.org: ")

        async def start():
            binary = os.environ.get("VIDFETCH_API_BINARY")
            async with local_bot_api(
                token, api_id, api_hash, binary=Path(binary) if binary else None
            ) as api:
                await run_bot(token, allowed_users=users, api=api, cookie_store=cookies)

        asyncio.run(start())
    except KeyboardInterrupt:
        pass
    except (LocalAPIError, TelegramError) as error:
        print(str(error))


if __name__ == "__main__":
    main()
