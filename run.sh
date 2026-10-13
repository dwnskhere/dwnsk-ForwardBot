#!/usr/bin/env bash
set -euo pipefail
# ForwardBot is a worker. bot.py starts its own aiohttp endpoint; do not start Gunicorn here.
exec python3 -u bot.py
