#!/bin/bash
# Regenerate the symbolicate fixtures and metro-symbolicate's goldens.
#
#   tests/fixtures/sourcemaps/tools/regenerate.sh
#
# Needs Node, a C++ compiler, and the Swag Pay app with its JS dependencies
# and CocoaPods installed: hermes-engine's pod has hermesc and a macOS build
# of the Hermes VM. Overridable: APP_RN (the app's React Native package),
# HERMES_ENGINE (its Pods/hermes-engine), WORK (a scratch directory).
#
#  1. host.cpp is built against that VM: it runs a bytecode bundle under a
#     source URL and prints each error's `stack` exactly as Hermes formats it.
#  2. program/ is built twice, v1 and v2 (v2 turns on the `// @@V2` lines,
#     which move offsets and lines), the way React Native's release builds
#     do: react-native bundle --dev false --minify false, hermesc -O
#     -output-source-map, compose-source-maps.js. v1 is also compiled without
#     -output-source-map: Hermes then keeps its own debug info and prints
#     file:line:col positions in the bundle's JavaScript instead of offsets.
#  3. Swag Pay itself is bundled for iOS and Android with the commands its
#     Xcode phase and Gradle plugin run, and its bytecode is run with
#     probe.*.js, which call app modules by Metro module id with bad input.
#     The ids are the app's at the time of capture; after the app changes,
#     look them up again (assemble.py's comments say how they were found).
#  4. assemble.py writes the fixtures: paths made neutral, maps trimmed.
#  5. golden.js records metro-symbolicate's answers for all of it.
set -euo pipefail

TOOLS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIX="$(dirname "$TOOLS")"
APP_RN="${APP_RN:-$HOME/Documents/swag-pay/apps/mobile/react-native}"
HERMES_ENGINE="${HERMES_ENGINE:-$APP_RN/../iosApp/Pods/hermes-engine/destroot}"
WORK="${WORK:-$(mktemp -d)}"
NM="$APP_RN/node_modules"
HERMESC="$HERMES_ENGINE/bin/hermesc"
FRAMEWORKS="$HERMES_ENGINE/Library/Frameworks/macosx"
export RN_NODE_MODULES="$NM"
echo "work dir: $WORK"
mkdir -p "$WORK"

# 1. The host.
clang++ -std=c++20 -O1 -I"$HERMES_ENGINE/include" -F"$FRAMEWORKS" -framework hermesvm \
  -Wl,-rpath,"$FRAMEWORKS" "$TOOLS/host.cpp" -o "$WORK/host"

# react-native bundle, as both platforms' release builds run it under Hermes.
rn_bundle() {  # <project dir> <platform> <bundle out> <packager map out>
  local cfg="{\"root\":\"$1\",\"reactNativePath\":\"$NM/react-native\",\"platforms\":{\"ios\":{},\"android\":{}}}"
  local extra=()
  [[ -f "$1/metro.config.js" && "$1" != "$APP_RN" ]] && extra=(--config "$1/metro.config.js")
  (cd "$1" && node "$NM/react-native/scripts/bundle.js" bundle --load-config "$cfg" ${extra[@]+"${extra[@]}"} \
    --entry-file index.js --platform "$2" --dev false --reset-cache --bundle-output "$3" \
    --assets-dest "$(dirname "$3")/assets" --sourcemap-output "$4" --minify false >/dev/null)
}

# hermesc -O -output-source-map, then the composed map, as both builds do.
hermes_compose() {  # <js bundle> <bytecode out> <packager map> <composed map out>
  "$HERMESC" -emit-binary -max-diagnostic-width=80 -O -output-source-map -out "$2" "$1" 2>/dev/null
  node "$NM/react-native/scripts/compose-source-maps.js" "$3" "$2.map" -o "$4"
  rm "$2.map"
}

# 2. The test program.
for v in v1 v2; do
  rm -rf "$WORK/work/$v"; mkdir -p "$WORK/work/$v/out"
  cp -R "$FIX/program" "$WORK/work/$v/proj"
  mkdir -p "$WORK/work/$v/proj/node_modules"
  mv "$WORK/work/$v/proj/fake-lib" "$WORK/work/$v/proj/node_modules/fake-lib"
  for f in "$WORK/work/$v/proj/src/"*.ts; do
    if [[ $v == v2 ]]; then sed -i '' 's#^// @@V2 ##' "$f"; else sed -i '' '/^\/\/ @@V2 /d' "$f"; fi
  done
  if [[ $v == v1 ]]; then platform=android; name=index.android.bundle; else platform=ios; name=main.jsbundle; fi
  out="$WORK/work/$v/out"
  rn_bundle "$WORK/work/$v/proj" "$platform" "$out/$name.js" "$out/$name.packager.map"
  hermes_compose "$out/$name.js" "$out/$name" "$out/$name.packager.map" "$out/$name.composed.map"
  "$WORK/host" "$out/$name" "$name" > "$out/stacks.txt" || true
  if [[ $v == v1 ]]; then
    "$HERMESC" -emit-binary -max-diagnostic-width=80 -O -out "$out/$name.withdebug" "$out/$name.js" 2>/dev/null
    "$WORK/host" "$out/$name.withdebug" "$name" > "$out/stacks.withdebug.txt" || true
  fi
done

# 3. Swag Pay. iOS: react-native-xcode.sh names the packager map after
# SOURCEMAP_FILE and writes the JS bundle to the build products directory,
# whose path Hermes's own debug info then carries.
cp "$TOOLS/probe.ios.js" "$TOOLS/probe.android.js" "$WORK/"
mkdir -p "$WORK/ios/Release-iphonesimulator" "$WORK/android"
ios="$WORK/ios/Release-iphonesimulator/main.jsbundle"
rn_bundle "$APP_RN" ios "$ios" "$WORK/ios/Release-iphonesimulator/main.jsbundle.map"
cp "$WORK/ios/Release-iphonesimulator/main.jsbundle.map" "$WORK/ios/main.jsbundle.packager.map"
hermes_compose "$ios" "$WORK/ios/main.hbc" "$WORK/ios/main.jsbundle.packager.map" "$WORK/ios/main.composed.map"
"$WORK/host" "$WORK/ios/main.hbc" main.jsbundle "$WORK/probe.ios.js" > "$WORK/ios/stack.real.txt" || true
# The app's current Release build: no SOURCEMAP_FILE, so no -output-source-map.
"$HERMESC" -emit-binary -max-diagnostic-width=80 -O -out "$WORK/ios/main.withdebug.hbc" "$ios" 2>/dev/null
"$WORK/host" "$WORK/ios/main.withdebug.hbc" main.jsbundle "$WORK/probe.ios.js" > "$WORK/ios/stack.withdebug.txt" || true
# Android: the Gradle plugin's createBundleReleaseJsAndAssets, by hand.
android="$WORK/android/index.android.bundle.js"
rn_bundle "$APP_RN" android "$android" "$WORK/android/index.android.bundle.packager.map"
"$HERMESC" -w -emit-binary -max-diagnostic-width=80 -out "$WORK/android/index.android.bundle" "$android" -O -output-source-map
node "$NM/react-native/scripts/compose-source-maps.js" "$WORK/android/index.android.bundle.packager.map" \
  "$WORK/android/index.android.bundle.map" -o "$WORK/android/index.android.bundle.composed.map"
mv "$WORK/android/index.android.bundle.composed.map" "$WORK/android/index.android.bundle.map"
"$WORK/host" "$WORK/android/index.android.bundle" index.android.bundle "$WORK/probe.android.js" \
  > "$WORK/android/stack.real.txt" || true

# 4, 5.
python3 "$TOOLS/assemble.py" "$WORK" "$FIX"
node "$TOOLS/golden.js" "$NM/metro-symbolicate" "$FIX/spec.json" "$FIX/golden.json"
echo "fixtures written to $FIX"
