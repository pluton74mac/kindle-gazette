#!/bin/sh
# live-e-ink: pixel-exact screenshot of the Kindle glass, pulled over SSH.
# Usage: screenshot.sh [out.png]
# Reads /dev/fb0 (8-bit gray, 1088-byte row stride, 1072x1448 visible) and
# decodes it with the repo venv's Pillow. Works whenever the CPU is awake —
# including the screensaver window — but not in deep suspend (tailscaled,
# and with it SSH, dies there).
set -e
KINDLE="${KINDLE_HOST:?set KINDLE_HOST to the Kindle Tailscale IP or hostname}"
OUT="${1:-kindle-shot-$(date +%Y%m%d-%H%M%S).png}"
DIR="$(cd "$(dirname "$0")" && pwd)"
PY="$DIR/../mcp_server/.venv/bin/python"
TMP="$(mktemp -t kindle-fb)"
trap 'rm -f "$TMP"' EXIT

ssh "root@${KINDLE}" 'dd if=/dev/fb0 2>/dev/null | gzip -c' | gunzip -c > "$TMP"

"$PY" - "$TMP" "$OUT" <<'EOF'
import sys
from PIL import Image
raw = open(sys.argv[1], "rb").read()
img = Image.frombytes("L", (1088, 1448), raw[: 1088 * 1448]).crop((0, 0, 1072, 1448))
img.save(sys.argv[2])
EOF

echo "saved: $OUT"
