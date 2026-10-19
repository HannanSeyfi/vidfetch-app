# VidFetch Telegram bot for Colab

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/HannanSeyfi/vidfetch-app/blob/codex/telegram-colab-bot/bot/VidFetch_Telegram_Colab.ipynb)

Open the notebook, select **Runtime → Run all**, and enter the bot token from [@BotFather](https://t.me/BotFather) in the hidden prompt. Open the printed Telegram bot link, send `/start`, then send a video URL. No domain, public IP, Telegram API ID, API hash, Google Drive mount, or GPU is needed. Use a standard CPU runtime.

The notebook installs FFmpeg/ffprobe if necessary, current nightly yt-dlp with its EJS challenge components and curl_cffi networking, Deno, and the Telegram HTTP client. It embeds the Python package from this directory, so it also works when opened from a branch, fork, or downloaded notebook. The token is held in runtime memory and is never stored in notebook code, files, or printed output. Do not paste a token into a code cell or share a running runtime with someone you do not trust.

## Using the bot

1. Send a single public video link in a private chat with the bot.
2. Choose a resolution, for example `720p · ~38.2 MB`. Sizes include the selected audio stream when known. If the site supplies neither size nor bitrate, the button says `size unknown`.
3. A `compress` marker means the estimated download is above the upload budget. Download size and delivered size can differ.
4. The bot downloads the selected streams, merges them, verifies a real video stream with ffprobe, and prepares a playable MP4. Oversized or incompatible videos are encoded as H.264/AAC, with two-pass encoding and a byte budget. It verifies the actual final size before uploading. The caption reports the delivered resolution and whether the video was compressed.

Commands: `/start`, `/help`, `/status`, `/cancel`, and `/id`. Cancelling stops active download/encoding subprocesses and cleans temporary files. Menus belong to the user who requested them, expire after 30 minutes, and are invalidated after use or when that user requests another link.

The optional `allowed_user_ids` field in the second notebook cell accepts comma-separated numeric Telegram user IDs. Find your ID using `/id`, stop the cell, enter your ID, and restart. A blank field allows anyone who discovers the bot to use it in private chats. Groups are not supported.

## Limits and behavior

- The standard [Telegram Bot API](https://core.telegram.org/bots/api#sendvideo) allows new video uploads up to 50 MB. This bot uses a conservative **49,000,000-byte** ceiling and **46,000,000-byte** encoding target. Sending as a document does not increase the limit. No local Bot API server is required.
- Compression can lower resolution, frame rate, audio quality, and detail. It preserves the full clip and original audio when present. If a complete valid video cannot fit after bounded encoding attempts, the bot explains the failure rather than uploading an oversized or truncated file.
- One request runs at a time, with at most five active/queued requests and one per user. Downloads have a 2 GB budget; videos over four hours, playlists, and ongoing live streams are rejected. Extraction, downloading, and encoding have time limits. Temporary media is deleted after success, error, or cancellation.
- Site support comes from yt-dlp. Network location, IP reputation, authentication requirements, DRM, and site changes can cause different results from the Android app. The Android-specific Python compatibility runtime is not used here. No cookies are imported, and raw extractor logs are not sent to Telegram.
- Initial URLs must use HTTP(S), resolve to public IPs, and use standard web ports. This is a small personal bot, not a hardened public download service; extractor redirects and nested media requests are handled by yt-dlp.
- Colab is a temporary interactive environment. The bot stops when the runtime stops, and old quality menus and unfinished jobs are not persisted. Google [restricts media serving unrelated to interactive compute](https://research.google.com/colaboratory/faq.html#limitations-and-restrictions); a notebook does not create an exception to those policies. No keepalive or limit-bypass mechanism is included.
- Run only one copy of a bot token at a time. If another notebook or host is already polling that bot, stop it before restarting. Telegram may retain unreceived updates for up to 24 hours; stale quality buttons require resending the link.

The Android app remains independent, uses local on-device processing, and does not connect to this bot.

## Development and verification

Python 3.11+ and FFmpeg/ffprobe with `libx264` are required. From `bot/`, install dependencies and run:

```text
python -m pip install --upgrade --pre -r requirements.txt
python -m unittest discover -s tests -v
python tools/build_notebook.py --check
```

For a local run, use `python -m vidfetch_bot`; it prompts for the token without echoing it. Optional environment variables are `TELEGRAM_BOT_TOKEN` and `VIDFETCH_ALLOWED_USERS`. Keep credentials outside Git and do not put them in shell commands that save history.

Canonical sources live in `vidfetch_bot/`. After editing them or `requirements.txt`, run `python tools/build_notebook.py` to regenerate the notebook. CI checks that the embedded code matches, validates notebook syntax, tests Telegram conversations through a fake transport, and exercises actual yt-dlp/FFmpeg against synthetic local media. Tests do not require a bot token or third-party video site.
