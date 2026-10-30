#!/usr/bin/env bash
# Fetches the shul's davening chart, bulletin and calendar now (the display also
# does this by itself on Friday afternoons).
cd "$(dirname "$0")" || exit 1
python3 server.py --update-shul
