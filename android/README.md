# VidFetch for Android

Native Kotlin/Jetpack Compose implementation for Android 7.0+ (minSdk 24), compiled and targeted at API 36. Version 0.2.2 uses a ViewModel for screen state, a foreground service for user-started downloads, and a dedicated `YtDlpRepository` for off-main-thread extraction. The app uses `io.github.junkfood02.youtubedl-android` 0.18.1 and its bundled FFmpeg module, both local on-device.

## Storage and privacy

yt-dlp writes intermediate files to app-specific storage. Completed videos are published to `Downloads/VidFetch/` through MediaStore on Android 10+; Android 7–9 use the public folder with the legacy storage permission. The Downloads screen also looks for accessible videos saved by earlier VidFetch versions. Local video frames are decoded for thumbnails with Coil; files that cannot be decoded show a fallback icon. No remote VidFetch server, analytics, or advertising SDK is used.

The Settings screen shows the author's GitHub profile photo in its About card, with a local fallback icon when the photo cannot load. The last card is a Telegram blue contact button; it opens the author's Telegram profile through the `tg:` app link, with a `t.me` fallback when Telegram is unavailable. The account name is not displayed in the Settings UI.

## Build

Use JDK 17 and an Android SDK with API 36 installed.

```text
cd android
./gradlew test
./gradlew assembleDebug
```

Windows: `gradlew.bat test` and `gradlew.bat assembleDebug`. The debug APKs are `app/build/outputs/apk/debug/app-arm64-v8a-debug.apk` and `app/build/outputs/apk/debug/app-armeabi-v7a-debug.apk`.

## Limitations

The selected wrapper bundles yt-dlp, FFmpeg, and QuickJS, so it does not need Python, Termux, or a separate Deno installation. VidFetch enables QuickJS and retries temporary network errors. It leaves YouTube client selection to yt-dlp's current defaults so the extractor can choose the best supported formats. Extractors change frequently: update the wrapper dependency after reviewing its release notes and licensing. Authentication-restricted and TLS-fingerprint-protected sites may still require a user's authorized session; VidFetch does not bypass access controls.

Downloads run while the foreground service remains active, but do not resume after a force-stop, reboot, or process termination. The app lists its own MediaStore downloads; files from an earlier installation may require importing through the system file picker in a future update.
