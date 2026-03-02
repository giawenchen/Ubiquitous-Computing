#!/usr/bin/env python3
"""
BrushBeat — wrist_controller.py  (macOS)
==========================================
Runs on your laptop. Polls the Feather board's HTTP endpoint
for live wrist-motion volume, maps it to macOS system volume,
and streams music via mpv + yt-dlp.

Song: "Intro" by The xx — instrumental, builds naturally,
perfect dynamic range to match gentle→vigorous wrist motion.

─────────────────────────────────────────
SETUP (run once in Terminal):
    brew install mpv yt-dlp

USAGE:
    python3 wrist_controller.py

    Move your wrist gently → quiet music
    Move your wrist hard   → loud music
    Keep still             → silence
    Press Ctrl+C           → stop (restores original volume)
─────────────────────────────────────────

REQUIREMENTS:
  - macOS (uses osascript for system volume)
  - Python 3.9+ (stdlib only — no pip installs needed)
  - mpv + yt-dlp  (brew install mpv yt-dlp)
  - Feather board running code.py on the same WiFi/hotspot
"""

import subprocess
import time
import sys
import signal
import socket
import json

# ─────────────────────────────────────────────────────
# CONFIGURATION  ← edit FEATHER_IP to match your board
# ─────────────────────────────────────────────────────

# IP shown on the Feather's screen after boot
FEATHER_IP    = "172.20.10.4"

POLL_INTERVAL = 0.15    # seconds between polls
VOLUME_SMOOTH = 0.3     # laptop-side smoothing (0=sluggish, 1=instant)
MIN_VOL_PCT   = 0       # system volume floor (%)
MAX_VOL_PCT   = 100     # system volume ceiling (%)

# "Intro" by The xx — instrumental, ~2 Hz rhythm, builds organically
MUSIC_URL = "https://www.youtube.com/watch?v=oFRbZJXjWIA"

# ─────────────────────────────────────────────────────
# macOS SYSTEM VOLUME
# ─────────────────────────────────────────────────────

def set_system_volume(pct):
    """Set macOS output volume 0–100 via osascript."""
    vol = int(max(0, min(100, pct)))
    subprocess.run(["osascript", "-e", f"set volume output volume {vol}"],
                   capture_output=True)

def get_system_volume():
    result = subprocess.run(
        ["osascript", "-e", "output volume of (get volume settings)"],
        capture_output=True, text=True)
    try:
        return int(result.stdout.strip())
    except ValueError:
        return 50

# ─────────────────────────────────────────────────────
# DEPENDENCIES CHECK
# ─────────────────────────────────────────────────────

def check_dependencies():
    missing = []
    for cmd in ["mpv", "yt-dlp"]:
        result = subprocess.run(["which", cmd], capture_output=True)
        if result.returncode != 0:
            missing.append(cmd)
    if missing:
        print(f"\n  Missing: {', '.join(missing)}")
        print("  Install: brew install " + " ".join(missing))
        print("  (No brew? → https://brew.sh)\n")
        sys.exit(1)

# ─────────────────────────────────────────────────────
# MUSIC PLAYER
# ─────────────────────────────────────────────────────

def launch_music():
    """Stream music via mpv + yt-dlp. Volume controlled via system volume."""
    print(f"\n  ♫  Loading: The xx — Intro")
    print(f"     {MUSIC_URL}")
    print(f"     (buffering, may take a few seconds...)\n")
    return subprocess.Popen(
        ["mpv", "--no-video", "--volume=100", "--loop=inf",
         "--really-quiet", "--ytdl-raw-options=format=bestaudio", MUSIC_URL],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

# ─────────────────────────────────────────────────────
# FEATHER POLLING
# Uses raw socket — handles CircuitPython's abrupt
# connection-close without errors.
# ─────────────────────────────────────────────────────

def fetch_volume():
    """Returns wrist volume 0.0–1.0, or None on failure."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        s.connect((FEATHER_IP, 80))
        s.sendall(b"GET / HTTP/1.0\r\nHost: " + FEATHER_IP.encode() + b"\r\n\r\n")
        raw = b""
        while True:
            try:
                chunk = s.recv(1024)
                if not chunk:
                    break
                raw += chunk
            except Exception:
                break
        s.close()
        body = raw.split(b"\r\n\r\n", 1)[-1].strip()
        data = json.loads(body.decode("utf-8"))
        return float(data.get("volume", 0.0))
    except Exception:
        return None

# ─────────────────────────────────────────────────────
# TERMINAL BAR
# ─────────────────────────────────────────────────────

def render_bar(vol, width=30):
    filled = int(vol * width)
    bar    = "█" * filled + "░" * (width - filled)
    pct    = int(vol * 100)
    if vol < 0.05:
        state = "STILL  "
    elif vol < 0.38:
        state = "gentle "
    elif vol < 0.70:
        state = "medium "
    else:
        state = "HARD!!  "
    return f"\r  [{bar}] {pct:3d}%  {state}"

# ─────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────

def main():
    print("\n" + "=" * 50)
    print("   BrushBeat — Wrist Volume Controller")
    print("   Song: The xx — Intro")
    print("=" * 50)

    check_dependencies()

    original_vol = get_system_volume()
    print(f"\n  System volume: {original_vol}%  (restored on exit)")

    music_proc = launch_music()
    time.sleep(2.0)   # let mpv buffer

    smooth_vol = 0.0
    fail_count = 0
    MAX_FAILS  = 30

    def cleanup(sig=None, frame=None):
        print("\n\n  Stopping...")
        music_proc.terminate()
        set_system_volume(original_vol)
        print(f"  Volume restored to {original_vol}%. Bye!\n")
        sys.exit(0)

    signal.signal(signal.SIGINT,  cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    print("  Polling Feather — move your wrist!")
    print("  Ctrl+C to stop.\n")

    while True:
        start     = time.monotonic()
        wrist_vol = fetch_volume()

        if wrist_vol is None:
            fail_count += 1
            if fail_count == 1:
                print(f"\n  ! Cannot reach {FEATHER_IP} — retrying...")
            if fail_count >= MAX_FAILS:
                print(f"\n  ! Failed {MAX_FAILS} times. Check IP and WiFi.")
                cleanup()
        else:
            fail_count  = 0
            smooth_vol  = VOLUME_SMOOTH * wrist_vol + (1 - VOLUME_SMOOTH) * smooth_vol
            target_pct  = MIN_VOL_PCT + smooth_vol * (MAX_VOL_PCT - MIN_VOL_PCT)
            set_system_volume(target_pct)
            print(render_bar(smooth_vol), end="", flush=True)

        elapsed = time.monotonic() - start
        time.sleep(max(0.0, POLL_INTERVAL - elapsed))


if __name__ == "__main__":
    main()
