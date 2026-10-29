VidFetch 0.4.0 adds individual cancellation, concurrent downloads and a home-screen widget.

- Android can run two downloads at once and queue additional videos or audio. Home, Downloads and notifications show separate progress and Cancel controls for each transfer. You can analyze another link while transfers continue.
- Cancelling a transfer stops its extractor and media subprocesses and removes partial files without interrupting the other requests. Parallel downloads safely reserve distinct filenames.
- Add **VidFetch · Paste link** from the home screen's Widgets picker. Copy a link and tap the widget to open a compact native window with Paste, Analyze, quality selection and Download controls. Downloads continue after closing the window.

Choose **VidFetch_v8a_0.4.0.apk** for most current Android phones, or **VidFetch_v7a_0.4.0.apk** for 32-bit ARM phones. Both require Android 7.0+. The GitHub release workflow signs builds with the existing permanent release identity. Local builds without that key use development signing and cannot update an installed published release.

Android transfers do not survive process termination or restart. Website access still depends on session validity, network reputation and upstream restrictions. Extraction and processing in the Android app remain local to the phone.
