# Pinned extraction runtime

The build generates native libraries and the yt-dlp resource from runtime-lock.json. Every artifact has a SHA-256 digest. The binaries are build output and must never be committed.

## Sources

* yt-dlp 2026.10.10.233141: https://github.com/yt-dlp/yt-dlp-nightly-builds/releases/tag/2026.10.10.233141
* Native runtime revision: https://github.com/hussain-najeb/youtubedl-android/tree/35f2609d80ce26b6683a0b2b6bc52f32efe4c81c
* Upstream contribution and validation notes: https://github.com/yausername/youtubedl-android/pull/361
* Python/runtime packaging scripts: library/build-python-bundle-arm64.sh, library/build-python-bundle-armv7.sh and library/build-python-bundle-x86.sh at that revision.
* FFmpeg packaging scripts: ffmpeg/package-arm64.sh, ffmpeg/package-armv7.sh and ffmpeg/package-x86.sh at that revision.
* CPython source: https://github.com/python/cpython (3.14)
* Termux runtime and FFmpeg build recipes: https://github.com/termux/termux-packages
* QuickJS-ng source: https://github.com/quickjs-ng/quickjs (0.16.2)
* curl_cffi source: https://github.com/lexiforest/curl_cffi (arm64 0.16.2; armv7 and x86_64 0.16.3b1)
* curl-impersonate source: https://github.com/lexiforest/curl-impersonate
* Android cross-build contributions: https://github.com/lexiforest/curl-impersonate/pull/305 and https://github.com/lexiforest/curl_cffi/pull/846

The native contribution is not yet merged upstream. VidFetch uses its immutable commit and verifies downloaded content, rather than following the contributor's moving branch. ARM64 and ARMv7 binaries are distributed; x86_64 binaries are used only for instrumentation tests.

The old wrapper dependency is removed. ExtractorRuntime unpacks runtime data in noBackupFilesDir, supplies the certificate and shared-library paths, invokes APK-installed executables without a shell, and serializes updates with extraction. The yt-dlp resource includes EJS components; QuickJS-ng runs those components without Deno. Native executables are never downloaded during app use.

When changing the runtime, update the lockfile, BuildConfig runtime constants, component notices, and the Android runtime tests together. Keep the minimum supported Android API and both phone architectures.
