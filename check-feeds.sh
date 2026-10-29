#!/usr/bin/env bash
# Fetches every data source once and reports which ones work.
cd "$(dirname "$0")" || exit 1
python3 server.py --check
