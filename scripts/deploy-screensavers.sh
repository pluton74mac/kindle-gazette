#!/bin/sh
# Install kindle/screensavers/bg_ss*.png as the linkss screensaver cycle.
# linkss shows them in filename order, advancing one per suspend.
# The previous set is backed up to /mnt/us/linkss/backups/ on the device.
set -e
KINDLE="${KINDLE_HOST:?set KINDLE_HOST to the Kindle Tailscale IP or hostname}"
cd "$(dirname "$0")/../kindle/screensavers"

ls bg_ss*.png >/dev/null

ssh "root@${KINDLE}" '
    ts=$(date +%Y%m%d-%H%M%S)
    mkdir -p "/mnt/us/linkss/backups/screensavers-$ts"
    cp /mnt/us/linkss/screensavers/*.png "/mnt/us/linkss/backups/screensavers-$ts/" 2>/dev/null || true
    rm -f /mnt/us/linkss/screensavers/*.png
    echo "backed up to backups/screensavers-$ts"
'
scp -q bg_ss*.png "root@${KINDLE}:/mnt/us/linkss/screensavers/"
# two upstart jobs race to bind-mount over /usr/share/blanket/screensaver
# (linkss.conf and an older screensaver job left on this device, which mounts
# /mnt/us/screensavers) — keep both sources identical so either winner shows
# the same set
ssh "root@${KINDLE}" 'rm -f /mnt/us/screensavers/*.png'
scp -q bg_ss*.png "root@${KINDLE}:/mnt/us/screensavers/"
ssh "root@${KINDLE}" 'ls /mnt/us/linkss/screensavers/ /mnt/us/screensavers/'
echo "deployed — next suspend shows the new set"
