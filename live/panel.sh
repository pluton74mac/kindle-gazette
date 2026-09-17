#!/bin/sh
# live-e-ink: live monitor panel loop — the Kindle as an at-a-glance display.
# Paints a clock plus Mac/Kindle status cells every INTERVAL seconds using
# FBInk's DU waveform (no flash). Holds the device awake while running and
# restores preventScreenSaver on exit (ctrl-c).
#
# Usage: panel.sh [max_ticks]      (max_ticks 0/omitted = run forever)
#   INTERVAL=30  seconds between updates
#   KINDLE_HOST, FBINK_BIN as in the other live/ scripts
set -u
KINDLE="${KINDLE_HOST:?set KINDLE_HOST to the Kindle Tailscale IP or hostname}"
FB="${FBINK_BIN:-/mnt/us/libkh/bin/fbink}"
INTERVAL="${INTERVAL:-30}"
TICKS="${1:-0}"

cleanup() {
    ssh -o ConnectTimeout=10 -o BatchMode=yes "root@${KINDLE}" \
        "lipc-set-prop com.lab126.powerd preventScreenSaver 0; \
         $FB -q -W DU -x 2 -y 24 -S 2 '$(printf '%-40s' "panel stopped -- device may sleep")'" \
        2>/dev/null
    echo "panel stopped, preventScreenSaver restored"
    exit 0
}
trap cleanup INT TERM

# One-time: hold awake, full clear, static title
ssh -o ConnectTimeout=10 -o BatchMode=yes "root@${KINDLE}" \
    "lipc-set-prop com.lab126.powerd preventScreenSaver 1 && $FB -q -c -f -W GC16 ''" \
    || { echo "kindle unreachable at $KINDLE" >&2; exit 1; }

echo "panel running (every ${INTERVAL}s, ctrl-c to stop)"
n=0
while :; do
    NOW=$(date "+%H:%M")
    DAY=$(date "+%a %d %b")
    TS=$(date "+%H:%M:%S")
    MACBATT=$(pmset -g batt 2>/dev/null | grep -Eo '[0-9]+%' | head -1)
    MACBATT=${MACBATT:-AC}
    LOAD=$(sysctl -n vm.loadavg | awk '{print $2}')
    DISK=$(df -g / | awk 'NR==2 {print $4}')
    # fixed-width cells so DU repaints fully cover the previous value
    L_MAC=$(printf '%-34s'  "mac:     batt $MACBATT   load $LOAD")
    L_DISK=$(printf '%-34s' "disk:    ${DISK}G free")
    L_FOOT=$(printf '%-40s' "updated $TS (every ${INTERVAL}s)")

    # single connection per tick; kindle-side data gathered in the same call
    if ! ssh -o ConnectTimeout=10 -o BatchMode=yes "root@${KINDLE}" 'sh -s' <<EOF
BATT=\$(lipc-get-prop com.lab126.powerd battLevel 2>/dev/null)
L_KDL=\$(printf '%-34s' "kindle:  batt \${BATT}%")
$FB -q -W DU -m -y 2  -S 6 "$NOW"
$FB -q -W DU -m -y 8  -S 3 "$DAY"
$FB -q -W DU -x 2 -y 12 -S 3 "$L_MAC"
$FB -q -W DU -x 2 -y 14 -S 3 "\$L_KDL"
$FB -q -W DU -x 2 -y 16 -S 3 "$L_DISK"
$FB -q -W DU -x 2 -y 24 -S 2 "$L_FOOT"
EOF
    then
        echo "tick failed (device unreachable?), retrying in ${INTERVAL}s" >&2
    fi

    n=$((n + 1))
    [ "$TICKS" -gt 0 ] && [ "$n" -ge "$TICKS" ] && cleanup
    sleep "$INTERVAL"
done
