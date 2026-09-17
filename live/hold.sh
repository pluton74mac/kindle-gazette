#!/bin/sh
# live-e-ink: hold the Kindle awake while it's being used as a monitor.
# Usage: hold.sh on|off
# IMPORTANT: turn it off when done — leaving preventScreenSaver on breaks
# agent-gazette's sleep lifecycle (see kindle/bin/gazette.sh).
KINDLE="${KINDLE_HOST:?set KINDLE_HOST to the Kindle Tailscale IP or hostname}"
case "$1" in
    on)  VAL=1 ;;
    off) VAL=0 ;;
    *)   echo "usage: hold.sh on|off" >&2; exit 1 ;;
esac
ssh "root@${KINDLE}" "lipc-set-prop com.lab126.powerd preventScreenSaver $VAL"
echo "preventScreenSaver=$VAL"
