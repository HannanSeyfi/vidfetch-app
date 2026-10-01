# VidFetch contributor guidance

VidFetch is a multi-platform product repository. Android is the active native implementation; iOS and Windows are planned and must remain separate from Android code. Never commit secrets, cookies, tokens, keystores, SDK paths, or generated binaries. Keep documentation accurate. Run relevant tests and builds before completing substantial changes.

Android code belongs in `android/`. Use Kotlin, native Android APIs, Jetpack Compose, Material 3, and local on-device extraction/processing. Do not replace the app with a WebView or a remote video-processing service. Do not add advertising or analytics SDKs.
