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
        print("Setup complete. Run the next cell and enter your bot token in the hidden prompt.")
    """)
    setup = setup.replace("+ REQUIREMENTS", "+ " + repr(requirements))
    setup = setup.replace(
        "for name, source in SOURCES.items():", "for name, source in " + repr(sources) + ".items():"
    )
    start = textwrap.dedent("""\
        #@title 2. Start the Telegram bot
        # Optional: comma-separated numeric Telegram user IDs. Blank allows any private-chat user.
        allowed_user_ids = "" #@param {type:"string"}

        from getpass import getpass
        from vidfetch_bot.app import run_bot

        async def start_vidfetch():
            try:
                allowed = {int(value.strip()) for value in allowed_user_ids.split(",") if value.strip()}
            except ValueError:
                print("Use numeric user IDs separated by commas, or leave the field blank.")
                return
            # Hidden input is never written into notebook source or cell outputs.
            await run_bot(getpass("Bot token from @BotFather: ").strip(), allowed_users=allowed)

        await start_vidfetch()
    """)
    intro = textwrap.dedent("""\
        # VidFetch Telegram bot

        **Run both cells, enter your bot token, then send your bot a video link in Telegram.**

        1. Use a standard **CPU** runtime (no GPU required).
        2. Select **Runtime → Run all**. Setup can take a few minutes.
        3. Enter the token supplied by [@BotFather](https://t.me/BotFather) in the hidden prompt.
        4. Open the bot link printed below, send `/start`, then a video URL.
        5. Choose a quality: buttons include estimated video + audio size. Large files are
           automatically compressed below the Telegram upload limit.

        Keep the second cell running. Its stop button shuts the bot down; rerun it to restart.
        Colab sessions are temporary and subject to [Colab's limits and policies](https://research.google.com/colaboratory/faq.html).
        Interrupted downloads and old quality menus do not survive a runtime restart.

        Optional: restrict access with Telegram user IDs in cell 2 (use `/id` to find yours).
        Leave the field blank to accept private messages from anyone who finds your bot.
        Use `/cancel` to stop your request and `/status` to check it.

        Sizes are estimates. Compression can reduce resolution, frame rate, and detail.
        Some sites block Colab IP addresses or require sign-in. This notebook does not import cookies.
        Download only content you are permitted to download.

        [Source and documentation](https://github.com/HannanSeyfi/vidfetch-app/tree/codex/telegram-colab-bot/bot)
    """)
    return {
        "cells": [
            cell("markdown", intro, "instructions"),
            cell("code", setup, "setup"),
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
