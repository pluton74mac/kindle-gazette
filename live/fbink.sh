#!/bin/sh
# live-e-ink: run FBInk on the Kindle with the Mac-side args passed through.
# The device already ships FBInk 1.25.0 (bundled with the libkh jailbreak
# package) — nothing to install.
# Usage examples:
#   fbink.sh -c -f -W GC16 ""              # clear (note the "" — see README)
#   fbink.sh -W DU -m -y 4 -S 3 "BIG TEXT" # flash-free centered scaled text
#   fbink.sh -W DU -x 4 -y 10 "cell text"  # positioned like eips col/row
KINDLE="${KINDLE_HOST:?set KINDLE_HOST to the Kindle Tailscale IP or hostname}"
FB="${FBINK_BIN:-/mnt/us/libkh/bin/fbink}"
CMD="$FB -q"
for a in "$@"; do
    CMD="$CMD '$(printf %s "$a" | sed "s/'/'\\\\''/g")'"
done
exec ssh "root@${KINDLE}" "$CMD"
