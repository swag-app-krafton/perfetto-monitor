#!/bin/sh
# Rebuilds labels.dex from Labels.java with the Android SDK (javac and d8).
# The built file is committed, so swagperf runs without the SDK installed.
set -e
cd "$(dirname "$0")"
SDK=${ANDROID_HOME:-$HOME/Library/Android/sdk}
JAR=$(ls -d "$SDK"/platforms/android-*/android.jar | tail -1)
D8=$(ls -d "$SDK"/build-tools/*/d8 | tail -1)
tmp=$(mktemp -d)
javac -source 8 -target 8 -nowarn -cp "$JAR" -d "$tmp" Labels.java
"$D8" --min-api 26 --output "$tmp" "$tmp/Labels.class"
cp "$tmp/classes.dex" labels.dex
rm -rf "$tmp"
echo "built $(pwd)/labels.dex"
