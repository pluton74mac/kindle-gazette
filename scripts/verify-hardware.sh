#!/bin/bash
# verify-hardware.sh — deploy the Kindle-side files over Tailscale SSH and
# guide the on-device verification of the v5 changes (see kindle/README.md).
#
# Run from the repo root ON A MACHINE THAT IS ON YOUR TAILNET (not inside a
# sandbox). Requires: tailscale up on this machine, the Kindle joined to the
# tailnet with its Tailscale extension running (`tailscale up --ssh` on the
# device gives passwordless root SSH).
#
# Usage:
#   ./scripts/verify-hardware.sh deploy <kindle-addr> [server-url]
#       Deploys kindle/ to /mnt/us/extensions/kindle-gazette on the device
#       (other extensions are left untouched), sets the server URL in
#       menu.json, clears stale cache. server-url defaults
#       to http://<this machine's tailscale IPv4>:8888.
#   ./scripts/verify-hardware.sh logs <kindle-addr>
#       Live-tails the viewer log on the device.
#   ./scripts/verify-hardware.sh status <kindle-addr>
#       Shows gazette-related processes + last log lines.
#   ./scripts/verify-hardware.sh rollback <kindle-addr>
#       Removes the kindle-gazette extension dir (nothing else is touched).
#
# SSH: uses `ssh root@<addr>` by default; export SSH_CMD="tailscale ssh" to
# route through the tailscale CLI instead.

set -euo pipefail

CMD="${1:-}"
KINDLE="${2:-}"
SSH_CMD="${SSH_CMD:-ssh}"
EXT_DIR="/mnt/us/extensions/kindle-gazette"
CACHE_DIR="/mnt/us/documents/kindle-gazette"

die() { echo "error: $*" >&2; exit 1; }

[ -n "$CMD" ] && [ -n "$KINDLE" ] || {
    sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'
    exit 1
}
[ -d kindle/bin ] || die "run from the repo root (kindle/bin not found)"

kssh() { $SSH_CMD -o ConnectTimeout=8 "root@${KINDLE}" "$@"; }

case "$CMD" in
deploy)
    SERVER_URL="${3:-}"
    if [ -z "$SERVER_URL" ]; then
        MY_IP="$(tailscale ip -4 2>/dev/null | head -1 || true)"
        [ -n "$MY_IP" ] || die "no server-url given and 'tailscale ip -4' failed — pass it explicitly"
        SERVER_URL="http://${MY_IP}:8888"
    fi
    echo "==> Checking SSH to the Kindle (${KINDLE})..."
    kssh true || die "cannot SSH to root@${KINDLE} — is the Tailscale extension running on the Kindle? Try SSH_CMD='tailscale ssh'"

    echo "==> Deploying kindle/ -> ${EXT_DIR} (server: ${SERVER_URL})"
    # tar-over-ssh: works regardless of scp/sftp support in the device's SSH
    # server, and busybox tar is always present on the Kindle.
    tar -C kindle --exclude '._*' --exclude '.DS_Store' -cf - . | \
        kssh "mkdir -p '${EXT_DIR}' && tar -C '${EXT_DIR}' -xf - && chmod +x '${EXT_DIR}'/bin/*"

    # Point menu.json at the server (replaces the placeholder or any old URL).
    kssh "sed -i 's|http://YOUR_SERVER_IP:8888|${SERVER_URL}|g; s|\"params\": \"http://[^\"]*\"|\"params\": \"${SERVER_URL}\"|g' '${EXT_DIR}/menu.json'"

    # Stale cache from a previous session can mask a broken fetch — clear it
    # so the first render we see is provably fresh.
    kssh "rm -rf '${CACHE_DIR}'; mkdir -p '${CACHE_DIR}'"

    echo "==> Deployed. On-device sanity:"
    kssh "ls -l '${EXT_DIR}/bin' && grep -o 'http://[^\"]*' '${EXT_DIR}/menu.json' | head -1"
    echo
    echo "Next: restart KUAL on the device, then walk the checklist"
    echo "(./scripts/verify-hardware.sh prints it via: $0 checklist ${KINDLE})"
    ;;
logs)
    echo "==> Tailing ${CACHE_DIR}/viewer.log (Ctrl-C to stop)"
    kssh "touch '${CACHE_DIR}/viewer.log'; tail -f '${CACHE_DIR}/viewer.log'"
    ;;
status)
    kssh "echo '--- processes ---'; ps | grep -E 'gazette|touch_tap|lipc-wait|tailscaled' | grep -v grep; \
          echo '--- pid file ---'; cat '${CACHE_DIR}/gazette.pid' 2>/dev/null || echo '(none)'; \
          echo '--- last log ---'; tail -20 '${CACHE_DIR}/viewer.log' 2>/dev/null || echo '(no log)'"
    ;;
rollback)
    echo "==> Removing ${EXT_DIR} (other extensions are untouched)"
    kssh "rm -rf '${EXT_DIR}'"
    echo "Done. Restart KUAL to make the menu entry disappear."
    ;;
checklist)
    cat <<'EOF'
Verification checklist (one stage at a time; keep `logs` running in a
second terminal). After EVERY stage, confirm before moving on.

 1. KUAL shows "Kindle Gazette". Open it. Do NOT start yet.
 2. Server up on this machine first:
      cd mcp_server && uv sync && uv run playwright install chromium
      uv run kindle-gazette      # or via your agent; port 8888
    Publish a test edition from your agent (or curl the health endpoint).
 3. KUAL -> Start Gazette (interactive). EXPECT in logs: "Interactive
    Viewer v5", token line only if configured, "Server reachable"/fetch
    lines, "Displayed". Glass shows the front page with the edition stamp.
 4. Tap a card -> section opens. In an article: NEXT/PREV page taps, BACK,
    masthead tap re-fetches. EXPECT no "Ignoring non-touch line" spam.
 5. Power button -> sleeps (screensaver). Press again + swipe -> EXPECT
    logs: WAKE, "Server reachable after Ns", home re-fetched, "Drain
    complete". Glass returns to a fresh front page.
 6. Failure drill: stop the server on this machine, power-cycle the Kindle
    awake. EXPECT: cached front page shows; logs say "Server not reachable
    ... continuing anyway". Restart the server. EXPECT within ~15-45s:
    "Retry succeeded" and a fresh page WITHOUT touching the device.
 7. KUAL -> Stop Gazette. EXPECT: pid file gone (status shows none), no
    gazette.sh/touch_tap/lipc-wait-event processes, Kindle UI responsive.
 8. Optional token: set KINDLE_GAZETTE_TOKEN on the server, write the same
    string to /mnt/us/extensions/kindle-gazette/token (one line, no
    spaces), restart both sides; verify fetches still work, and that a
    wrong token logs 401s server-side.

If a stage fails: stop, run `status`, save the log tail, and roll back
(`rollback`) if the device is unusable — it removes only this extension.
Report the failing stage + log lines.
EOF
    ;;
*)
    die "unknown command: ${CMD} (deploy|logs|status|rollback|checklist)"
    ;;
esac
