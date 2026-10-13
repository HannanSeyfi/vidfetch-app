VidFetch 0.3.4 corrects the Reddit and RedGIFs compatibility path.

- Runs the updated yt-dlp extractor with the Python 3.12/networking runtime from 0.2.2 for Reddit and RedGIFs. The working 0.2.2 installation had used Update extractor; 0.3.3 incorrectly restored its original frozen 2025 extractor instead.
- Uses that combination first for analysis and downloading, with a modern-runtime retry for HTTP 403 or anonymous-session rejection.
- Makes Update extractor apply to both runtimes and removes the frozen extractor from the APK and private storage.
- Shows the terminal extraction error instead of treating a non-fatal startup age warning as the failure.
- Adds Android regression checks using the app's actual CLI arguments, anonymous session/token fixtures, selected qualities, downloads with audio and video, and warning/error handling.
- Retains the Pornhub quality fix, optional site cookies and current runtime for other sites.

Choose VidFetch_v8a_0.3.4.apk for most current Android phones, or VidFetch_v7a_0.3.4.apk for 32-bit ARM phones. Both require Android 7.0 or newer and use the existing release signing identity.

The supplied Reddit example remains inaccessible from the development network. Controlled Android tests verify the updated-engine/older-runtime combination; successful access to that exact live link on the user's phone still needs confirmation.
