# Custom screensavers on the PW4 (linkss + ad_screensaver swap)

The device runs the linkss 0.25.N screensavers hack: at boot,
`/etc/upstart/linkss.conf` runs `/mnt/us/linkss/bin/linkss`, which
bind-mounts `/mnt/us/linkss/screensavers/` over
`/usr/share/blanket/screensaver/`, and blanket's `screensaver` module cycles
the `bg_ssNN.png` files there in filename order, one per suspend.

**The catch on ad-supported (Special Offers) devices**
(`lipc-get-prop com.lab126.adManager isAdUnitDevice` → 1): on FW 5.16.7,
blanket boots with an `ad_screensaver` module that owns the glass instead —
and with the gazette's touch grab it paints *nothing at all*: the screen simply froze on
whatever was showing when powerd entered the Screen Saver state, and the
linkss images never displayed. The fix:

```sh
lipc-set-prop com.lab126.blanket unload ad_screensaver
lipc-set-prop com.lab126.blanket load screensaver
```

This is runtime-only and resets on reboot — and a one-shot swap at boot is
not enough: the ad framework (dtcp/adManager) loads `ad_screensaver` a few
minutes into boot, long after any fixed startup window (a reboot test with
a one-shot swap brought the ads back). So `bin/linkss` launches
`kill-ad-screensaver.sh` in the background at every boot as a persistent
watchdog: it evicts `ad_screensaver` once blanket's lipc service is up, then
blocks on `lipc-wait-event -m com.lab126.blanket moduleLoaded` and evicts it
again within ~2s whenever anything reloads it (verified by loading the
module manually). It sleeps in the kernel between events, so it costs
nothing; a pidfile in /var/run keeps it single-instance per boot.

## Files here (Mac-side copies of what's deployed)

| File | Deploys to |
|---|---|
| `kill-ad-screensaver.sh` | `/mnt/us/linkss/bin/kill-ad-screensaver.sh` |
| `tailscale-boot.sh` | `/mnt/us/linkss/bin/tailscale-boot.sh` |
| `linkss.patched` | `/mnt/us/linkss/bin/linkss` (hooks inserted before the final `return 0`) |
| `linkss.orig` | pristine 0.25.N copy; also backed up on-device at `/mnt/us/linkss/backups/linkss.pre-adswap` (and `linkss.pre-tailscale` before the tailscale hook) |

## The Tailscale boot hook (piggybacked here)

`bin/linkss` is the only proven userstore boot vector on this firmware, so
it also backgrounds `tailscale-boot.sh`: tailscaled has no boot
hook of its own — it was KUAL-started only — and Tailscale SSH is the
device's *only* remote path (no LAN sshd), so a reboot used to cut off
remote access until someone touched the device. The hook starts tailscaled
in **proxy mode** (`localhost:1055`, exactly what `gazette.sh`'s
`ensure_tailscale_proxy()` expects), then retries `tailscale up --ssh`
(bounded, 40×15s — WiFi can lag boot by minutes) to re-assert prefs. A
daemon that's already running is left strictly alone: the SSH server lives
inside tailscaled, so bouncing it severs live sessions.

Verified without a reboot: with tailscaled killed, the hook restarted it in
a detached on-device session — the node reconnected from `--statedir` saved
state in ~18s, SSH came back, `up --ssh` confirmed. The true cold-boot
ordering (linkss → WiFi-up lag) is not yet verified with an at-the-device
reboot, so keep a USB fallback in mind the first time you rely on it.

## The plates

`scripts/make-screensavers.py` renders `kindle/screensavers/bg_ss00..02.png`
(1072x1448, 8-bit gray PNG holding 1-bit Floyd–Steinberg dithered content):
the caduceus engraving, the Didot "Night Edition" masthead, and the moiré
field. `scripts/deploy-screensavers.sh` backs up and installs them — into
**both** `/mnt/us/linkss/screensavers/` and `/mnt/us/screensavers/`, because
an older screensaver upstart job left on this device also bind-mounts the
latter and the two race at boot; identical sources make the race harmless.

## Verifying without touching the device

Suspend, dump the framebuffer, wake, decode (stride 1088, visible 1072x1448):

```sh
ssh root@kindle 'lipc-set-prop com.lab126.powerd powerButton 1; sleep 6;
  dd if=/dev/fb0 of=/tmp/ss.raw; lipc-set-prop com.lab126.powerd powerButton 1'
```

The fb tracks the glass exactly (validated by painting an eips marker and
re-dumping), so this shows what the screensaver really painted.
