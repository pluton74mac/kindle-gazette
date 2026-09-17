#!/bin/sh
# kindle-gazette: this is an ad-supported (Special Offers) device. Blanket's
# ad_screensaver module owns the glass whenever it is loaded, and the ad
# framework (dtcp/adManager) loads it a few minutes into boot — long after
# any fixed startup window — so a timed swap loses (proven by a reboot test: the
# module came up ~4 min after boot and served ads). This script is a tiny
# watchdog instead: it evicts ad_screensaver immediately, then blocks on
# blanket's moduleLoaded events and evicts it again whenever anything
# reloads it. Launched in the background by bin/linkss at every boot;
# lipc-wait-event sleeps in the kernel between events, so it costs nothing.

PIDFILE=/var/run/kill-ad-screensaver.pid
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2> /dev/null ; then
    exit 0
fi
echo $$ > "$PIDFILE"

# wait for blanket's lipc service to come up
while ! lipc-probe com.lab126.blanket > /dev/null 2>&1 ; do
    sleep 5
done

swap() {
    lipc-set-prop com.lab126.blanket unload ad_screensaver 2> /dev/null
    lipc-set-prop com.lab126.blanket load screensaver 2> /dev/null
}

# evict it if it beat us here, then again on every reload
swap
lipc-wait-event -m com.lab126.blanket moduleLoaded | while read -r line ; do
    case "$line" in
        *ad_screensaver*)
            sleep 1
            swap
            ;;
    esac
done
