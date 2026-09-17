#!/bin/sh
# Name: The Gazette
# Author: The Gazette Press
# Icon: /mnt/us/extensions/kindle-gazette/cover.png
#
# Scriptlet launcher — deploy to /mnt/us/documents/ (NOT extensions/).
# The Universal Hotfix indexes any .sh in documents/ as a "book"; tapping
# it runs the script with stdout piped to FBInk, so everything echoed here
# shows live on the glass. That gives us a one-tap launch from the library
# AND a visible boot log while the press spins up.
#
# Custom cover: add a "# Icon: /abs/path/to/cover.png" line above (or a
# base64 image) once the cover is designed.

GAZ_DIR="/mnt/us/extensions/kindle-gazette"
CACHE="/mnt/us/documents/kindle-gazette"
LOG="$CACHE/viewer.log"
PID_FILE="$CACHE/gazette.pid"
EIPS="/usr/sbin/eips"

echo "======  THE GAZETTE  ======"

# Hold the "book" open while the gazette runs. The moment this script
# exits, the framework closes the book and repaints the LIBRARY over the
# gazette (observed on hardware) — so we block, printing
# nothing, until the viewer's PID dies. The library then comes back
# exactly when the reader exits the paper.
hold_while_running() {
    while :; do
        pid=$(cat "$PID_FILE" 2>/dev/null)
        if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then
            break
        fi
        sleep 5
    done
}

# Already running? Don't double-start — just bring the front page back.
if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE" 2>/dev/null)" 2>/dev/null; then
    echo "The press is already running."
    echo "Redisplaying the front page..."
    sleep 1
    [ -f "$CACHE/home.png" ] && "$EIPS" -f -g "$CACHE/home.png" 2>/dev/null
    hold_while_running
    exit 0
fi

# One source of truth for the server URL: the KUAL menu entry's params.
SERVER=$(sed -n 's/.*"params"[[:space:]]*:[[:space:]]*"\(http[^"]*\)".*/\1/p' "$GAZ_DIR/menu.json" 2>/dev/null | head -1)
if [ -z "$SERVER" ]; then
    echo "No server URL in $GAZ_DIR/menu.json — set the Start entry's params."
    sleep 5
    exit 1
fi

echo "Server: $SERVER"
echo "Starting the press..."

# Start from a known log position so we only stream THIS boot's lines.
seen=$(wc -l < "$LOG" 2>/dev/null)
[ -z "$seen" ] && seen=0

nohup sh "$GAZ_DIR/bin/gazette.sh" "$SERVER" >/dev/null 2>&1 &

# Live boot log: stream the viewer's own log lines (its bracketed entries
# only — tailscaled noise filtered out) until the first page is painted,
# then exit SILENTLY: the gazette has just done a full-screen paint and any
# further echo would scribble text over the front page.
waited=0
while [ $waited -lt 90 ]; do
    total=$(wc -l < "$LOG" 2>/dev/null)
    [ -z "$total" ] && total=0
    if [ "$total" -gt "$seen" ]; then
        new_lines=$(tail -n +"$((seen + 1))" "$LOG" 2>/dev/null | grep '^\[')
        seen=$total
        if echo "$new_lines" | grep -q "Displayed:"; then
            # Front page is up — say nothing more, just hold the book open.
            hold_while_running
            exit 0
        fi
        [ -n "$new_lines" ] && echo "$new_lines"
    fi
    sleep 1
    waited=$((waited + 1))
done

echo "Still starting (slow network?) - the gazette will appear when ready."
hold_while_running
exit 0
