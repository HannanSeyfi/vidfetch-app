# VidFetch

VidFetch is a privacy-minded, local-first video and audio downloader for content a user is permitted to download. The native Android app uses site support provided by yt-dlp and processes media on the user's device; URLs are not sent to a VidFetch service.

## Download for Android

[**Download the latest Android release**](https://github.com/HannanSeyfi/vidfetch-app/releases/latest)

Choose the **v8a** APK for most current Android phones (`arm64-v8a`), or **v7a** for 32-bit ARM phones. Android may ask you to allow installation from your browser or file manager. The release page shows the latest published build.

Android 0.4.0 supports individual cancellation, two concurrent downloads with per-transfer progress, and a **Paste link** home-screen widget.

## Platforms

| Platform | Status |
| --- | --- |
| Android | In development |
| iOS | Planned |
| Windows | Planned |
| [<img src=".github/assets/telegram.svg" width="18" height="18" alt="" />@VidFetchRobot](https://t.me/VidFetchRobot) | Telegram companion |

## Download with Telegram

**Video and audio downloads, right in Telegram.** Send a link to [@VidFetchRobot](https://t.me/VidFetchRobot), choose a video quality or **Audio only**, and get your file in chat. Follow each download's progress and cancel individual downloads when you need to.

You can also type `@VidFetchRobot` followed by a link in another Telegram chat to get started without switching conversations.

[**Try VidFetch on Telegram →**](https://t.me/VidFetchRobot)

## Repository layout

`android/` contains the native Android Studio project. Future native implementations will live in their own platform directories.

See [the Android README](android/README.md) for setup, architecture, limitations, and build instructions.
