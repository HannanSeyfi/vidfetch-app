VidFetch 0.3.0 expands local site compatibility with an updated extraction runtime and download rules.

- Bundles yt-dlp 2026.10.10.233141 and its JavaScript challenge components.
- Adds curl_cffi browser-compatible networking, Python 3.14, QuickJS-ng, and FFmpeg/ffprobe 8.1.2 on both ARM architectures.
- Prefers direct MP4 streams for Pornhub and supports flexible combined/separate stream selection for other yt-dlp-supported sites.
- Keeps public downloading available without imported cookies; adds optional Netscape cookies.txt import, replacement, enable/disable and deletion per site.
- Keeps cookies in private storage excluded from backups and uses them for both analysis and downloading.
- Shows the actual extraction engine version, preserves newer installed extractors, and verifies nightly update checksums.
- Reports the downloaded resolution when a requested quality falls back.

Choose VidFetch_v8a_0.3.0.apk for most current Android phones, or VidFetch_v7a_0.3.0.apk for 32-bit ARM phones. Both require Android 7.0 or newer and use the existing release signing identity.

Automated checks cover unit tests, Android builds, native runtime startup, browser impersonation targets, MP4/HLS/DASH downloads with audio and video, and cookie controls. Website and IP restrictions can still affect individual links; this release does not claim every yt-dlp-supported site or the supplied YouTube example is reachable from every network. The pinned native runtime is an upstream contribution pending merge; physical ARM device verification remains a field-testing limitation.
