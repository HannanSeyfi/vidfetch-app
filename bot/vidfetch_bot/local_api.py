"""Install and supervise Telegram's official Bot API server on the bot's own machine."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path

from .telegram import Telegram, TelegramError

API_REVISION = "e3e9dd8e5b3d7ab8537cd5a10dc31d5ffa8f82d1"


class LocalAPIError(Exception):
    """A credential-free error suitable for notebook output."""


def install_server(cache: Path | None = None) -> Path:
    """Build pinned official sources once per Colab runtime; never download third-party binaries."""
    root = (cache or Path.home() / ".cache" / "vidfetch-bot-api") / API_REVISION
    binary = root / "install" / "bin" / "telegram-bot-api"
    if binary.is_file():
        return binary
    if not sys.platform.startswith("linux"):
        raise LocalAPIError("Automatic server installation requires Linux (including Colab).")
    root.mkdir(parents=True, exist_ok=True)
    source = root / "source"
    apt = ([] if getattr(os, "geteuid", lambda: 0)() == 0 else ["sudo"]) + ["apt-get"]
    steps = [
        apt + ["update", "-qq"],
        [
            *apt,
            "install",
            "-y",
            "-qq",
            "git",
            "cmake",
            "clang",
            "make",
            "gperf",
            "libssl-dev",
            "zlib1g-dev",
        ],
    ]
    if not (source / ".git").is_dir():
        steps.append(
            [
                "git",
                "clone",
                "--no-checkout",
                "https://github.com/tdlib/telegram-bot-api.git",
                str(source),
            ]
        )
    steps.extend(
        [
            ["git", "-C", str(source), "checkout", "--detach", API_REVISION],
            [
                "git",
                "-C",
                str(source),
                "submodule",
                "update",
                "--init",
                "--recursive",
                "--depth",
                "1",
            ],
            [
                "cmake",
                "-S",
                str(source),
                "-B",
                str(root / "build"),
                "-DCMAKE_BUILD_TYPE=Release",
                "-DCMAKE_C_COMPILER=clang",
                "-DCMAKE_CXX_COMPILER=clang++",
                f"-DCMAKE_INSTALL_PREFIX={root / 'install'}",
            ],
            ["cmake", "--build", str(root / "build"), "--target", "install", "--parallel", "2"],
        ]
    )
    print("Installing Telegram's official API server. The first build can take several minutes.")
    for args in steps:
        subprocess.run(args, check=True)
    if not binary.is_file():
        raise LocalAPIError("The Telegram API server build did not produce an executable.")
    return binary


async def wait_for_server(process, port: int, *, timeout: float = 90) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.returncode is not None:
            raise LocalAPIError("The local Telegram API server stopped during startup.")
        try:
            _, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.close()
            await writer.wait_closed()
            return
        except OSError:
            await asyncio.sleep(0.25)
    raise LocalAPIError("The local Telegram API server did not become ready. Restart the bot cell.")


async def stop_server(process) -> None:
    if process.returncode is None:
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), 20)
        except TimeoutError:
            process.kill()
            await process.wait()


async def migrate_from_cloud(token: str) -> None:
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    cloud = Telegram(token)
    try:
        await cloud.call("logOut")
    except TelegramError as error:
        # A fresh Colab runtime may start during the cloud's ten-minute login cooldown.
        # Local login is allowed immediately after logout; do not fall back to cloud uploads.
        if error.code != 429 or not 0 < error.retry_after <= 600:
            raise
    finally:
        await cloud.close()


@asynccontextmanager
async def local_bot_api(
    token: str,
    api_id: str,
    api_hash: str,
    *,
    binary: Path | None = None,
    directory: Path | None = None,
):
    if not re.fullmatch(r"\d{5,20}:[A-Za-z0-9_-]{20,}", token):
        raise LocalAPIError("Enter the complete bot token from @BotFather.")
    if not api_id.isdecimal() or int(api_id) <= 0 or not re.fullmatch(r"[a-fA-F0-9]{32}", api_hash):
        raise LocalAPIError(
            "Enter the numeric api_id and 32-character api_hash from my.telegram.org."
        )
    executable = str(binary or shutil.which("telegram-bot-api") or "")
    if not executable or not Path(executable).is_file():
        raise LocalAPIError("The Telegram API server is missing. Run the setup cell first.")
    # This directory survives stopping/rerunning a cell, but not deleting the Colab runtime.
    root = directory or Path(tempfile.gettempdir()) / "vidfetch-telegram-api" / token.split(":")[0]
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    environment = {**os.environ, "TELEGRAM_API_ID": api_id, "TELEGRAM_API_HASH": api_hash}
    process = None
    api = None
    try:
        process = await asyncio.create_subprocess_exec(
            executable,
            "--local",
            "--http-ip-address=127.0.0.1",
            f"--http-port={port}",
            f"--dir={root}",
            "--verbosity=0",
            env=environment,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await wait_for_server(process, port)
        # One migration per server data directory. Do not log out a cloud session on every cell rerun.
        migrated = root / "cloud-migrated"
        if not migrated.exists():
            await migrate_from_cloud(token)
            migrated.touch(mode=0o600)
        api = Telegram(token, api_root=f"http://127.0.0.1:{port}", local_files=True)
        api.server_process = process
        yield api
    except OSError:
        raise LocalAPIError(
            "Could not start the local Telegram API server. Run setup again."
        ) from None
    finally:
        if api is not None:
            await api.close()
        if process is not None:
            await stop_server(process)
