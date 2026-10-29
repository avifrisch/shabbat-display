#!/usr/bin/env bash
# Stops the Shabbat Display: the launcher, the data server and the full-screen browser.
HERE="$(cd "$(dirname "$0")" && pwd)"
pkill -f "$HERE/launcher.pyw"
pkill -f "$HERE/server.py"
pkill -f "$HERE/browser-profile"
echo "Shabbat Display stopped."
