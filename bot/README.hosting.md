# VidFetch on Botkeep or another persistent Linux host

Use Python 3.12, FFmpeg/ffprobe, and a source-built official Telegram Bot API server.
The native Android app remains independent. No public port or domain is needed.

The `vidfetch-botkeep-linux-x64` CI artifact contains a clean deployment ZIP with
Python sources, dependencies, and the pinned official Telegram API server built by
this repository. Its matching Linux loader/libraries let it run on older glibc
hosts without root access. Generated executables are CI artifacts, never Git files.
`manifest.json` records the source revision and every packaged file's SHA-256.

1. Create an Application / Python 3.12 server. Assign 1 GB RAM, 100% CPU and at least
   1 GB storage. Physical free capacity can differ from the account allowance.
2. Transfer and extract the ZIP into the server root. Botkeep's browser uploader has
   a 4 MB per-file limit; use SFTP for the complete ZIP, or upload smaller numbered
   parts and reassemble them with a checksum-verified installer. Keep a source copy
   outside the host.
3. Use startup command `pip install --no-cache-dir --pre -r requirements.txt && python -u main.py`.
4. In **Environment**, add `TELEGRAM_BOT_TOKEN`, `TELEGRAM_API_ID` and
   `TELEGRAM_API_HASH` as secrets. The entry point loads Botkeep's managed `.env`
   without logging its contents or prompting for input. Existing process variables
   take precedence. Do not upload credentials with the deployment ZIP.
5. Set `VIDFETCH_STORAGE_LIMIT_MB=1024` to match the actual allocated storage in MB.
   Optionally set `VIDFETCH_ALLOWED_USERS` to comma-separated numeric Telegram IDs.
6. Stop any previous instance before starting this one. Check Console for the bot
   link, then send `/start`, a public video URL, and select a quality in Telegram.

`python main.py --check` checks tools and free storage without contacting Telegram.
The local API data and temporary downloads stay under `.vidfetch/` on the server.
Normal shutdown stops both processes. Do not share `.env`, `.vidfetch/`, an SFTP
password, or server backups: these may contain authorization state.

This uses Telegram's local API and preserves original quality, including the
existing numbered-part delivery. The hosting disk allowance is usually the tighter
limit: the Python environment, native server and session data consume part of it,
and downloads/preparation need working space. A 256 MB reserve is enforced against
the allocation as well as the shared filesystem's free space. Large videos may
require more storage; a 1 GB plan cannot provide the notebook's multi-GB workspace.
Files are cleaned after each job, but queued jobs and menus do not survive restarts.

Cookies are optional and must be imported separately into a private directory;
set `VIDFETCH_COOKIE_DIR` and a nonempty `VIDFETCH_ALLOWED_USERS` before enabling
account cookies. See the main bot README for supported formats and site restrictions.

Free hosting availability and plan expiry are controlled by the provider. No
keepalive or account/resource-limit bypass is used.
