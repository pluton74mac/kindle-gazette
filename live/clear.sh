#!/bin/sh
# live-e-ink: clear the Kindle screen.
KINDLE="${KINDLE_HOST:?set KINDLE_HOST to the Kindle Tailscale IP or hostname}"
ssh "root@${KINDLE}" 'eips -c' 2>/dev/null
