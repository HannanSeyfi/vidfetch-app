VidFetch 0.4.0 adds individual cancellation, concurrent downloads, a home-screen widget and Telegram inline downloads.

- Android can run two downloads at once and queue additional videos or audio. Home, Downloads and notifications show separate progress and Cancel controls for each transfer. You can analyze another link while transfers continue.
- Cancelling a transfer stops its extractor and media subprocesses and removes partial files without interrupting the other requests. Parallel downloads safely reserve distinct filenames.
- Add **VidFetch · Paste link** from the home screen's Widgets picker. Copy a link and tap the widget to open a compact native window with Paste, Analyze, quality selection and Download controls. Downloads continue after closing the window.
- The Telegram bot runs two requests concurrently, with up to five per user and 20 total active/queued requests. Each request has progress and its own Cancel button. /status lists all requests; /cancel offers individual choices, /cancel ID selects one, and /cancel all explicitly cancels all of yours. Earlier quality menus stay usable when another link is added.
- Telegram inline mode lets you type @VidFetchRobot URL in another chat, select the download result, choose a quality and receive the resulting video or audio in that same message. Tap **Show qualities** if analysis has not started. Approvals, personal cookie routing and owner-only controls remain in force.
- Enable /setinline for this bot in BotFather. Optionally enable /setinlinefeedback at 100% for automatic analysis after result selection. Send /start privately once so the bot can stage the upload, reuse its Telegram file ID in the destination message and remove the temporary private copy. Oversized files retain lossless splitting and are delivered to your private bot chat with their verified joiner.
- The self-contained Colab notebook includes the updated bot. Stop an old instance, reopen the latest notebook and run all cells to load the new source.

Choose **VidFetch_v8a_0.4.0.apk** for most current Android phones, or **VidFetch_v7a_0.4.0.apk** for 32-bit ARM phones. Both require Android 7.0+. The GitHub release workflow signs builds with the existing permanent release identity. Local builds without that key use development signing and cannot update an installed published release.

Android transfers and bot queues do not survive process termination or restart. Website access still depends on session validity, network reputation and upstream restrictions. Extraction and processing in the Android app remain local to the phone.
