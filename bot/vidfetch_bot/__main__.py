"""Optional local entry point; Colab uses the same asynchronous run_bot function."""

import asyncio
import os
from pathlib import Path

from .app import run_bot
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
    try:
        api_id = read_secret("TELEGRAM_API_ID", "Telegram api_id from my.telegram.org: ")
        api_hash = read_secret("TELEGRAM_API_HASH", "Telegram api_hash from my.telegram.org: ")

        async def start():
            binary = os.environ.get("VIDFETCH_API_BINARY")
            async with local_bot_api(
                token, api_id, api_hash, binary=Path(binary) if binary else None
            ) as api:
                await run_bot(token, allowed_users=users, api=api)

        asyncio.run(start())
    except KeyboardInterrupt:
        pass
    except (LocalAPIError, TelegramError) as error:
        print(str(error))


if __name__ == "__main__":
    main()
