# YLSY Atlas Android 4.0.0

Android Studio project packaging the shared YLSY Atlas Python/SQLite backend and phone UI with Chaquopy. Drive authentication remains OAuth/PKCE; Android OAuth tokens are encrypted with Android Keystore. The app uses system insets, theme-matched system bars, a hidden-scrollbar 95vw layout, responsive drawer gestures, native file selection/export and automatic background synchronization.

Open this directory with Android Studio and run `gradlew.bat assembleDebug` (or `./gradlew assembleDebug`). Requires JDK 17+, Android SDK 36 and network access on the first build.

