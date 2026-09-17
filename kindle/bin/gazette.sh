#!/bin/sh
# Kindle Gazette — Interactive Viewer
#
# Behaviour worth knowing (all hardware-verified on a Paperwhite 4):
#   - Wake repaints the cached view FIRST (~2-3s), then the network catches
#     up: one short health probe decides fetch-fresh vs cache+retry. Queued
#     sleep/wake pairs are collapsed; exit sweeps the lipc-wait-event pipeline.
#   - tailscaled is restarted only when the PROXY is down (curl rc=7), never
#     because the server is; offline navigation falls back to cached views.
#   - On ad-supported devices the "swipe to unlock" ad overlay is painted
#     over the wake repaint and cannot be swiped under the touch grab, so the
#     ad_screensaver module must stay unloaded — the linkss boot watchdog
#     owns that (see the comment before the FIFO setup below).
#   - PID file for stop.sh, trap cleanup on INT/TERM, bounded retry after a
#     failed fetch, optional auth token (extensions/kindle-gazette/token).
# Power button sleep/wake lifecycle via LIPC events.
# Uses awk for JSON parsing (no jq or python dependency).
#
# Architecture:
#   - Touch helper writes taps to TOUCH_FIFO (fd3)
#   - Power watcher creates flag files (SLEEP_FLAG / WAKE_FLAG)
#   - Main loop polls flag files + reads touch FIFO
#   - Touch helper is NEVER killed during sleep — it freezes and resumes
#     naturally. EVIOCGRAB on a frozen process doesn't block the Kindle
#     framework from handling swipe-to-unlock.
#
# Usage: gazette.sh [SERVER_URL]

SERVER="${1:-http://YOUR_SERVER_IP:8888}"
SCRIPT_DIR="/mnt/us/extensions/kindle-gazette/bin"
CACHE_DIR="/mnt/us/documents/kindle-gazette"
LOG_FILE="/mnt/us/documents/kindle-gazette/viewer.log"
TOUCH_HELPER="${SCRIPT_DIR}/touch_tap"
SCREEN_W=1072
SCREEN_H=1448
SLEEP_FLAG="${CACHE_DIR}/.sleep_flag"
WAKE_FLAG="${CACHE_DIR}/.wake_flag"
PID_FILE="${CACHE_DIR}/gazette.pid"
TAILSCALED_BIN="/mnt/us/extensions/tailscale/bin/tailscaled"
TAILSCALED_STATEDIR="/mnt/us/extensions/tailscale/bin/"
TAILSCALE_PROXY="localhost:1055"
CURL_PROXY_ARGS=""
TOKEN_FILE="${SCRIPT_DIR}/../token"
GAZETTE_TOKEN=""
CURL_AUTH_ARGS=""

mkdir -p "$CACHE_DIR"

log() {
    echo "[$(date '+%H:%M:%S')] $1" >> "$LOG_FILE" 2>&1
}

# Optional auth token: first line of extensions/kindle-gazette/token.
# CURL_AUTH_ARGS is word-split into curl args (same pattern as
# CURL_PROXY_ARGS) — no quotes inside the value, and the header value must
# contain no whitespace so the split yields exactly two argv entries.
if [ -s "$TOKEN_FILE" ]; then
    read -r GAZETTE_TOKEN < "$TOKEN_FILE"
    if [ -n "$GAZETTE_TOKEN" ]; then
        token_stripped=$(printf '%s' "$GAZETTE_TOKEN" | tr -d ' \t\r')
        if [ "$token_stripped" = "$GAZETTE_TOKEN" ]; then
            CURL_AUTH_ARGS="-H X-Gazette-Token:$GAZETTE_TOKEN"
            log "Auth token loaded from $TOKEN_FILE"
        else
            log "WARNING: token file contains whitespace — ignoring it"
            GAZETTE_TOKEN=""
        fi
    fi
fi

# Parse a JSON string field using grep/sed
json_str() {
    grep -o "\"$2\"[[:space:]]*:[[:space:]]*\"[^\"]*\"" "$1" 2>/dev/null | head -1 | sed "s/.*\"$2\"[[:space:]]*:[[:space:]]*\"//;s/\"$//"
}

# Parse a JSON number field using grep/sed
json_num() {
    grep -o "\"$2\"[[:space:]]*:[[:space:]]*[0-9]*" "$1" 2>/dev/null | head -1 | sed "s/.*:[[:space:]]*//"
}

# ── Tailscale (optional) ──
# If a Tailscale extension is installed (SOCKS5/HTTP proxy mode), start it and
# route curl through the local proxy. This lets SERVER be a Tailscale IP
# (100.x.x.x) that works both on the home LAN and away from it — Tailscale
# picks a direct path when possible, falling back to its DERP relay otherwise.
# Kernel TUN networking is NOT used here: confirmed unavailable on this
# PW4/FW5.16.7 build ("tailscaled failed — kernel TUN may not be supported"),
# so userspace-networking + an explicit proxy is the only path that works.
# If the Tailscale extension isn't installed, this is skipped entirely and
# curl falls back to plain LAN-only requests — Tailscale is purely additive.
ensure_tailscale_proxy() {
    if [ ! -x "$TAILSCALED_BIN" ]; then
        log "Tailscale not installed — LAN-only mode"
        return 1
    fi

    # If a tailscaled proxy is already up, don't bounce it. Restarting kills
    # any active Tailscale SSH session (the SSH server runs inside tailscaled
    # itself) and leaves a cold proxy that turns every fetch into a 30s
    # timeout for minutes. Judge the PROXY by curl's exit code, not the
    # server: 7 = couldn't connect to the proxy itself → restart it;
    # anything else (0 = all fine; 22 = proxy answered 502, server down;
    # 28 = tailnet still connecting) means the proxy is alive — keep it.
    # Conflating "server down" with "proxy down" makes every KUAL start
    # with the server stopped take ~60s.
    curl -fsS --connect-timeout 2 --max-time 3 --proxy "http://${TAILSCALE_PROXY}" $CURL_AUTH_ARGS "${SERVER}/health" >/dev/null 2>&1
    proxy_rc=$?
    if [ $proxy_rc -eq 0 ]; then
        CURL_PROXY_ARGS="--proxy http://${TAILSCALE_PROXY}"
        log "Tailscale proxy already up at ${TAILSCALE_PROXY} (server reachable)"
        return 0
    fi
    if [ $proxy_rc -ne 7 ]; then
        CURL_PROXY_ARGS="--proxy http://${TAILSCALE_PROXY}"
        log "Tailscale proxy already up at ${TAILSCALE_PROXY} (server not reachable, curl rc=$proxy_rc) — keeping proxy"
        return 0
    fi

    log "Starting tailscaled (proxy mode) for Tailscale connectivity..."
    pkill tailscaled 2>/dev/null
    sleep 2
    rm -f /var/run/tailscale/tailscaled.sock

    nohup "$TAILSCALED_BIN" --statedir="$TAILSCALED_STATEDIR" -tun userspace-networking \
        --socks5-server="$TAILSCALE_PROXY" \
        --outbound-http-proxy-listen="$TAILSCALE_PROXY" >> "$LOG_FILE" 2>&1 &

    sleep 3
    CURL_PROXY_ARGS="--proxy http://${TAILSCALE_PROXY}"

    # tailscaled needs real time to reach the control plane and connect to a
    # DERP relay before the proxy can actually route anywhere — observed ~20s
    # from cold start. Give it a bounded head start rather than either
    # guessing with a fixed sleep (too short = first fetch fails) or waiting
    # for full readiness (too long = touch_tap holds its EVIOCGRAB grab with
    # nothing yet watching SLEEP_FLAG, so a screen-timeout mid-wait leaves
    # swipe-to-unlock broken — confirmed on hardware). The
    # normal fetch fallback (cached image) plus the next tap's retry already
    # cover a still-cold tailnet, so this only needs to catch the common case.
    log "Waiting for Tailscale to connect..."
    start_ts=$(date +%s)
    waited=0
    while [ $waited -lt 6 ]; do
        if curl -fsS --connect-timeout 2 --max-time 3 $CURL_PROXY_ARGS $CURL_AUTH_ARGS "${SERVER}/health" >/dev/null 2>&1; then
            log "Tailscale proxy ready at ${TAILSCALE_PROXY} (connected after $(($(date +%s) - start_ts))s)"
            return 0
        fi
        sleep 2
        waited=$((waited + 2))
    done
    log "Tailscale proxy started but server not reachable after ${waited}s — continuing anyway (cached view / next tap will retry)"
}

# Fetch a view from the server
fetch_view() {
    path="$1"
    url="${SERVER}/view?path=${path}"
    img_name=$(echo "$path" | tr '/' '_')
    json_tmp="${CACHE_DIR}/${img_name}.json.tmp"
    png_tmp="${CACHE_DIR}/${img_name}.png.tmp"
    json_file="${CACHE_DIR}/${img_name}.json"
    png_file="${CACHE_DIR}/${img_name}.png"

    log "Fetching: $url"

    curl -fsSL --connect-timeout 10 --max-time 30 $CURL_PROXY_ARGS $CURL_AUTH_ARGS "$url" -o "$json_tmp" 2>>"$LOG_FILE"
    if [ $? -ne 0 ]; then
        log "ERROR: Failed to fetch JSON"
        return 1
    fi

    image_path=$(json_str "$json_tmp" "image")
    refresh_sec=$(json_num "$json_tmp" "refresh_sec")
    back_path=$(json_str "$json_tmp" "back")

    if [ -z "$image_path" ]; then
        log "ERROR: No image path in JSON"
        return 1
    fi

    img_url="${SERVER}${image_path}"
    log "Fetching image: $img_url"
    curl -fsSL --connect-timeout 10 --max-time 30 $CURL_PROXY_ARGS $CURL_AUTH_ARGS "$img_url" -o "$png_tmp" 2>>"$LOG_FILE"
    if [ $? -ne 0 ]; then
        log "ERROR: Failed to fetch PNG"
        return 1
    fi

    # Record whether the image actually changed — the wake path uses this to
    # skip a redundant full-screen e-ink flash. cmp missing/failing counts
    # as "changed" (safe: at worst an extra flash).
    if cmp -s "$png_tmp" "$png_file" 2>/dev/null; then
        FETCH_CHANGED=0
    else
        FETCH_CHANGED=1
    fi

    mv "$json_tmp" "$json_file"
    mv "$png_tmp" "$png_file"

    CURRENT_PNG="$png_file"
    CURRENT_JSON="$json_file"
    CURRENT_PATH="$path"
    CURRENT_BACK="${back_path:-home}"
    CURRENT_REFRESH="${refresh_sec:-3600}"

    log "OK: view=$path png=$png_file refresh=${refresh_sec}s"
    return 0
}

# Load a view from the on-device cache (no network) — same naming scheme as
# fetch_view. Sets CURRENT_* so the tap map, BACK and refresh keep working
# offline. Used as the navigation fallback when the server is unreachable:
# the article PNGs and tap maps of every previously fetched view are already
# on disk, so the paper stays browsable with the press offline.
load_cached_view() {
    path="$1"
    img_name=$(echo "$path" | tr '/' '_')
    json_file="${CACHE_DIR}/${img_name}.json"
    png_file="${CACHE_DIR}/${img_name}.png"

    if [ ! -f "$json_file" ] || [ ! -f "$png_file" ]; then
        return 1
    fi

    back_path=$(json_str "$json_file" "back")
    refresh_sec=$(json_num "$json_file" "refresh_sec")

    CURRENT_PNG="$png_file"
    CURRENT_JSON="$json_file"
    CURRENT_PATH="$path"
    CURRENT_BACK="${back_path:-home}"
    CURRENT_REFRESH="${refresh_sec:-3600}"
    return 0
}

# Display current PNG
display_view() {
    if [ -z "$CURRENT_PNG" ] || [ ! -f "$CURRENT_PNG" ]; then
        log "ERROR: No PNG to display"
        return 1
    fi
    eips -f -g "$CURRENT_PNG" 2>>"$LOG_FILE"
    log "Displayed: $CURRENT_PNG"
}

# Hit test: check if (x,y) matches any tap region
# Output: "action target" on stdout if hit, empty if no hit
hit_test() {
    tx=$1
    ty=$2

    if [ -z "$CURRENT_JSON" ] || [ ! -f "$CURRENT_JSON" ]; then
        return 1
    fi

    # First try direct coordinates
    result=$(awk -v tx="$tx" -v ty="$ty" '
    BEGIN { x=y=w=h=act=tgt="" }
    /"x"/ { gsub(/.*"x"[[:space:]]*:[[:space:]]*/, ""); gsub(/[^0-9-].*/, ""); x=$0 }
    /"y"/ { gsub(/.*"y"[[:space:]]*:[[:space:]]*/, ""); gsub(/[^0-9-].*/, ""); y=$0 }
    /"w"/ { gsub(/.*"w"[[:space:]]*:[[:space:]]*/, ""); gsub(/[^0-9-].*/, ""); w=$0 }
    /"h"/ { gsub(/.*"h"[[:space:]]*:[[:space:]]*/, ""); gsub(/[^0-9-].*/, ""); h=$0 }
    /"action"/ { gsub(/.*"action"[[:space:]]*:[[:space:]]*"/, ""); gsub(/".*/, ""); act=$0 }
    /"target"/ { gsub(/.*"target"[[:space:]]*:[[:space:]]*"/, ""); gsub(/".*/, ""); tgt=$0 }
    /}/ && x != "" {
        if (tx+0 >= x+0 && tx+0 < x+0+w+0 && ty+0 >= y+0 && ty+0 < y+0+h+0) {
            print act " " tgt
            exit 0
        }
        x=y=w=h=act=tgt=""
    }
    ' "$CURRENT_JSON" 2>/dev/null)

    if [ -n "$result" ]; then
        echo "$result"
        return 0
    fi

    return 1
}

show_error() {
    msg="$1"
    log "ERROR: $msg"
    eips -c 2>/dev/null
    eips 1 2 "E-INK GAZETTE" 2>/dev/null
    eips 1 4 "Error: $msg" 2>/dev/null
    eips 1 6 "Server: $SERVER" 2>/dev/null
}

# ── Power lifecycle ──

# Start touch helper — writes "x y" taps to the touch FIFO
start_touch_helper() {
    if [ -x "$TOUCH_HELPER" ]; then
        "$TOUCH_HELPER" > "$TOUCH_FIFO" 2>>"$LOG_FILE" &
        TOUCH_PID=$!
        log "Touch helper started (PID=$TOUCH_PID)"
    else
        log "ERROR: touch_tap not found at $TOUCH_HELPER"
        TOUCH_PID=""
    fi
}

# Start power event watcher — creates flag files on sleep/wake events.
# Uses lipc-wait-event with -m (multievent, don't exit after first event).
# Event names MUST be comma-separated.
# The watcher creates SLEEP_FLAG or WAKE_FLAG files — the main loop polls these.
# This avoids any FIFO sharing/corruption issues.
start_power_watcher() {
    rm -f "$SLEEP_FLAG" "$WAKE_FLAG"
    (
        while true; do
            log "Power watcher: launching lipc-wait-event"
            lipc-wait-event -m com.lab126.powerd goingToScreenSaver,outOfScreenSaver 2>>"$LOG_FILE" | while read -r line; do
                log "Power event: $line"
                case "$line" in
                    *goingToScreenSaver*) touch "$SLEEP_FLAG" 2>/dev/null ;;
                    *outOfScreenSaver*)   touch "$WAKE_FLAG" 2>/dev/null ;;
                esac
            done
            log "Power watcher: lipc-wait-event exited, restarting in 1s"
            sleep 1
        done
    ) &
    POWER_WATCHER_PID=$!
    log "Power watcher started (PID=$POWER_WATCHER_PID)"
}


# Handle sleep — called when SLEEP_FLAG is detected by the main loop.
# Clears the screen, waits for wake, then fetches home and displays.
# Does NOT kill the touch helper — it freezes and resumes with the device.
# A frozen touch_tap can't read events, so the Kindle framework handles
# swipe-to-unlock naturally. This is the behavior that worked before.
handle_sleep() {
    log "=== SLEEP: entering sleep mode ==="
    rm -f "$SLEEP_FLAG"

    # Clear the screen so the dashboard image doesn't ghost through the screensaver.
    eips -c 2>/dev/null

    log "Kindle will sleep naturally (screensaver → deep sleep)"
    log "Waiting for wake (flag file or time-gap detection)..."

    # Wait for wake.
    # Two detection mechanisms:
    #   a) WAKE_FLAG file created by power watcher (outOfScreenSaver event)
    #   b) Time-gap: sleep 2 takes much longer than 2s → device was suspended
    #
    # During deep sleep, the shell process freezes mid-sleep.
    # When it resumes, the time gap tells us we slept.
    while true; do
        if [ -f "$WAKE_FLAG" ]; then
            rm -f "$WAKE_FLAG"
            log "Wake flag detected (outOfScreenSaver)"
            break
        fi
        before=$(date +%s)
        sleep 1
        after=$(date +%s)
        gap=$((after - before))
        if [ "$gap" -gt 10 ]; then
            log "Time gap ${gap}s >> 2s — woke from deep sleep"
            # Clean up any wake flag that might have been set
            rm -f "$WAKE_FLAG" 2>/dev/null
            break
        fi
    done

    # ── WAKE ──
    log "=== WAKE: Resuming gazette ==="

    # Repaint the cached view FIRST — before any network work — so the glass
    # responds to the unlock swipe in ~2-3s. A tap made while the screen is
    # still dead is simply lost (that latency is what makes Exit feel like it
    # needs two taps: the first lands mid-wake). The network catches up
    # below; the old order (poll + fetch
    # before the first repaint) froze the glass on the lock image for
    # minutes whenever the server/proxy was unreachable.
    display_view
    wake_shown_path="$CURRENT_PATH"

    # Drain phantom taps from the swipe-to-unlock gesture.
    # touch_tap was frozen during sleep — it resumes with the device and
    # reads buffered swipe-to-unlock events, reporting the final release
    # point as a tap. Flush these for 2 seconds before accepting real input.
    log "Draining phantom taps (swipe-to-unlock residue)..."
    drain_until=$(($(date +%s) + 2))
    while [ "$(date +%s)" -lt "$drain_until" ]; do
        if read -r -t 1 drain_line <&3 2>/dev/null; then
            log "Drained: $drain_line"
        fi
    done
    log "Drain complete — accepting touch input"

    # Collapse a lock/unlock pair queued while this wake was processing —
    # replaying it would just repaint and drain again for nothing. A lone
    # SLEEP_FLAG (device really is asleep again) is left for the main loop.
    if [ -f "$SLEEP_FLAG" ] && [ -f "$WAKE_FLAG" ]; then
        log "Collapsing queued sleep/wake pair"
        rm -f "$SLEEP_FLAG" "$WAKE_FLAG"
    fi

    # Now the network: one short reachability probe decides the path. WiFi
    # reconnect can take 5-15s, so a failed probe is common even at home —
    # the retry loop fetches fresh home as soon as the network is back; the
    # cached view already on the glass covers the meantime. Taps made during
    # this probe/fetch window are buffered and processed right after.
    if curl -fsS --connect-timeout 2 --max-time 3 $CURL_PROXY_ARGS $CURL_AUTH_ARGS "${SERVER}/health" >/dev/null 2>&1; then
        log "Server reachable at wake — fetching home view..."
        if fetch_view "home"; then
            last_refresh=$(date +%s)
            RETRY_AT=0
            RETRY_COUNT=0
            # Skip the second full-screen flash if the glass already shows
            # exactly this image (cached home == fresh home, the usual case).
            if [ "$wake_shown_path" != "home" ] || [ "$FETCH_CHANGED" = "1" ]; then
                display_view
                log "Home view displayed after wake"
            else
                log "Home view unchanged after wake — repaint skipped"
            fi
        else
            log "Fetch failed after wake — keeping cached view, retry armed"
            RETRY_AT=$(($(date +%s) + 15))
            RETRY_COUNT=0
        fi
    else
        log "Server not reachable at wake — keeping cached view, retry armed"
        RETRY_AT=$(($(date +%s) + 10))
        RETRY_COUNT=0
    fi
}

# Cleanup on SIGINT/SIGTERM — kills children, closes fd3, removes
# FIFO/flag/PID files. Without it, SIGTERM orphans everything.
cleanup() {
    [ -n "$TOUCH_PID" ] && kill $TOUCH_PID 2>/dev/null
    [ -n "$POWER_WATCHER_PID" ] && kill $POWER_WATCHER_PID 2>/dev/null
    # Killing the watcher subshell does NOT kill its lipc-wait-event
    # pipeline — power events kept being logged after "Viewer exited
    # cleanly". Sweep it like stop.sh does.
    killall lipc-wait-event 2>/dev/null
    exec 3<&- 2>/dev/null
    rm -f "$TOUCH_FIFO" "$SLEEP_FLAG" "$WAKE_FLAG" "$PID_FILE" 2>/dev/null
    log "Viewer stopped by signal"
    exit 0
}

# ── Main ──

log "=== Kindle Gazette Interactive Viewer v6.2 ==="
log "Server: $SERVER"
echo $$ > "$PID_FILE"
trap cleanup INT TERM

# Kill any leftover processes from previous sessions
killall touch_tap 2>/dev/null
killall lipc-wait-event 2>/dev/null

# Ad screensaver (Special Offers): kept unloaded device-wide by the linkss
# boot watchdog (kindle/linkss/kill-ad-screensaver.sh), which evicts the
# module on every reload. Without it, the "SWIPE TO UNLOCK" ad overlay
# paints over our wake repaint and its swipe is dead under touch_tap's
# EVIOCGRAB (hardware-confirmed) — so if that watchdog is ever disabled,
# restore the unload call here:
#   lipc-set-prop com.lab126.blanket unload ad_screensaver

# Create touch FIFO (ONLY touch helper writes to it — no power watcher)
TOUCH_FIFO="${CACHE_DIR}/touch_fifo"
rm -f "$TOUCH_FIFO"
mkfifo "$TOUCH_FIFO" 2>/dev/null

# Start touch helper and power watcher
start_touch_helper
start_power_watcher
ensure_tailscale_proxy

log "Waiting 3s for WiFi..."
sleep 3

# Initial fetch
CURRENT_PATH="home"
CURRENT_JSON=""
CURRENT_PNG=""
RETRY_AT=0
RETRY_COUNT=0
FETCH_CHANGED=1
if ! fetch_view "home"; then
    show_error "Cannot reach server"
    if [ -f "${CACHE_DIR}/home.png" ]; then
        eips -f -g "${CACHE_DIR}/home.png" 2>/dev/null
        log "Using cached home.png"
        CURRENT_PNG="${CACHE_DIR}/home.png"
        CURRENT_JSON="${CACHE_DIR}/home.json"
    fi
    RETRY_AT=$(($(date +%s) + 15))
    RETRY_COUNT=0
fi
display_view

# Main interaction loop
# fd3 reads from the touch FIFO (touch taps only — no power events mixed in).
# Power events are detected via flag file polling.
log "Entering interaction loop"
exec 3< "$TOUCH_FIFO"
last_refresh=$(date +%s)

while true; do
    # Check for sleep flag (power button pressed)
    if [ -f "$SLEEP_FLAG" ]; then
        handle_sleep
        continue
    fi

    # Read from touch FIFO (1 second timeout for auto-refresh tick)
    tap_line=""
    if read -r -t 1 tap_line <&3 2>/dev/null; then
        # Only process lines that look like touch coordinates (start with digit)
        case "$tap_line" in
            [0-9]*)
                if [ -n "$tap_line" ]; then
                    tx=$(echo "$tap_line" | awk '{print $1}')
                    ty=$(echo "$tap_line" | awk '{print $2}')
                    log "Tap: ($tx,$ty)"

                    # Hit test
                    hit_result=$(hit_test "$tx" "$ty")
                    if [ -n "$hit_result" ]; then
                        tap_action=$(echo "$hit_result" | awk '{print $1}')
                        tap_target=$(echo "$hit_result" | awk '{print $2}')
                        log "HIT: $tap_action -> $tap_target"

                        if [ "$tap_action" = "navigate" ] && [ -n "$tap_target" ]; then
                            if fetch_view "$tap_target"; then
                                display_view
                                last_refresh=$(date +%s)
                            elif load_cached_view "$tap_target"; then
                                log "Offline: showing cached $tap_target"
                                display_view
                                last_refresh=$(date +%s)
                            else
                                log "Failed to fetch $tap_target (no cached copy)"
                            fi
                        elif [ "$tap_action" = "refresh" ]; then
                            if fetch_view "$CURRENT_PATH"; then
                                display_view
                                last_refresh=$(date +%s)
                            fi
                        elif [ "$tap_action" = "exit" ]; then
                            log "Exit requested — cleaning up and stopping"
                            exec 3<&-
                            kill $TOUCH_PID 2>/dev/null
                            kill $POWER_WATCHER_PID 2>/dev/null
                            # The lipc-wait-event pipeline survives the
                            # subshell kill — sweep it (see cleanup()).
                            killall lipc-wait-event 2>/dev/null
                            rm -f "$TOUCH_FIFO" "$SLEEP_FLAG" "$WAKE_FLAG" "$PID_FILE"
                            # Return to Kindle home screen
                            lipc-set-prop com.lab126.appmgrd start app://com.lab126.booklet.home 2>/dev/null
                            log "Viewer exited cleanly"
                            exit 0
                        fi
                    else
                        log "No hit at ($tx,$ty)"
                    fi
                fi
                ;;
            *)
                # Not a touch coordinate — log and ignore
                log "Ignoring non-touch line: $tap_line"
                ;;
        esac
    fi

    # Auto-refresh
    now=$(date +%s)
    elapsed=$((now - last_refresh))
    if [ -n "$CURRENT_REFRESH" ] && [ "$CURRENT_REFRESH" -gt 0 ] && [ "$elapsed" -ge "$CURRENT_REFRESH" ]; then
        log "Auto-refresh (${elapsed}s >= ${CURRENT_REFRESH}s)"
        if fetch_view "$CURRENT_PATH"; then
            display_view
        fi
        last_refresh=$(date +%s)
    fi

    # Retry after a failed fetch left stale content on screen.
    # Armed (RETRY_AT != 0) by the initial-startup and post-wake failure
    # branches; backs off to 30s steps, gives up after 10 straight failures.
    if [ "$RETRY_AT" -ne 0 ] && [ "$now" -ge "$RETRY_AT" ]; then
        if fetch_view "$CURRENT_PATH"; then
            display_view
            last_refresh=$(date +%s)
            RETRY_AT=0
            RETRY_COUNT=0
            log "Retry succeeded"
        else
            RETRY_COUNT=$((RETRY_COUNT + 1))
            if [ "$RETRY_COUNT" -ge 10 ]; then
                RETRY_AT=0
                RETRY_COUNT=0
                log "Giving up retries until next interaction"
            else
                RETRY_AT=$(($(date +%s) + 30))
            fi
        fi
    fi
done

# Cleanup (unreachable — loop is infinite, exit via tap action)
exec 3<&-
kill $TOUCH_PID 2>/dev/null
kill $POWER_WATCHER_PID 2>/dev/null
rm -f "$TOUCH_FIFO" "$SLEEP_FLAG" "$WAKE_FLAG" "$PID_FILE"
log "Viewer stopped"
