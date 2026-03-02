#!/bin/bash
# Start the Claude E-Ink Display app.
# Loads API key from script/.env if it exists, then launches the app.

cd "$(dirname "$0")/script"

# Load .env if present (ANTHROPIC_API_KEY, ESP32_IP, etc.)
if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "No API key found."
    echo "Either:"
    echo "  1. Create script/.env with:  ANTHROPIC_API_KEY=sk-ant-..."
    echo "  2. Or run:  export ANTHROPIC_API_KEY=sk-ant-..."
    exit 1
fi

PORT="${PORT:-8080}"
open "http://localhost:${PORT}" &
exec python3 app.py --ip "${ESP32_IP:-192.168.1.50}" --port "$PORT" --browser "$@"
