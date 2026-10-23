"""Build the official Linux server and smoke-test startup without contacting a Telegram account."""

import asyncio
import subprocess
import tempfile
from pathlib import Path

import httpx

from vidfetch_bot.local_api import install_server, local_bot_api


async def main():
    binary = install_server()
    subprocess.run([str(binary), "--version"], check=True)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        # No real token and no cloud migration: probe only the local server's HTTP root.
        (root / "cloud-migrated").touch()
        async with local_bot_api(
            "123456:" + "x" * 35,
            "1",
            "0" * 32,
            binary=binary,
            directory=root,
        ) as api:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(api.api_root + "/")
                if response.status_code not in {400, 404}:
                    raise RuntimeError("Unexpected local Telegram HTTP response")
    print("Official server build, loopback startup, HTTP handling and shutdown passed.")


if __name__ == "__main__":
    asyncio.run(main())
