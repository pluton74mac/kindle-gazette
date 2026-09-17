#!/bin/sh
# live-e-ink: push a PNG from the Mac and paint it full-screen on the Kindle.
# Usage: push.sh <image.png>
# The image should be 1072x1448 grayscale (see README.md).
set -e
KINDLE="${KINDLE_HOST:?set KINDLE_HOST to the Kindle Tailscale IP or hostname}"
IMG="$1"
if [ ! -f "$IMG" ]; then
    echo "usage: push.sh <image.png>" >&2
    exit 1
fi
scp -q "$IMG" "root@${KINDLE}:/tmp/live-e-ink.png"
ssh "root@${KINDLE}" 'eips -f -g /tmp/live-e-ink.png' 2>/dev/null
echo "painted: $IMG"
