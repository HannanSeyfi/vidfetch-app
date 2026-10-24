# VidFetch for Android

Native Kotlin/Jetpack Compose implementation for Android 7.0+ (minSdk 24), compiled and targeted at API 36. Version 0.3.8 uses a ViewModel, a foreground download service, and local on-device extraction through `YtDlpRepository`.

## Multi-site extraction

The APK bundles yt-dlp **2026.10.23.233055**, with its built-in EJS challenge components. The native runtime provides Python 3.14, curl_cffi, QuickJS-ng 0.16.2, FFmpeg and ffprobe 8.1.2. Settings displays the actual installed yt-dlp, Python and curl_cffi versions. No Python, Termux or Deno installation is required on the phone.

Site support comes from yt-dlp's extractors. VidFetch leaves YouTube client selection to yt-dlp and uses Chrome browser impersonation for Reddit requests. Generic downloads support separate or combined video/audio streams; Pornhub requests prefer direct MP4 before other combined formats. A selected resolution falls back only to the same or a lower resolution. When known, the completion message reports a different downloaded resolution.

YouTube sorts resolution first, preferring H.264/AAC when available at that resolution, requests M4A audio where available and remuxes completed output to MP4. The app uses yt-dlp's reported `after_move` filepath, validates that it exists inside the working directory, and checks the final file with ffprobe for a real video stream. Audio intermediates are never selected by modification time or published as completed videos. Other sites retain their 0.3.4 format selectors and extraction profiles; silent videos remain supported.

FFmpeg and ffprobe use their own shared-library search path without Python's private OpenSSL libraries. A Python startup hook applies this environment to yt-dlp's media subprocesses under both interpreters; final-file validation launches ffprobe directly with the same isolation. This fixes the 0.3.5 save failure where a phone's system SQLite library requested `EVP_MD_CTX_init` from the wrong `libcrypto.so`.

Quality choices include formats with a known resolution even when the video codec is unspecified, as with Pornhub's direct MP4 formats. Formats explicitly marked as having no video are excluded; duplicate resolutions are grouped.

**Audio only · M4A** appears alongside video qualities when the link has a format that may contain audio. Formats explicitly marked silent do not enable it; direct MP4 formats with unspecified audio metadata remain eligible. Audio links offer audio without a video choice. The download service prefers the best separate audio stream, falling back to a combined stream, then uses local FFmpeg to extract M4A (AAC). AAC can be copied without re-encoding; other codecs are converted with yt-dlp's highest VBR quality setting. Audio output size is left unknown because conversion can change it. No video resolution or YouTube MP4 remux options apply to audio downloads. Final ffprobe validation requires an audio stream and rejects remaining video before publishing the completed file.

The existing Update extractor button downloads an official nightly, verifies its SHA-256 checksum and version, and installs it atomically. Upgrading the app replaces an older bundled extractor while retaining a newer installed nightly.

Reddit first uses the current Python 3.14/curl_cffi runtime with Chrome impersonation. Eligible session/403 failures try the Python 3.12 compatibility runtime with Chrome, then the current runtime's default request profile, with at most three attempts. The exact Reddit API rejection message also triggers fallback. RedGIFs retains compatibility-first/current-second behavior. Cancellation, HTTP 429, inaccessible private communities and unrelated failures are not retried. Both runtimes use the same updated yt-dlp. Site downloads restart partial files between attempts. Browser profiles and cookies cannot guarantee access when a website rejects the session or network. See runtime/README.md for runtime provenance.

## Optional site cookies

Public downloads use no imported cookies by default. In Settings, enter the website domain and choose Import / replace cookies.txt through Android's file picker. Exports must use Netscape format. The importer validates entries and retains only cookies for that domain and its subdomains. YouTube aliases use the youtube.com configuration. Reddit aliases, including `redd.it`, `v.redd.it`, `old.reddit.com` and `redditmedia.com`, select the reddit.com jar before redirects; the cookie jar still enforces each cookie's original domain. Expired entries are discarded, entirely expired exports are rejected, and Settings reports unexpired cookie counts and the presence of common sign-in cookie names. This is a local check, not confirmation that a website accepts the session. For Reddit, try a fresh signed-in Chrome export.

Each site has an enable switch and delete control. Cookie files, settings and per-request snapshots live in `noBackupFilesDir`, outside backups and the media FileProvider. No account cookies are logged or sent to a VidFetch service. Analysis and downloading use the same site configuration. Importing or changing cookies clears an existing analysis so it can be refreshed.

## Storage and privacy

yt-dlp writes intermediate files to app-specific storage. Completed videos and audio are published to Downloads/VidFetch through MediaStore on Android 10+; Android 7–9 use the public folder with the legacy storage permission. On Android 10+, tap Allow folder access in Downloads and select Downloads/VidFetch once. The persistent system folder grant lets Refresh list media directly from that folder, including files moved in by other apps or returned after being moved away. Moved-out and deleted files disappear. The list also refreshes when the app resumes. Without the grant, the app continues to show its accessible downloads. Audio files use audio MIME types for publishing, opening and sharing, and a music icon in the list; both media types support rename and delete. No broad media-library or all-files permission is requested. Local video frames provide video thumbnails. No remote processing service, analytics or advertising SDK is used.

Settings retains the author's GitHub profile photo and Telegram contact card.

The Extractor section displays component versions without the Reddit/RedGIFs runtime explanation.

## Build and verification

Use JDK 17 and an Android SDK with API 36 and build-tools 36.0.0 installed.

```text
cd android
./gradlew test assembleDebug assembleRelease bundleRelease
```

Windows: use gradlew.bat. The build downloads the exact artifacts in runtime/runtime-lock.json into app/build/generated/extractor and verifies their SHA-256 hashes. Generated binaries are not committed. See runtime/README.md for provenance and source links.

Debug APKs are app/build/outputs/apk/debug/app-arm64-v8a-debug.apk and app-armeabi-v7a-debug.apk. Release signing uses the existing VIDFETCH_KEYSTORE_* environment variables; GitHub CI restores the permanent signing key from repository secrets.

For an x86_64 Android emulator:

```text
./gradlew -PemulatorBuild=true connectedDebugAndroidTest
```

Instrumentation tests start both packaged interpreters with the same updated engine, run current-runtime dependencies and tools, and exercise the real Reddit and RedGIFs extractors against synthetic HTTP fixtures. They include a Reddit share redirect, anonymous Reddit session and RedGIFs token acquisition, the app's actual analysis/download CLI arguments under Python 3.12, MP4/HLS/DASH downloads and audio/video verification. A CLI startup warning followed by a private-subreddit error verifies that warnings cannot hide the failure. Other checks cover cookie controls and Pornhub quality metadata. JVM tests check preferred runtime, retry scope, cancellation, terminal errors and HTTP 403 messages. GitHub CI exercises API 24 and API 35 using tools/run_runtime_tests.py with non-streaming ADB installation to avoid the old emulator install-write transport issue. Required and live test reports are stored separately. An optional live check uses the supplied YouTube example; external site or IP restrictions can affect that check independently of the deterministic runtime tests.

0.3.5 regression checks use genuine separate H.264/VP9 video and AAC/Opus audio streams with the app's YouTube CLI options, verify requested resolutions and final MP4 audio/video, and reject an audio-only intermediate. Folder tests copy, move out, restore, rename and delete external files; Android 15 exercises the actual system folder picker and persisted grant.

0.3.6 adds checks at Python's actual subprocess execution boundary for inherited and explicit environments, standard subprocess calls and yt-dlp's Popen, under both packaged interpreters. It verifies that media children exclude Python library paths and startup settings while the parent extraction environment and unrelated children remain intact. Direct FFmpeg/ffprobe execution is also exercised.

0.3.7 adds separate-stream audio extraction under both interpreters, combined MP4/HLS/DASH audio extraction, final stream validation, audio folder operations and an end-to-end shared-link quality-selection/service download check. JVM tests distinguish audio selection from best video, hide audio for silent formats and verify audio-only links and cross-site selectors.

## Limitations

The runtime payload comes from a pinned upstream contribution that has not yet merged, rather than a released youtubedl-android AAR. Both ARM APKs are built; automated runtime execution uses x86_64 emulators. Physical ARM devices still need field verification. See runtime/README.md for the pinned revision.

Website support and availability can change. Regional restrictions, authentication, IP reputation and DRM can prevent downloads. Colab and a phone may receive different responses from the same site.

Downloads do not resume after a force-stop, reboot or process termination. Folder access must be granted again after reinstalling or revoking its system permission.

0.3.8 adds cookie alias/expiry checks, request-profile and bounded retry tests, distinct session/rate-limit errors, and on-device checks that both runtimes expose Chrome impersonation. Live verification still depends on the actual phone/network and user-provided sessions.
