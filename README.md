# VidFetch

VidFetch is a privacy-minded, local-first video and audio downloader for content a user is permitted to download. The native Android app uses site support provided by yt-dlp and processes media on the user's device; URLs are not sent to a VidFetch service.

## Download for Android

[**Download the latest Android APK**](https://github.com/HannanSeyfi/vidfetch-app/releases/latest/download/VidFetch_v8a_0.3.9.apk)

This APK is for most current Android phones (`arm64-v8a`). Version 0.3.9 adds a fallback for public Reddit videos whose JSON endpoint returns HTTP 403, updates the bundled extractor, fixes Reddit cookie selection for short links, adds Reddit browser request profiles and clearer session/rate-limit errors, and shows cookie expiry/sign-in status. Existing video/audio downloads and storage fixes are retained. A 32-bit ARM APK is also available on the release page. Android may ask you to allow installation from your browser or file manager.

## Platforms

| Platform | Status |
| --- | --- |
| Android | In development |
| iOS | Planned |
| Windows | Planned |
| [<img src=".github/assets/telegram.svg" width="18" height="18" alt="" /> Telegram bot · @VidFetchRobot](https://t.me/VidFetchRobot) | Runs during active Colab sessions |

## Telegram companion

The separate [Telegram bot](bot/README.md) runs from a self-contained Colab notebook alongside Telegram's official local Bot API server. Enter a bot token plus Telegram application credentials, send a link, and choose a video quality or Audio only. Original quality is preserved without a 50 MB compression requirement; files above the conservative 1,950 MB per-file ceiling are delivered in numbered parts with a verified joiner. The notebook supports optional private YouTube/Reddit cookies with import, replace, enable, disable and delete controls. Account cookies require an explicit Telegram user allowlist. [Open the latest notebook](https://colab.research.google.com/github/HannanSeyfi/vidfetch-app/blob/main/bot/VidFetch_Telegram_Colab.ipynb). Colab sessions are temporary; see the bot documentation for setup and limits. The Android app continues to process downloads on-device independently.

## Repository layout

`android/` contains the native Android Studio project. `bot/` contains the independent Python Telegram companion and Colab notebook. Future native implementations will live in their own platform directories.

See [the Android README](android/README.md) for setup, architecture, limitations, and build instructions.
