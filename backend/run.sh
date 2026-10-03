#!/usr/bin/env bash
# Sahayak v2 — run the Paytm-clone demo locally
#   ./run.sh            → http://localhost:8000
cd "$(dirname "$0")"
exec python3 -m uvicorn app:app --host 0.0.0.0 --port 8000
