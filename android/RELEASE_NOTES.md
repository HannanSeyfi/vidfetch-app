VidFetch 0.3.7 adds audio downloads to quality selection.

- After analyzing a shared or pasted link, select **Audio only · M4A** and tap **Download audio**.
- Downloads the best available audio stream, or extracts audio from a combined video when a separate stream is unavailable. Extraction and conversion run locally on the phone.
- Saves M4A audio in **Downloads/VidFetch**. The Downloads tab lists audio with a music icon and supports opening, sharing, renaming and deleting it.
- Hides audio selection for formats explicitly marked silent. Links with unspecified audio metadata can still be tried; files without an audio stream are never published as completed audio.
- Keeps existing video quality choices, YouTube MP4 merging, Reddit/RedGIFs compatibility, optional cookies and the 0.3.6 FFmpeg library fix.
- Adds Android regression checks for separate and combined streams, audio validation, folder operations and the shared-link audio selection flow.

Choose **VidFetch_v8a_0.3.7.apk** for most current Android phones, or **VidFetch_v7a_0.3.7.apk** for 32-bit ARM phones. Both require Android 7.0 or newer and use the existing release signing identity, so they can update an existing installation.

For copied-in or restored media on Android 10+, open Downloads, tap **Allow folder access**, then select **Downloads/VidFetch** once.

Automated runtime checks use Android emulators and controlled media fixtures. Physical ARM devices still need field verification; live-site availability can vary with network and verification requirements.
