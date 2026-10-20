#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
exec python -m uvicorn control_api:app --host 127.0.0.1 --port 8787
