#!/usr/bin/env bash
# Starts the Shabbat Display (data server + full-screen browser).
# Run it from the Pi's desktop; setup-pi.sh also makes it start at login.
HERE="$(cd "$(dirname "$0")" && pwd)"
nohup python3 "$HERE/launcher.pyw" >/dev/null 2>&1 &
