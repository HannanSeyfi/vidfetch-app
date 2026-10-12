# VidFetch for Android

Native Kotlin/Jetpack Compose implementation for Android 7.0+ (minSdk 24), compiled and targeted at API 36. Version 0.3.2 uses a ViewModel, a foreground download service, and local on-device extraction through `YtDlpRepository`.

## Multi-site extraction

The APK bundles yt-dlp **2026.10.10.233141**, matching the successful reference notebook, with its built-in EJS challenge components. The native runtime provides Python 3.14, curl_cffi, QuickJS-ng 0.16.2, FFmpeg and ffprobe 8.1.2. Settings displays the actual installed yt-dlp, Python and curl_cffi versions. No Python, Termux or Deno installation is required on the phone.

Site support comes from yt-dlp's extractors. VidFetch leaves YouTube client selection and extractor-specific browser impersonation to yt-dlp. Generic downloads support separate or combined video/audio streams; Pornhub requests prefer direct MP4 before other combined formats. A selected resolution falls back only to the same or a lower resolution. When known, the completion message reports a different downloaded resolution.

Quality choices include formats with a known resolution even when the video codec is unspecified, as with Pornhub's direct MP4 formats. Formats explicitly marked as having no video are excluded; duplicate resolutions are grouped.

The existing Update extractor button downloads an official nightly, verifies its SHA-256 checksum and version, and installs it atomically. Upgrading the app replaces an older bundled extractor while retaining a newer installed nightly.

## Optional site cookies

Public downloads use no imported cookies by default. In Settings, enter the website domain and choose Import / replace cookies.txt through Android's file picker. Exports must use Netscape format. The importer validates entries and retains only cookies for that domain and its subdomains. YouTube aliases use the youtube.com configuration.

Each site has an enable switch and delete control. Cookie files, settings and per-request snapshots live in `noBackupFilesDir`, outside backups and the media FileProvider. No account cookies are logged or sent to a VidFetch service. Analysis and downloading use the same site configuration. Importing or changing cookies clears an existing analysis so it can be refreshed.

## Storage and privacy

yt-dlp writes intermediate files to app-specific storage. Completed videos are published to Downloads/VidFetch through MediaStore on Android 10+; Android 7–9 use the public folder with the legacy storage permission. The Downloads screen finds accessible videos saved by earlier versions. Local video frames provide thumbnails. No remote processing service, analytics or advertising SDK is used.

Settings retains the author's GitHub profile photo and Telegram contact card.

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

Instrumentation tests start the actual packaged interpreter, import curl_cffi, execute QuickJS and FFmpeg/ffprobe, enumerate browser impersonation targets, download generated MP4, HLS and separate-stream DASH media without cookies, check audio/video streams, and verify cookie storage and switches. A metadata regression test checks the JSON-to-quality-list path with Pornhub-style direct MP4 formats, missing/null/empty codec metadata, duplicate resolutions, and audio-only entries. GitHub CI exercises API 24 and API 35 using tools/run_runtime_tests.py with non-streaming ADB installation to avoid the old emulator install-write transport issue. Required and live test reports are stored separately. An optional live check uses the supplied YouTube example; external site or IP restrictions can affect that check independently of the deterministic runtime tests.

## Limitations

The runtime payload comes from a pinned upstream contribution that has not yet merged, rather than a released youtubedl-android AAR. Both ARM APKs are built; automated runtime execution uses x86_64 emulators. Physical ARM devices still need field verification. See runtime/README.md for the pinned revision.

Website support and availability can change. Regional restrictions, authentication, IP reputation and DRM can prevent downloads. Colab and a phone may receive different responses from the same site.

Downloads do not resume after a force-stop, reboot or process termination. Old files inaccessible after reinstalling may require a future system file-picker import.
