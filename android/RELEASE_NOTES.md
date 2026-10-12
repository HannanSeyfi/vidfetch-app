VidFetch 0.3.2 fixes missing quality choices for Pornhub downloads.

- Shows available resolutions when direct MP4 formats provide a height without a video codec name.
- Handles missing, null and empty codec metadata as unknown instead of excluding those formats.
- Keeps audio-only formats and storyboards out of the quality list and groups duplicate resolutions.
- Adds an Android regression test for the complete JSON-to-quality-list path.

Choose VidFetch_v8a_0.3.2.apk for most current Android phones, or VidFetch_v7a_0.3.2.apk for 32-bit ARM phones. Both require Android 7.0 or newer and use the existing release signing identity.

This update retains the extraction runtime, download selection rules and optional site cookies from 0.3.0. It does not fix the YouTube bot-verification issue. Verification uses synthetic Pornhub-style metadata and controlled media downloads; an individual live Pornhub URL has not been tested.
