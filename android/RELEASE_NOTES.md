VidFetch 0.3.8 improves Reddit extraction and site cookie handling.

- Updates bundled yt-dlp to official nightly 2026.10.23.233055, verified by SHA-256.
- Uses reddit.com cookies for Reddit short links and media aliases before redirects, while preserving cookie domain isolation.
- Tries Reddit with Chrome impersonation on the current runtime, then the compatibility runtime, then a default current-runtime request. Retries are bounded; cancellation, rate limits and inaccessible private communities stop immediately.
- Discards expired cookie entries and shows unexpired cookie counts and sign-in cookie presence in Settings. Enabled cookies do not guarantee that a website accepts the session.
- Gives specific guidance for Reddit session rejection, YouTube verification and HTTP 429.
- Retains audio-only M4A downloads, video quality selection, Downloads folder access, media validation and existing FFmpeg isolation fixes.
- Publishes the Telegram companion with original-quality large-file delivery and a new optional YouTube/Reddit cookie setup cell. Cookies are imported into private runtime storage and used for both analysis and downloads. An explicit Telegram user allowlist is required when account cookies are enabled.

Choose **VidFetch_v8a_0.3.8.apk** for most current Android phones, or **VidFetch_v7a_0.3.8.apk** for 32-bit ARM phones. Both require Android 7.0+ and use the existing release signing identity.

Open the updated bot notebook from the repository's main branch and run all cells. Saved copies contain their previous embedded source. In the optional cookies cell choose Import / replace for each site, upload a Netscape export, then enter your Telegram ID in the start cell. Use /id with cookies disabled to find it. Every allowlisted user can use the imported accounts; only list trusted people.

Automated checks exercise controlled media fixtures and Android emulators. Live Reddit/YouTube access can still be restricted by account/session validity, network reputation, verification requirements or upstream site changes. Private credentials are never included in the source, notebook or APK.
