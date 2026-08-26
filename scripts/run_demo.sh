#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT_DIR"
PYTHON_BIN="$ROOT_DIR/../.venv/bin/python"

if [ ! -f "$PYTHON_BIN" ]; then
    PYTHON_BIN="python3"
fi

echo "================================================================"
echo "🛡️  AEGIS-OPS: AUTONOMOUS SRE & PLATFORM CONTROL PLANE DEMO"
echo "================================================================"
echo "Starting AegisOps IDP Developer Portal & SRE Control Plane..."
echo "Portal URL: http://localhost:8005"
echo "================================================================"

exec "$PYTHON_BIN" "$ROOT_DIR/apps/idp-portal/server.py"
