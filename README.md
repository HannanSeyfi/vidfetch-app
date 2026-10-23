# VidFetch

VidFetch is a privacy-minded, local-first video downloader for content a user is permitted to download. The native Android app uses site support provided by yt-dlp and processes media on the user's device; URLs are not sent to a VidFetch service.

## Download for Android

[**Download the latest Android APK**](https://github.com/HannanSeyfi/vidfetch-app/releases/latest/download/VidFetch_v8a_0.3.6.apk)

This APK is for most current Android phones (`arm64-v8a`). GitHub publishes it after each successful build of `main`; Android may ask you to allow installation from your browser or file manager. Version 0.3.6 fixes a media-library conflict that could block saving downloaded videos in 0.3.5. It retains folder access for moved-in and restored videos, YouTube MP4 selection and merging, the existing extraction runtimes, Pornhub quality choices and optional site cookies. A 32-bit ARM APK is also available on the release page.

## Platforms

| Platform | Status |
| --- | --- |
| Android | In development |
| iOS | Planned |
| Windows | Planned |

## Telegram companion

The separate [Telegram bot](bot/README.md) runs from a self-contained Colab notebook alongside Telegram's official local Bot API server. Enter a bot token plus Telegram application credentials, send a link, and choose a video quality or Audio only. Original quality is preserved without a 50 MB compression requirement; files above the conservative 1,950 MB per-file ceiling are delivered in numbered parts with a verified joiner. Colab sessions are temporary; see the bot documentation for setup and limits. The Android app continues to process downloads on-device independently.

## Repository layout

`android/` contains the native Android Studio project. `bot/` contains the independent Python Telegram companion and Colab notebook. Future native implementations will live in their own platform directories.

See [the Android README](android/README.md) for setup, architecture, limitations, and build instructions.
