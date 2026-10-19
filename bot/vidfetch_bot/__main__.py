"""Optional local entry point; Colab uses the same asynchronous run_bot function."""

import asyncio
import os
from getpass import getpass

from .app import run_bot


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or getpass("Telegram bot token from @BotFather: ")
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
        asyncio.run(run_bot(token, allowed_users=users))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
