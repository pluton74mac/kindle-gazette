#!/bin/sh
# kindle-gazette: bring Tailscale up at every boot. tailscaled has no boot
# hook of its own (it is started manually via KUAL), so a reboot used to cut
# off Tailscale SSH — the device's only remote path; there is no LAN sshd —
# until someone touched the device. Launched in the background by
# /mnt/us/linkss/bin/linkss at boot, the same vector as
# kill-ad-screensaver.sh.
#
# Proxy mode (SOCKS5/HTTP on localhost:1055) is deliberate: it is what
# gazette.sh's ensure_tailscale_proxy() health-checks and routes through,
# and it is a strict superset of standard userspace mode (inbound Tailscale
# SSH works in both). Node state persists in --statedir, so the daemon
# reconnects with its saved node key on its own; the `tailscale up --ssh`
# loop afterwards just re-asserts prefs and is non-fatal if it never
# confirms. WiFi can lag boot by minutes, hence the long retry budget.

BIN=/mnt/us/extensions/tailscale/bin
LOG=$BIN/tailscale_boot_log.txt
PIDFILE=/var/run/tailscale-boot.pid
PROXY_ADDR_FILE=$BIN/proxy.address

[ -x "$BIN/tailscaled" ] || exit 0

if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2> /dev/null ; then
    exit 0
fi
echo $$ > "$PIDFILE"

log() { echo "[$(date)] $*" >> "$LOG" ; }
echo "[$(date)] tailscale boot hook (via linkss)" > "$LOG"

# A daemon that is already running (KUAL start won the race, or gazette.sh
# restarted it) is left strictly alone: killing it would sever any live
# Tailscale SSH session, since the SSH server runs inside tailscaled itself.
if pidof tailscaled > /dev/null 2>&1 ; then
    log "tailscaled already running — leaving it alone"
else
    if [ -s "$PROXY_ADDR_FILE" ] ; then
        PROXY_ADDR=$(cat "$PROXY_ADDR_FILE")
    else
        PROXY_ADDR=localhost:1055
    fi
    rm -f /var/run/tailscale/tailscaled.sock
    log "starting tailscaled (proxy: $PROXY_ADDR)"
    nohup "$BIN/tailscaled" --statedir="$BIN/" -tun userspace-networking \
        --socks5-server="$PROXY_ADDR" \
        --outbound-http-proxy-listen="$PROXY_ADDR" >> "$LOG" 2>&1 &
fi

# Re-assert prefs once the daemon answers. Each attempt is bounded because
# `tailscale up` on a fresh/reset node prints a login URL and waits forever
# instead of failing; --ssh matches the KUAL start_tailscale.sh invocation
# exactly, so it never trips tailscale's "flags differ from last up" check.
n=0
while [ $n -lt 40 ] ; do
    if timeout 15 "$BIN/tailscale" up --ssh >> "$LOG" 2>&1 ; then
        log "tailscale up --ssh confirmed"
        rm -f "$PIDFILE"
        exit 0
    fi
    n=$((n + 1))
    sleep 15
done
log "tailscale up never confirmed — daemon left running (saved state usually reconnects on its own)"
rm -f "$PIDFILE"
