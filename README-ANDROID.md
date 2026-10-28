# My Home Cinema Android — Java app

This branch adds a native Android app, in Java, that does the same job
as the Python server, but without Termux or a PC:

- Open the app on your phone
- Type (or keep) your movies folder, for example `/storage/emulated/0/Movies`
- Tap **Start Sharing**
- The app shows a big address like `http://192.168.1.10:8000`
- Open that address on your TV browser (same Wi-Fi) — same Netflix-style
  page, Local movies/series from that folder, plus the Online tab

The server runs as a foreground service with a notification, so it
keeps sharing while you watch. Tap **Stop Sharing** to stop it.
Tap **Copy Address** to copy the URL, or **Open on This Phone** to
test the page on the phone itself.

## What is inside

Pure Java, no external libraries, no Kotlin:

- `app/src/main/java/com/myhomecinema/app/MainActivity.java` — UI: folder, port, Start/Stop, IP:port, Copy, Open
- `app/src/main/java/com/myhomecinema/app/SharingService.java` — foreground service that owns the server
- `app/src/main/java/com/myhomecinema/app/HomeCinemaServer.java` — HTTP server: `/`, `/api/status`, `/api/library`, `/stream` (Range/seeking), `/poster`, `/subtitles` (.srt → WebVTT)
- `app/src/main/assets/index.html` — the same My Home Cinema web UI as `server.py` (v0.7), served to the TV browser
- `app/src/main/AndroidManifest.xml`, `app/src/main/res/layout/activity_main.xml`

Folder layout that works best (same as the Python server):

```
Movies/Avatar (2009)/Avatar (2009).mp4
Movies/Avatar (2009)/poster.jpg
Series/Demo Show/Season 1/Demo Show S01E01.mp4
```

MP4 + H.264 + AAC plays in almost every TV browser. MKV / HEVC / DTS
files are flagged in the UI, as in the Python version.

Permissions the app asks for: Internet, Wi-Fi/network state,
foreground service, notifications, and reading video files
(`READ_MEDIA_VIDEO` on Android 13+, storage read on older versions).
No account, no upload — local files stay on your Wi-Fi.

## Build the APK — shell (Java + shell, no Android Studio needed)

On a PC or Mac with JDK 17 and the Android SDK:

```bash
chmod +x build.sh
export ANDROID_HOME=$HOME/Android/Sdk   # adjust if your SDK is elsewhere
./build.sh
# -> ./My-Home-Cinema-debug.apk
```

`build.sh` checks Java and the SDK, downloads Gradle 8.5 once if
Gradle is not installed, runs `gradle assembleDebug`, and copies the
APK to the repo root as `My-Home-Cinema-debug.apk`.

SDK parts needed: `platforms;android-34` and `build-tools;34.0.0`.
Install them with Android Studio, or with:
`sdkmanager "platforms;android-34" "build-tools;34.0.0"`

## Build the APK — Android Studio

Open this repo root in Android Studio, let it sync Gradle, then
Run (or Build → Build App Bundle(s) / APK(s) → Build APK(s)).
Install the debug APK on your phone and allow install from that source.

## Build the APK — GitHub Actions (no local SDK)

The workflow in `.github/workflows/android.yml` (see note below)
builds the debug APK on every push to this `android` branch and
uploads it as an artifact named `My Home Cinema-debug-apk`. Download it
from the Actions run, install it on your phone, and use it as above.

> Note: the Muse GitHub App cannot create `.github/workflows/` files
> directly (GitHub blocks workflow files from integrations, 403).
> If that file is missing from this branch, add it manually in the
> GitHub web UI: create `.github/workflows/android.yml` and paste
> the content from `android-workflow.yml.txt` in this repo root.
> After that, pushing to `android` will build the APK in Actions.

## Install and use

1. Install `My-Home-Cinema-debug.apk` on your Android phone.
2. Allow the video and notification permissions when asked.
3. Keep the default folder, or type your own, and tap Start Sharing.
4. Note the address, for example `http://192.168.1.10:8000`.
5. On the TV browser (same Wi-Fi, Jio STB browser works), open that address.
6. Keep the phone on Wi-Fi and charging while you watch.
7. Tap Stop Sharing when you are done.
