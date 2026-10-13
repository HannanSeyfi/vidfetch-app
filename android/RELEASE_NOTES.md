VidFetch 0.3.5 improves Downloads folder visibility and YouTube video output.

- Removes the Reddit/RedGIFs explanation under Extractor.
- Adds persistent access to Downloads/VidFetch so copied-in and restored videos appear on Refresh. Moved-out or deleted files disappear, and the list refreshes when the app resumes.
- Publishes the exact completed file reported by yt-dlp, checking it contains a real video stream. Audio intermediates cannot be saved as successful video downloads.
- Prefers compatible YouTube H.264 video and M4A/AAC audio at the chosen resolution and remuxes final output to MP4. Higher resolutions remain available through other offered codecs.
- Keeps the extraction runtimes, nightly version, Reddit/RedGIFs compatibility route and other site format selectors from the working 0.3.4 release.
- Adds Android regression checks for folder grants, moved/restored files, separate video/audio merging, resolution choices, final MP4 output and audio-only rejection.

Choose VidFetch_v8a_0.3.5.apk for most current Android phones, or VidFetch_v7a_0.3.5.apk for 32-bit ARM phones. Both require Android 7.0 or newer and use the existing release signing identity.

On Android 10 or newer, open Downloads, tap **Allow folder access**, then select **Downloads/VidFetch** and allow access once. This includes files placed there by other apps without requesting access to the whole storage or video library.

Automated downloads use controlled Android fixtures. Live sites may require verification or reject the development/CI network independently of the on-device pipeline.
