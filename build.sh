#!/bin/bash
# My Home Cinema Android — build the debug APK with Java + shell.
# Usage:  ./build.sh
# Needs:  JDK 17, Android SDK (platforms;android-34, build-tools;34.0.0),
#         and Gradle (installed, or downloaded automatically below).
set -e
cd "$(dirname "$0")"

echo "== My Home Cinema Android build =="

# 1. Java 17
if ! command -v java >/dev/null 2>&1; then
  echo "ERROR: Java not found. Install JDK 17 first (Android Studio bundles one, or: sudo apt install openjdk-17-jdk)."
  exit 1
fi
java -version 2>&1 | head -1

# 2. Android SDK
if [ -z "$ANDROID_HOME" ]; then
  for cand in "$HOME/Android/Sdk" "$HOME/Library/Android/sdk" "/opt/android-sdk" "/usr/lib/android-sdk"; do
    if [ -d "$cand/platform-tools" ]; then ANDROID_HOME="$cand"; break; fi
  done
fi
if [ -z "$ANDROID_HOME" ] || [ ! -d "$ANDROID_HOME" ]; then
  echo "ERROR: ANDROID_HOME is not set and no SDK was found."
  echo "Install Android Studio, or the command-line tools, then:"
  echo "  export ANDROID_HOME=\$HOME/Android/Sdk"
  echo "  sdkmanager \"platforms;android-34\" \"build-tools;34.0.0\""
  exit 1
fi
echo "ANDROID_HOME=$ANDROID_HOME"
export ANDROID_HOME

# 3. Gradle (use system gradle, or download Gradle 8.5 once)
if command -v gradle >/dev/null 2>&1; then
  GRADLE_CMD="gradle"
else
  GRADLE_DIR="$HOME/.gradle-dist/gradle-8.5"
  if [ ! -x "$GRADLE_DIR/bin/gradle" ]; then
    echo "Gradle not found — downloading Gradle 8.5 (one time)..."
    mkdir -p "$HOME/.gradle-dist"
    cd "$HOME/.gradle-dist"
    curl -L -o gradle-8.5-bin.zip https://services.gradle.org/distributions/gradle-8.5-bin.zip
    unzip -q -o gradle-8.5-bin.zip
    cd - >/dev/null
  fi
  GRADLE_CMD="$GRADLE_DIR/bin/gradle"
fi
echo "Gradle: $GRADLE_CMD"

# 4. Build
"$GRADLE_CMD" assembleDebug

APK="app/build/outputs/apk/debug/app-debug.apk"
if [ -f "$APK" ]; then
  cp "$APK" ./My-Home-Cinema-debug.apk
  echo ""
  echo "OK: APK built -> ./My-Home-Cinema-debug.apk"
  ls -lh ./My-Home-Cinema-debug.apk
  echo "Install it on your phone (allow install from this source), open My Home Cinema,"
  echo "type your movies folder, tap Start Sharing, and open the shown"
  echo "http://192.168.x.x:8000 address on your TV browser."
else
  echo "ERROR: APK not found at $APK"
  exit 1
fi
