# VidFetch

VidFetch is a privacy-minded, local-first video downloader for content a user is permitted to download. It uses site support provided by yt-dlp and processes media on the user's device; URLs are not sent to a VidFetch service.

## Download for Android

[**Download the latest Android APK**](https://github.com/HannanSeyfi/vidfetch-app/releases/latest/download/VidFetch_v8a_0.1.2.apk)

This APK is for most current Android phones (`arm64-v8a`). GitHub publishes it after each successful build of `main`; Android may ask you to allow installation from your browser or file manager.

## Platforms

| Platform | Status |
| --- | --- |
| Android | In development |
| iOS | Planned |
| Windows | Planned |

## Repository layout

`android/` contains the native Android Studio project. Future native implementations will live in their own platform directories.

See [the Android README](android/README.md) for setup, architecture, limitations, and build instructions.
