# VidFetch

VidFetch is a privacy-minded, local-first video and audio downloader for content a user is permitted to download. It uses site support provided by yt-dlp and processes media on the user's device; URLs are not sent to a VidFetch service.

## Download for Android

[**Download the latest Android APK**](https://github.com/HannanSeyfi/vidfetch-app/releases/latest/download/VidFetch_v8a_0.3.7.apk)

This APK is for most current Android phones (`arm64-v8a`). GitHub publishes it after each successful build of `main`; Android may ask you to allow installation from your browser or file manager. Version 0.3.7 adds **Audio only · M4A** to quality selection for links with audio. Select it and tap **Download audio** to save an audio file in Downloads/VidFetch, where it can be opened, shared, renamed or deleted. Existing video downloads, extraction runtimes, optional cookies and the 0.3.6 media-library fix are retained. A 32-bit ARM APK is also available on the release page.

## Platforms

| Platform | Status |
| --- | --- |
| Android | In development |
| iOS | Planned |
| Windows | Planned |

## Repository layout

`android/` contains the native Android Studio project. Future native implementations will live in their own platform directories.

See [the Android README](android/README.md) for setup, architecture, limitations, and build instructions.
