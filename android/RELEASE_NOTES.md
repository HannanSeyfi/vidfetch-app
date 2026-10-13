VidFetch 0.3.6 fixes the download-saving regression introduced in 0.3.5.

- Fixes FFmpeg/ffprobe inheriting Python's private OpenSSL libraries. On affected phones this caused an `EVP_MD_CTX_init` / system SQLite linker failure after the video had downloaded, preventing it from being saved.
- Isolates every FFmpeg/ffprobe process launched by yt-dlp, including merging and remuxing, under both extraction runtimes.
- Runs final video validation directly through the isolated ffprobe process.
- Retains the existing extractor version, Reddit/RedGIFs compatibility route, site format choices, optional cookies, Downloads folder access and YouTube MP4 improvements.
- Adds Android regression checks for the actual subprocess environment, both Python runtimes and direct media-tool execution, alongside the existing download, merge and folder tests.

Choose **VidFetch_v8a_0.3.6.apk** for most current Android phones, or **VidFetch_v7a_0.3.6.apk** for 32-bit ARM phones. Both require Android 7.0 or newer and use the existing release signing identity, so they can update an existing installation.

For copied-in or restored videos on Android 10+, open Downloads, tap **Allow folder access**, then select **Downloads/VidFetch** once.

Automated runtime checks use Android emulators and controlled download fixtures. The affected physical ARM phone still needs confirmation after installing this hotfix; live-site availability can also vary with network and verification requirements.
