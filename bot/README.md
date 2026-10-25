# VidFetch Telegram bot

For a persistent Linux deployment, see [the Botkeep/hosting guide](README.hosting.md).

The hosted entry point is private: the owner approves users with `/allow ID`,
removes them with `/deny ID`, and lists them with `/users`. Each approved user can
manage their own YouTube/Reddit cookie exports through `/cookies`. Personal cookie
stores are isolated by Telegram user ID and are never used for another user's
downloads. Owner configuration, persistence and cookie handling are documented in
the hosting guide. The Colab workflow below retains its separate shared-cookie mode.

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/HannanSeyfi/vidfetch-app/blob/main/bot/VidFetch_Telegram_Colab.ipynb)

VidFetch downloads video and audio in Colab and delivers the selected quality through Telegram. The notebook runs both the Python bot and Telegram's official Bot API server on the **Colab machine**, using its internet connection. No home server, public IP, domain, tunnel, Google Drive mount, or GPU is needed.

## Start or update the notebook

1. Obtain the bot token from [@BotFather](https://t.me/BotFather).
2. Obtain your own Telegram **api_id** and **api_hash** at [my.telegram.org/apps](https://my.telegram.org/apps). Sign in and create an API application if needed. These application credentials are separate from the bot token.
3. Stop the old bot cell and any other copy of the same bot. Open the latest notebook from GitHub, choose a standard **CPU** runtime, and select **Runtime → Run all**.
4. Enter all three credentials in the hidden prompts. Alternatively, create Colab Secrets named `TELEGRAM_BOT_TOKEN`, `TELEGRAM_API_ID`, and `TELEGRAM_API_HASH` and grant this notebook access. Never paste credentials into code cells.
5. Open the printed bot link, send `/start`, and send a public video URL.

The first setup compiles pinned official [telegram-bot-api](https://github.com/tdlib/telegram-bot-api) sources and can take **15 minutes or longer**. It reuses a completed build in the same runtime. The server listens only on `127.0.0.1` at a dynamically allocated port, with `--local` enabled. No third-party API gateway or prebuilt server binary is used.

The first start deregisters this bot from `api.telegram.org` with `logOut`, then routes **all** bot requests to the local server. Telegram prevents returning to the hosted API for ten minutes after that migration. Stopping and rerunning the bot cell reuses the runtime's server data and migration marker. Run only one instance of a bot at a time. If changing to another machine, stop the old instance first; use Telegram's [local-server migration procedure](https://github.com/tdlib/telegram-bot-api#moving-a-bot-from-one-local-server-to-another) when preserving pending updates matters.

Saved Colab copies contain their old embedded Python sources. **Reopen the latest GitHub notebook and rerun all cells** to update; restarting only an old start cell cannot install this change.

Hidden prompts and Secrets keep credentials out of notebook source and outputs. The local server maintains authorization state in the temporary runtime filesystem, so do not share its data directory or a live runtime with someone you do not trust. The directory disappears when Colab deletes the runtime.

## Optional YouTube and Reddit cookies

1. Start once with cookies disabled and send `/id` to learn your Telegram user ID, then stop the bot.
2. Reopen the latest notebook from **main** and run setup. In **cell 2**, choose **Import / replace** for YouTube or Reddit and upload one Netscape-format export for that site. Files stay in the temporary runtime, outside notebook source and media output.
3. For Reddit use a fresh signed-in Chrome export. For YouTube follow [yt-dlp's official export instructions](https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies): use a new private/incognito login, visit youtube.com/robots.txt in the same tab, export youtube.com cookies and close that private window.
4. Enter your numeric Telegram ID in `allowed_user_ids` in **cell 3** and start. Enabled account cookies require a nonempty allowlist. All listed users can request content accessible to these accounts; list only trusted people. No cookies are accepted through Telegram messages.
5. `/cookies` reports site status and common sign-in cookie presence, without cookie values. To replace, enable, disable or delete cookies, stop the bot, rerun cell 2 with the desired action, then restart cell 3 and send the URL again.

Imports are limited to 2 MB, validated, filtered to the selected site's domains and stripped of expired entries. Each extraction uses a private temporary snapshot, deleted on completion, failure or cancellation. Reddit short links select the reddit.com jar; YouTube aliases select youtube.com. Normal cookie domain rules still apply to redirects and media requests. Sign-in cookie presence is a local check, not proof of a valid session. Cookie files expire with the Colab runtime and must be reimported after a runtime reset. Never commit exports, paste their contents into notebook cells or share an active runtime.

On another host, set `VIDFETCH_COOKIE_DIR` to a dedicated private directory containing `youtube.com.cookies` and/or `reddit.com.cookies`, using validated Netscape exports, and set `VIDFETCH_ALLOWED_USERS`. Alternatively import with `CookieStore.import_file(site, path)` before starting. The runtime revalidates snapshots and never enables a public bot with account cookies.

Cookies authenticate a session; they do not guarantee access from Colab. Session/fingerprint/network restrictions can affect Reddit and YouTube even when the browser or Android app works. Update the extractor, replace rejected sessions and compare the same public post on the actual bot host. If that host's network is rejected, use a host/connection where the same test succeeds. YouTube PO-token errors require a separate compatible provider setup; cookie import does not generate PO tokens.

## Quality and large files

Choose a resolution or **Audio only**. Buttons show estimated sizes; video estimates include audio where known. Unknown sizes are labelled explicitly. Delivered captions include the title, actual size, and a clickable source URL.

- **No automatic 50 MB compression in the notebook.** Compatible H.264/AAC MP4 video is sent inline without lowering resolution, frame rate, or bitrate. Compatible streams from another container are remuxed without re-encoding. Other video codecs are delivered as original-quality documents.
- **Audio only preserves the audio codec.** AAC is extracted as M4A and MP3 as MP3 for Telegram's music player. Other codecs, such as Opus, are extracted losslessly into an MKA document instead of being converted to AAC. No video stream is retained.
- Telegram's [local Bot API supports up to 2,000 MB per file](https://core.telegram.org/bots/api#using-a-local-bot-api-server). VidFetch uses a conservative **1,950,000,000-byte** ceiling. The notebook never silently falls back to the hosted API's 50 MB limit if its local server fails.
- Files above that ceiling are automatically sent as **numbered byte-exact file parts**, followed by a small Python joiner. A `split into files` marker indicates this in menus when the estimate is known. **These parts do not play separately.** Download every part and the joiner into one folder on a device with Python 3, then run the joiner, for example `python join-VidFetch-12345678.mp4.py`. It restores the original file only after its total size and SHA-256 match. It needs enough free space for the restored file as well as the downloaded parts. Unique names keep separate requests from mixing together.
- There is no fixed total-download byte ceiling or four-hour duration rejection. Available disk space, site availability, network timeouts, and Colab runtime lifetime still apply. Downloads stop before exhausting the session's free disk space; individual downloads and lossless preparation have two-hour operation timeouts. Upload requests allow up to one hour per file.

Cancellation or interrupted delivery can leave already-sent Telegram messages in the chat. A complete multi-part delivery ends with its joiner and a completion status; an incomplete set cannot be restored by the joiner. Send the link again to restart an interrupted job.

## Commands and access

Commands: `/start`, `/help`, `/status`, `/cancel`, `/id`, and `/cookies`. Cancellation stops active download/preparation subprocesses and cleans job files. Temporary media is removed after success, error, or cancellation; only one part is staged at a time while sending a large file.

Menus belong to the requesting user, expire after 30 minutes, and are invalidated after use or when the user requests another link. One request runs at a time, with at most five active/queued requests and one per user. The optional `allowed_user_ids` field accepts comma-separated numeric Telegram IDs. Find yours with `/id`, stop the cell, set the field, and restart. A blank field allows anyone who discovers the bot to use it in private chats. Groups are not supported.

The [bot profile picture](assets/vidfetch-bot-avatar.png) and its [generation prompt](assets/avatar-prompt.md) are included.

## Other limits

Site support comes from yt-dlp, with its EJS components, curl_cffi networking and Deno. Authentication requirements, DRM, IP reputation and site changes can prevent a download. Optional cookies are supported as described below; raw extractor logs are not sent to Telegram. A bundled yt-dlp plugin can extract the requested post's native HLS/DASH player from its accessible public HTML page when the JSON endpoint is rejected; it excludes related posts and comment GIFs and preserves private-community/rate-limit errors. Reddit uses Chrome impersonation followed by one default-profile retry only for eligible session/403 failures. Rate limits and private-community access errors are not retried. Playlists and ongoing live streams are not supported. Initial links must use HTTP(S), resolve to public IPs and use standard web ports. Extractor redirects and nested media requests are handled by yt-dlp; this is a small personal bot rather than a hardened public download service.

Colab is a temporary interactive environment: its runtime shutdown stops both programs. Google [restricts media serving unrelated to interactive compute](https://research.google.com/colaboratory/faq.html#limitations-and-restrictions); adding a local Telegram server does not create an exception. Use a persistent host for continuous operation. There is no keepalive or Colab-limit bypass mechanism. Unfinished jobs and old menus do not persist across runtime restarts.

The native Android app remains independent and processes downloads on-device without connecting to this bot.

## Development and verification

Python 3.11+ and FFmpeg/ffprobe are required. From `bot/`:

```text
python -m pip install --upgrade --pre -r requirements.txt
python -m pip install ruff nbformat
python -m unittest discover -s tests -v
ruff check vidfetch_bot tests tools
python tools/build_notebook.py --check
```

To run on another host, install Telegram's official Bot API server and use `python -m vidfetch_bot`. It prompts for the same three credentials; optional environment variables are `TELEGRAM_BOT_TOKEN`, `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `VIDFETCH_API_BINARY`, and `VIDFETCH_ALLOWED_USERS`. Keep credentials outside Git and shell history.

Canonical sources live in `vidfetch_bot/`. After edits, regenerate the self-contained notebook with `python tools/build_notebook.py`. The lower-level Python client still supports explicit hosted-API use for compatibility, including its old compression behavior; both user-facing entry points use the local server and preserve quality.

CI validates notebook schema/bootstrap, source parity, conversations, both HTTP transports, cancellation, byte-exact splitting and reconstruction, original media packet preservation, and synthetic yt-dlp/FFmpeg downloads. A separate Linux job builds the pinned official server and checks loopback HTTP startup and shutdown without contacting a Telegram account. Tests do not need a real bot token. Live delivery still requires the user's credentials and a running session.
