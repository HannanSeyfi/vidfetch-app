"""Generate a self-contained notebook from the reviewed Python sources (no Git ref dependency)."""

import argparse
import json
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "VidFetch_Telegram_Colab.ipynb"


def cell(kind: str, source: str, identifier: str) -> dict:
    result = {
        "cell_type": kind,
        "id": identifier,
        "metadata": {"id": identifier},
        "source": source.splitlines(keepends=True),
    }
    if kind == "code":
        result.update(execution_count=None, outputs=[])
    return result


def notebook() -> dict:
    sources = {
        f"vidfetch_bot/{path.name}": path.read_text(encoding="utf-8")
        for path in sorted((ROOT / "vidfetch_bot").glob("*.py"))
    }
    requirements = [
        line
        for line in (ROOT / "requirements.txt").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    setup = textwrap.dedent("""\
        #@title 1. Install tools and load VidFetch
        import importlib
        import os
        from pathlib import Path
        import shutil
        import subprocess
        import sys
        import sysconfig
        import tempfile

        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            subprocess.run(["apt-get", "update", "-qq"], check=True)
            subprocess.run(["apt-get", "install", "-y", "-qq", "ffmpeg"], check=True)
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--upgrade", "--pre"]
                       + REQUIREMENTS, check=True)
        os.environ["PATH"] = sysconfig.get_path("scripts") + os.pathsep + os.environ["PATH"]
        encoders = subprocess.check_output(["ffmpeg", "-hide_banner", "-encoders"], text=True)
        if "libx264" not in encoders:
            raise RuntimeError("This FFmpeg installation has no H.264 encoder (libx264).")
        import deno
        subprocess.run([deno.find_deno_bin(), "--version"], check=True)
        # The notebook contains the same package as bot/vidfetch_bot in GitHub.
        # Embedded sources make Open in Colab work from a branch, fork, or downloaded copy.
        vidfetch_source_dir = Path(tempfile.mkdtemp(prefix="vidfetch-code-"))
        for name, source in SOURCES.items():
            destination = vidfetch_source_dir / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(source, encoding="utf-8")
        sys.path.insert(0, str(vidfetch_source_dir))
        # Rerunning setup must load this notebook's version, not a cached older package.
        for name in list(sys.modules):
            if name == "vidfetch_bot" or name.startswith("vidfetch_bot."):
                del sys.modules[name]
        importlib.invalidate_caches()
        from vidfetch_bot.local_api import install_server
        from vidfetch_bot.cookies import CookieStore
        if "vidfetch_cookie_dir" not in globals():
            vidfetch_cookie_dir = Path(tempfile.mkdtemp(prefix="vidfetch-cookies-"))
        vidfetch_cookies = CookieStore(vidfetch_cookie_dir)
        vidfetch_api_binary = install_server()
        print("Setup complete. Configure optional site cookies, then start the bot.")
    """)
    setup = setup.replace("+ REQUIREMENTS", "+ " + repr(requirements))
    setup = setup.replace(
        "for name, source in SOURCES.items():", "for name, source in " + repr(sources) + ".items():"
    )
    start = textwrap.dedent("""\
        #@title 3. Start the Telegram bot
        # Optional: comma-separated numeric Telegram user IDs. Blank allows any private-chat user.
        allowed_user_ids = "" #@param {type:"string"}

        from vidfetch_bot.app import run_bot
        from vidfetch_bot.credentials import read_secret
        from vidfetch_bot.local_api import LocalAPIError, local_bot_api
        from vidfetch_bot.telegram import TelegramError

        async def start_vidfetch():
            try:
                allowed = {int(value.strip()) for value in allowed_user_ids.split(",") if value.strip()}
            except ValueError:
                print("Use numeric user IDs separated by commas, or leave the field blank.")
                return
            if vidfetch_cookies.has_enabled() and not allowed:
                print("Enter your Telegram user ID in allowed_user_ids before enabling cookies. To find it, disable cookies, start the bot and send /id.")
                return
            # Colab Secrets or hidden inputs keep credentials out of source and outputs.
            token = read_secret("TELEGRAM_BOT_TOKEN", "Bot token from @BotFather: ")
            api_id = read_secret("TELEGRAM_API_ID", "Telegram api_id from my.telegram.org: ")
            api_hash = read_secret("TELEGRAM_API_HASH", "Telegram api_hash from my.telegram.org: ")
            try:
                async with local_bot_api(
                    token, api_id, api_hash, binary=vidfetch_api_binary
                ) as api:
                    await run_bot(token, allowed_users=allowed, api=api, cookie_store=vidfetch_cookies)
            except (LocalAPIError, TelegramError) as error:
                print(str(error))

        await start_vidfetch()
    """)
    cookie_setup = textwrap.dedent("""\
        #@title 2. Optional YouTube and Reddit cookies
        # Stop the running bot before changing cookies. Cookie files stay in this temporary runtime.
        youtube_cookies = "Keep" #@param ["Keep", "Import / replace", "Enable", "Disable", "Delete"]
        reddit_cookies = "Keep" #@param ["Keep", "Import / replace", "Enable", "Disable", "Delete"]
        from vidfetch_bot.colab_cookies import configure_cookies
        configure_cookies(vidfetch_cookies, {
            "youtube.com": youtube_cookies,
            "reddit.com": reddit_cookies,
        })
    """)
    intro = textwrap.dedent("""\
        # VidFetch Telegram bot

        **Original-quality video and audio, with large-file support. Everything runs in Colab.**

        1. Use a standard **CPU** runtime (no GPU required).
        2. Obtain your bot token from [@BotFather](https://t.me/BotFather), plus your own
           **api_id** and **api_hash** from [my.telegram.org/apps](https://my.telegram.org/apps).
           These are Telegram application credentials, separate from your bot token.
        3. Stop any older copy of this bot. Select **Runtime → Run all** and enter the
           three credentials in the hidden prompts. The first setup builds Telegram's official
           server and can take 15 minutes or longer; rerunning setup reuses the completed build.
        4. Open the bot link printed below, send `/start`, then a video URL.
        5. Choose a quality: buttons include estimated video + audio size.
           Files are **not compressed to 50 MB**. Compatible videos play inline; other formats
           arrive as original-quality documents. **Audio only** preserves the original audio codec.

        Two requests run at once, with up to five per user and 20 total running or queued.
        Every request has its own progress and Cancel button; `/status` lists all of yours.
        `/cancel` offers individual choices when several requests are active; `/cancel all` stops all of yours.

        For inline downloads, enable `/setinline` for your bot in BotFather. Optionally set
        `/setinlinefeedback` to `100%` for automatic analysis after selecting a result.
        Send `/start` privately once, then type `@your_bot URL` in a destination chat and
        select the download result. Tap **Show qualities** if needed, then choose video quality
        or Audio only. The result shows progress and becomes the media. Oversized file parts
        and their joiner are delivered to your private bot chat.

        Telegram allows up to **2,000 MB per file** with this server. Files exceeding our
        conservative 1,950 MB ceiling are sent as numbered parts plus a Python joiner.
        Download all parts and the joiner into one folder and run the joiner with Python 3.
        It verifies the original size and SHA-256; parts do not play separately.

        Optionally add `TELEGRAM_BOT_TOKEN`, `TELEGRAM_API_ID`, and `TELEGRAM_API_HASH`
        in Colab's **Secrets** panel and grant this notebook access to avoid retyping them.
        Do not paste credentials into code cells. The API server runs only on Colab's loopback
        interface; no public URL, tunnel, home computer server, or GPU is needed.

        Keep the start cell running. Its stop button shuts the bot down; rerun it to restart.
        Colab sessions are temporary and subject to [Colab's limits and policies](https://research.google.com/colaboratory/faq.html).
        Interrupted downloads and old quality menus do not survive a runtime restart.
        To update an older copy, stop its bot cell, reopen the latest GitHub notebook,
        and run all cells again. Rerunning only the start cell does not update the embedded code.

        Optional: import Netscape-format cookies in cell 2 using **Import / replace** for each site.
        Export only `youtube.com` or `reddit.com` cookies, never paste their contents into a cell.
        For Reddit, try a fresh signed-in Chrome export. For YouTube, follow the
        [official export instructions](https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies).
        Files are scoped to that site, checked for expiration and stored privately in this runtime.
        `/cookies` shows status without cookie values. Stop the bot and rerun cell 2 to replace,
        enable, disable or delete cookies; then restart cell 3 and send the link again.

        Restrict access with Telegram user IDs in cell 3 (use `/id` to find yours).
        **An explicit allowlist is required when account cookies are enabled.** Every allowed user
        can request content accessible to the imported accounts; list only people you trust.
        Leave the field blank to accept private messages from anyone who finds your bot.
        Use `/cancel` to stop your request and `/status` to check it.

        Sizes are estimates. Available disk space, network timeouts and runtime lifetime still apply.
        Downloads and Telegram uploads use Colab's connection, not your home upload bandwidth.
        Reddit uses Chrome impersonation and can read the requested post's own video player from an accessible public page if the JSON endpoint is rejected. Websites can still reject a
        session or Colab's connection even with fresh cookies; cookies cannot guarantee access.
        Download only content you are permitted to download.

        [Source and documentation](https://github.com/HannanSeyfi/vidfetch-app/tree/main/bot)
    """)
    return {
        "cells": [
            cell("markdown", intro, "instructions"),
            cell("code", setup, "setup"),
            cell("code", cookie_setup, "cookies"),
            cell("code", start, "start"),
        ],
        "metadata": {
            "colab": {"name": OUTPUT.name, "provenance": [], "toc_visible": False},
            "kernelspec": {"display_name": "Python 3", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    content = json.dumps(notebook(), ensure_ascii=False, indent=2) + "\n"
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != content:
            raise SystemExit("Notebook is out of date. Run: python tools/build_notebook.py")
        print("Notebook matches its Python sources and dependencies.")
    else:
        OUTPUT.write_text(content, encoding="utf-8")
        print(f"Generated {OUTPUT.name}")
