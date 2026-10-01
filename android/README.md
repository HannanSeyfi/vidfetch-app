# VidFetch for Android

Native Kotlin/Jetpack Compose implementation for Android 7.0+ (minSdk 24), compiled and targeted at API 36. The UI is MVVM-ready with a dedicated `YtDlpRepository`; extractor work is off the main thread. The app uses the maintained `io.github.junkfood02.youtubedl-android` 0.18.1 wrapper and its bundled FFmpeg module, both local on-device.

## Storage and privacy

The intended final public destination is `Downloads/VidFetch/` via MediaStore; intermediate media belongs in app-private storage. No remote VidFetch server, analytics, or advertising SDK is used. Optional future cookie import must use SAF and private storage only.

## Build

Use JDK 17 and an Android SDK with API 36 installed.

```text
cd android
./gradlew test
./gradlew assembleDebug
```

Windows: `gradlew.bat test` and `gradlew.bat assembleDebug`. The debug APK is `app/build/outputs/apk/debug/app-debug.apk`.

## Limitations

The selected wrapper bundles yt-dlp and FFmpeg, does not need Python or Termux, and supports arm64-v8a/x86_64. Extractors change frequently: update the wrapper dependency after reviewing its release notes and licensing. Authentication-restricted and TLS-fingerprint-protected sites may need users' own cookies; VidFetch does not bypass access controls.
