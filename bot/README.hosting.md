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
   Set **`VIDFETCH_ADMIN_USERS`** to your numeric Telegram user ID (send `/id` to
   learn it). Multiple trusted owners can be separated by commas. Startup refuses
   to run without an explicit owner. Owners are always allowed.
   `VIDFETCH_ALLOWED_USERS` optionally seeds the initial approved user list **once**;
   later changes are managed through owner commands and persist across restarts.
6. Stop any previous instance before starting this one. Check Console for the bot
   link, then send `/start`, a public video URL, and select a quality in Telegram.

`python main.py --check` checks tools and free storage without contacting Telegram.
The local API data and temporary downloads stay under `.vidfetch/` on the server.
Normal shutdown stops both processes. To replace credentials later, edit the secret
values in Environment and restart. A different bot ID gets its own authorization
directory and hosted-API migration marker; rotating a token for the same bot keeps
its existing session directory. Do not share `.env`, `.vidfetch/`, an SFTP
password, or server backups: these may contain authorization state.

This uses Telegram's local API and preserves original quality, including the
existing numbered-part delivery. The hosting disk allowance is usually the tighter
limit: the Python environment, native server and session data consume part of it,
and downloads/preparation need working space. A 256 MB reserve is enforced against
the allocation as well as the shared filesystem's free space. Large videos may
require more storage; a 1 GB plan cannot provide the notebook's multi-GB workspace.
Files are cleaned after each job, but queued jobs and menus do not survive restarts.

## Approve and remove users

The hosted bot is private, including when the approved user list is empty. Only
owners and approved users can download media or manage cookies. Anyone can use
`/id` to find their own numeric ID and ask the owner for approval; it grants no access.

Send these commands to the bot from an owner account:

- `/allow 123456789` approves a user. Multiple IDs can be separated by spaces or commas.
- `/deny 123456789` removes approval, cancels their active/queued requests,
  invalidates their menus and removes their stored cookie exports from this host.
- `/users` lists owners and approved IDs. Only owners can use these commands.
- `/sharecookies 123456789` lets an **already approved** user use the issuing
  owner's entire cookie set, including future imports. They do not need to import
  anything. `/sharecookies 123456789 example.com` grants just that website.
- `/unsharecookies 123456789` removes all cookie sharing for that user without
  removing bot access. Add a domain to remove sharing just for that site, including
  an exception to a whole-set grant. `/deny` removes both access and sharing.

Blocked users are directed to **@sorrow_climax** for approval, with `/id` available
to find their own numeric ID.

Approvals and cookie-sharing grants are saved atomically in `.vidfetch/users/<bot-id>/access.json`; a corrupt
access file stops startup instead of opening public access. At most 200 users can
be approved on this small personal bot. Owners cannot be removed through `/deny`;
change `VIDFETCH_ADMIN_USERS` in Environment and restart to change ownership.

## Each user's personal cookies

An approved user sends **`/cookies example.com`** in a private chat, then sends
their own Netscape-format export as a document within ten minutes. Alternatively,
send `/cookies`, choose **Add another site**, enter the domain and upload the file.
YouTube and Reddit retain their convenient buttons and short-link aliases.

Each export is limited to 2 MB, filtered to the selected domain and its subdomains,
and stripped of expired entries. Domain input accepts international names, while
IP addresses, public suffixes such as `com`/`co.uk`, URL credentials and paths are
rejected. Use the account's parent domain (such as `example.com`) if the export
contains parent-domain cookies. The bundled Public Suffix List is used offline.
The uploaded filename never selects a server path. Invalid exports do not replace
a working import. A user can keep up to 25 site exports; menus are paginated.

The same menu shows status and offers enable, disable and confirmed deletion for
each site. Removing a site's export removes it from the user's custom-site list.
`/cancel` cancels a pending domain prompt or file import. Cookie controls and quality menus
belong to the requesting user and expire; forwarded or altered callbacks cannot
manage another user's exports. Each extraction gets a temporary private snapshot.

Personal files live under `.vidfetch/users/<bot-id>/cookies/<user-id>/` with private
directory/file permissions. The most-specific matching saved domain is selected.
An empty personal store uses no account cookies. Other users' cookies are used
**only after an explicit owner grant**; recipients cannot read, replace or delete
the owner's exports through their cookie menus.

For a per-site grant, owner cookies override the recipient's personal cookies for
that domain. Missing, disabled, expired or invalid owner exports produce an error
instead of switching to a different account. In entire-set mode, sites with no
owner export use guest access; personal exports are not silently substituted.
The cookie menu displays the effective source. Sharing changes cancel existing
recipient jobs and invalidate their menus. Replacing, disabling or deleting an
owner export also cancels dependent requests. No cookie values or files are sent
to recipients. Existing approvals and exports survive the access-file migration.
`VIDFETCH_COOKIE_DIR` is not used by this hosted entry point. Existing shared
exports are not automatically assigned or copied to any user; reimport through
the personal menu. Colab's separate, explicitly allowlisted shared-cookie mode
continues to work as described in the main bot README.

Cookies authorize whatever content the signed-in account can access through the
downloader. Share them only with trusted approved users. A custom cookie domain
does not add a new yt-dlp extractor or guarantee that the site's authentication,
network restrictions or media formats will work.

Cookie files contain signed-in account sessions. Uploads pass through Telegram and
are stored on this bot's host; server administrators and the hosting provider can
access server files. The bot does not send cookie values to other users or owners.
Its local Bot API download cache copy is removed after reading an accepted import;
the upload message remains in Telegram until its sender removes it. Deleting an
import or denying access removes the bot's saved exports, not Telegram's copies
or independent server backups. Only upload sessions belonging to you. See the main
bot README for export instructions, session expiry and site/network restrictions.

Free hosting availability and plan expiry are controlled by the provider. No
keepalive or account/resource-limit bypass is used.
