#!/bin/sh
# Runs the app's unit tests in a booted simulator.
#
# `xcodebuild test` is the normal way. When it hangs before starting (it did on the Mac mini in
# Nov 2026, for every named simulator), this builds the tests for a generic simulator and runs
# them inside the app with XCTest's bundle injection instead.
#
#   ./run-tests.sh [simulator UDID]      default: the first booted iPad
set -e
cd "$(dirname "$0")"
SIM="${1:-$(xcrun simctl list devices booted | grep -m1 iPad | sed -E 's/.*\(([0-9A-F-]{36})\).*/\1/')}"
[ -n "$SIM" ] || { echo "Boot an iPad simulator first (or pass its UDID)."; exit 1; }
rm -rf build-sim
xcodebuild build-for-testing -project ShabbatDisplay.xcodeproj -scheme ShabbatDisplay \
  -destination 'generic/platform=iOS Simulator' -derivedDataPath build-sim CODE_SIGNING_ALLOWED=NO 2>&1 \
  | grep -E "error:|\*\* TEST BUILD" || true
APP="$PWD/build-sim/Build/Products/Debug-iphonesimulator/ShabbatDisplay.app"
[ -d "$APP/PlugIns/ShabbatDisplayTests.xctest" ] || { echo "The tests didn't build."; exit 1; }
PLAT="$(xcrun --sdk iphonesimulator --show-sdk-platform-path)"
xcrun simctl terminate "$SIM" com.avifrischlaw.shabbatdisplay 2>/dev/null || true
xcrun simctl install "$SIM" "$APP"
IN="$(xcrun simctl get_app_container "$SIM" com.avifrischlaw.shabbatdisplay app)"
LOG="$(mktemp)"
SIMCTL_CHILD_DYLD_INSERT_LIBRARIES="$PLAT/Developer/usr/lib/libXCTestBundleInject.dylib" \
SIMCTL_CHILD_XCInjectBundleInto="$IN/ShabbatDisplay" \
SIMCTL_CHILD_XCTestBundlePath="$IN/PlugIns/ShabbatDisplayTests.xctest" \
SIMCTL_CHILD_DYLD_FRAMEWORK_PATH="$PLAT/Developer/Library/Frameworks" \
SIMCTL_CHILD_DYLD_LIBRARY_PATH="$PLAT/Developer/usr/lib" \
xcrun simctl launch --console-pty "$SIM" com.avifrischlaw.shabbatdisplay -XCTest All > "$LOG" 2>&1 &
PID=$!
for _ in $(seq 1 60); do grep -q "Test Suite 'All tests' \(passed\|failed\)" "$LOG" && break; sleep 1; done
kill "$PID" 2>/dev/null || true
xcrun simctl terminate "$SIM" com.avifrischlaw.shabbatdisplay 2>/dev/null || true
grep -E "error:|failed|Test Suite 'All tests'" "$LOG" || true
grep -E "Executed [0-9]+ tests" "$LOG" | tail -1
grep -q "Test Suite 'All tests' passed" "$LOG"
