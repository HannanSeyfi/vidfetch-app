# Pinned extraction runtime

The build generates native libraries and the yt-dlp resource from runtime-lock.json. Every artifact has a SHA-256 digest. The binaries are build output and must never be committed.

## Sources

* yt-dlp 2026.10.23.233055: https://github.com/yt-dlp/yt-dlp-nightly-builds/releases/tag/2026.10.23.233055
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

## Reddit and RedGIFs compatibility runtime

The separately packaged compatibility interpreter and Python data come from the released youtubedl-android 0.18.1 source at commit `d725d5c9a18c3a99a13ee0308bf78275dc310760`: https://github.com/yausername/youtubedl-android/tree/d725d5c9a18c3a99a13ee0308bf78275dc310760. Its Python version is 3.12. The ARM64 interpreter and Python archive bytes were compared against the published VidFetch 0.2.2 APK and match exactly. The payload is renamed to avoid replacing the current runtime, checksum-pinned in runtime-lock.json, and generated during the build. No generated binaries are committed.

The older interpreter uses its own Python/OpenSSL libraries and CA bundle. Current FFmpeg/ffprobe perform media processing; Android tests verify that pairing, including separate-stream merging. Compatibility Python data lives in a separate noBackupFilesDir subdirectory. Both interpreters execute the same installed yt-dlp file, so the nightly updater applies to both paths. This recreates the user's working 0.2.2 installation after Update extractor; the frozen 2025 extractor introduced in 0.3.3 is retired.

The old wrapper dependency is removed. ExtractorRuntime unpacks runtime data in noBackupFilesDir, supplies the certificate and shared-library paths, invokes APK-installed executables without a shell, and serializes updates with extraction. The yt-dlp resource includes EJS components; QuickJS-ng runs those components without Deno. Native executables are never downloaded during app use.

Python retains its own OpenSSL libraries for extraction. Since 0.3.6, an APK-owned `sitecustomize.py` startup hook gives only the exact APK FFmpeg and ffprobe executable paths a separate environment: their library search path contains FFmpeg's data libraries and the APK native directory, with Python startup variables, OpenSSL modules and preloads removed. Both interpreters load this hook before yt-dlp imports subprocess. Final-file validation starts ffprobe directly with the same media library path. This prevents Python's `libcrypto.so` from shadowing the Android platform library needed by system SQLite on affected devices. The hook is replaced from the installed APK at each app-process initialization, including upgrades that retain existing runtime data.

When changing the runtime, update the lockfile, BuildConfig runtime constants, component notices, and the Android runtime tests together. Keep the minimum supported Android API and both phone architectures.
