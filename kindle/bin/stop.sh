#!/bin/sh
# Stop the Kindle Gazette viewer.
# Prefers the PID file written by gazette.sh — killall may not match the
# process comm reliably on busybox. Then sweeps stragglers by name.
PID_FILE="/mnt/us/documents/kindle-gazette/gazette.pid"

if [ -f "$PID_FILE" ]; then
    pid=$(cat "$PID_FILE" 2>/dev/null)
    if [ -n "$pid" ]; then
        kill "$pid" 2>/dev/null
        sleep 1
        if kill -0 "$pid" 2>/dev/null; then
            kill -9 "$pid" 2>/dev/null
        fi
    fi
    rm -f "$PID_FILE"
fi

# Secondary sweep by name (stale or missing PID file). Plain TERM first so
# gazette.sh's trap can clean up; -9 fallback after a grace period.
# touch_tap and lipc-wait-event must be killed too — the power watcher's
# lipc-wait-event survives otherwise.
killall gazette.sh 2>/dev/null
killall touch_tap 2>/dev/null
killall lipc-wait-event 2>/dev/null
sleep 1
killall -9 gazette.sh 2>/dev/null
killall -9 touch_tap 2>/dev/null
killall -9 lipc-wait-event 2>/dev/null

echo "Gazette stopped"
