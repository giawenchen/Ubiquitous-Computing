"""
BrushBeat — code.py  (CircuitPython, ESP32-S2 TFT Feather)
============================================================
Copy this file to the root of your CIRCUITPY drive as code.py.

What it does:
  - Reads wrist motion from ICM20948 IMU at 50 Hz
  - Maps motion intensity → volume (0.0–1.0)
  - Shows polished BrushBeat UI on the TFT display:
      STILL  → grey,   0%
      gentle → green,  low volume
      medium → orange, mid volume
      HARD   → red,    high volume
  - Serves live data over WiFi HTTP:
      GET http://<device-ip>/ → {"volume": 0.72, "rms": 0.234}

Required CircuitPython libraries (copy to CIRCUITPY/lib/):
  - adafruit_icm20x.mpy
  - adafruit_display_text/  (folder)
  - adafruit_bitmap_font/   (folder, optional)

Hardware:
  - Adafruit ESP32-S2 TFT Feather
  - ICM20948 IMU breakout wired to I2C (SDA/SCL)

WiFi: edit WIFI_OPTIONS below to match your network.
"""

import time
import math
import board
import wifi
import socketpool
import displayio
import terminalio
import adafruit_icm20x
from adafruit_display_text import label

# ─────────────────────────────────────────────────────
# CONFIGURATION  ← edit these
# ─────────────────────────────────────────────────────

WIFI_OPTIONS = [
    ("jiawenhii",        "qmqmqmQQMM0"),   # phone hotspot
    ("WhiteSky-Cornell", "2cgvwj69"),
    ("RedRover",         None),
]

# Motion thresholds (in g, gravity removed).
# Open serial monitor with DEBUG=True and shake your wrist
# to find the right values for your motion style.
MOTION_DEAD = 0.04    # below this → STILL, volume = 0
MOTION_MIN  = 0.06    # motion starts registering
MOTION_MAX  = 0.50    # full volume (clamp above this)

SAMPLE_RATE     = 50    # Hz
WINDOW_SIZE     = 50    # samples in rolling window (= 1 second)
UPDATE_INTERVAL = 0.12  # display + server refresh rate (seconds)

ALPHA_RISE = 0.4        # volume smoothing — how fast it rises
ALPHA_FALL = 0.2        # how fast it falls

DEBUG = True            # print rms/vol to serial for calibration

# ─────────────────────────────────────────────────────
# IMU
# ─────────────────────────────────────────────────────

i2c = board.I2C()
imu = adafruit_icm20x.ICM20948(i2c)

# ─────────────────────────────────────────────────────
# DISPLAY
# ─────────────────────────────────────────────────────

display = board.DISPLAY
W = display.width    # 240
H = display.height   # 135

group = displayio.Group()
display.root_group = group

# Colors
BLACK    = 0x000000
GREY     = 0x444455
MUTED    = 0x888899
GREEN    = 0x50E080
ORANGE   = 0xF0A020
RED      = 0xE84060
DKGREEN  = 0x103020
DKORANGE = 0x301800
DKRED    = 0x300010

# Background
bg_bitmap  = displayio.Bitmap(W, H, 1)
bg_palette = displayio.Palette(1)
bg_palette[0] = BLACK
group.append(displayio.TileGrid(bg_bitmap, pixel_shader=bg_palette))

# Volume bar track
BAR_X = 12
BAR_Y = 68
BAR_W = W - 24
BAR_H = 7

bar_bg_pal    = displayio.Palette(1)
bar_bg_pal[0] = 0x1a1a2a
group.append(displayio.TileGrid(displayio.Bitmap(BAR_W, BAR_H, 1),
             pixel_shader=bar_bg_pal, x=BAR_X, y=BAR_Y))

# Volume bar fill
bar_fill_pal    = displayio.Palette(1)
bar_fill_pal[0] = GREEN
bar_fill_bm     = displayio.Bitmap(BAR_W, BAR_H, 1)
group.append(displayio.TileGrid(bar_fill_bm, pixel_shader=bar_fill_pal,
             x=BAR_X, y=BAR_Y))

# Waveform dot row
WAVE_Y   = 84
WAVE_N   = 30
DOT_SIZE = 3
wave_palettes = []
for i in range(WAVE_N):
    pal    = displayio.Palette(1)
    pal[0] = GREY
    bm     = displayio.Bitmap(DOT_SIZE, DOT_SIZE, 1)
    x_pos  = BAR_X + i * (BAR_W // WAVE_N)
    group.append(displayio.TileGrid(bm, pixel_shader=pal, x=x_pos, y=WAVE_Y))
    wave_palettes.append(pal)

# Labels
lbl_app   = label.Label(terminalio.FONT, text="BrushBeat",  x=12,     y=10,  color=0x334433, scale=1)
lbl_state = label.Label(terminalio.FONT, text="STILL",      x=12,     y=30,  color=MUTED,    scale=3)
lbl_sub   = label.Label(terminalio.FONT, text="no motion",  x=12,     y=52,  color=GREY,     scale=1)
lbl_vol   = label.Label(terminalio.FONT, text=" 0%",        x=W - 48, y=30,  color=MUTED,    scale=2)
lbl_rms   = label.Label(terminalio.FONT, text="rms:0.000g", x=12,     y=118, color=GREY,     scale=1)
lbl_info  = label.Label(terminalio.FONT, text="connecting", x=W - 96, y=118, color=GREY,     scale=1)

for lbl in (lbl_app, lbl_state, lbl_sub, lbl_vol, lbl_rms, lbl_info):
    group.append(lbl)

# ─────────────────────────────────────────────────────
# WiFi + HTTP SERVER
# ─────────────────────────────────────────────────────

connected = False
for ssid, password in WIFI_OPTIONS:
    try:
        if password:
            wifi.radio.connect(ssid, password)
        else:
            wifi.radio.connect(ssid)
        connected = True
        break
    except Exception:
        pass

if not connected:
    lbl_info.text  = "WiFi fail!"
    lbl_info.color = 0xFF0000
    while True:
        pass

my_ip = str(wifi.radio.ipv4_address)
print("Connected! IP:", my_ip)
lbl_info.text = my_ip

pool   = socketpool.SocketPool(wifi.radio)
server = pool.socket()
server.bind(("0.0.0.0", 80))
server.listen(1)
server.setblocking(False)   # never block the main loop

# ─────────────────────────────────────────────────────
# SIGNAL PROCESSING
# ─────────────────────────────────────────────────────

def get_dynamic_accel():
    """3-axis magnitude minus 1 g gravity → dynamic motion in g."""
    ax, ay, az = imu.acceleration
    mag = math.sqrt((ax / 9.81) ** 2 + (ay / 9.81) ** 2 + (az / 9.81) ** 2)
    return abs(mag - 1.0)

def rms(values):
    return math.sqrt(sum(v * v for v in values) / len(values))

def motion_to_volume(rms_val):
    """Linear ramp: still→0, gentle→low, hard→1.0."""
    if rms_val < MOTION_DEAD:
        return 0.0
    if rms_val > MOTION_MAX:
        return 1.0
    if rms_val < MOTION_MIN:
        return 0.1 * (rms_val - MOTION_DEAD) / (MOTION_MIN - MOTION_DEAD)
    return 0.1 + 0.9 * (rms_val - MOTION_MIN) / (MOTION_MAX - MOTION_MIN)

def classify_state(vol, rms_val):
    """Return (name, subtitle, text_color, bg_color, bar_color)."""
    if rms_val < MOTION_DEAD:
        return "STILL",  "no motion",     MUTED,  BLACK,    GREY
    elif vol < 0.38:
        return "gentle", "slow strokes",  GREEN,  DKGREEN,  GREEN
    elif vol < 0.70:
        return "medium", "steady rhythm", ORANGE, DKORANGE, ORANGE
    else:
        return "HARD",   "vigorous brush", RED,   DKRED,    RED

# ─────────────────────────────────────────────────────
# DISPLAY HELPERS
# ─────────────────────────────────────────────────────

def set_bar(vol, color):
    fill_w = max(0, min(BAR_W, int(vol * BAR_W)))
    for x in range(BAR_W):
        for y in range(BAR_H):
            bar_fill_bm[x, y] = 1 if x < fill_w else 0
    bar_fill_pal[0] = color

def set_wave(vol, phase, color):
    for i in range(WAVE_N):
        if vol < 0.02:
            wave_palettes[i][0] = 0x1a1a2a   # flat / dark
        else:
            t   = i / WAVE_N
            amp = (math.sin(t * math.pi * 4 + phase) * 0.6
                 + math.sin(t * math.pi * 9 + phase * 1.4) * 0.4)
            wave_palettes[i][0] = color if amp > (1.0 - vol * 1.5) else 0x1a1a2a

def render_ui(vol, rms_val, phase):
    name, sub, color, bg, bar_c = classify_state(vol, rms_val)
    bg_palette[0]   = bg
    lbl_state.text  = name
    lbl_state.color = color
    lbl_sub.text    = sub
    lbl_sub.color   = color if vol > 0.02 else GREY
    lbl_vol.text    = f"{int(vol * 100):2d}%"
    lbl_vol.color   = color if vol > 0.02 else MUTED
    lbl_rms.text    = f"rms:{rms_val:.3f}g"
    set_bar(vol, bar_c)
    set_wave(vol, phase, color)

# ─────────────────────────────────────────────────────
# RUNTIME STATE
# ─────────────────────────────────────────────────────

mag_buffer       = [0.0] * WINDOW_SIZE
buf_index        = 0
volume           = 0.0
rms_val          = 0.0
phase            = 0.0

last_sample_time = time.monotonic()
last_update_time = time.monotonic()
SAMPLE_INTERVAL  = 1.0 / SAMPLE_RATE

# ─────────────────────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────────────────────

while True:
    now = time.monotonic()

    # ── 1. Sample IMU at 50 Hz ──────────────────────
    if now - last_sample_time >= SAMPLE_INTERVAL:
        last_sample_time += SAMPLE_INTERVAL
        mag_buffer[buf_index] = get_dynamic_accel()
        buf_index = (buf_index + 1) % WINDOW_SIZE

    # ── 2. Update display + compute volume ──────────
    if now - last_update_time >= UPDATE_INTERVAL:
        last_update_time = now

        rms_val = rms(mag_buffer)
        raw_vol = motion_to_volume(rms_val)

        # Smooth volume: fast rise, slower fall
        alpha  = ALPHA_RISE if raw_vol >= volume else ALPHA_FALL
        volume = alpha * raw_vol + (1 - alpha) * volume

        # Waveform phase advances faster with harder motion
        phase += rms_val * 8.0 + 0.05

        render_ui(volume, rms_val, phase)

        if DEBUG:
            name, *_ = classify_state(volume, rms_val)
            print(f"rms={rms_val:.4f}  vol={volume:.2f}  [{name}]")

    # ── 3. Serve HTTP (non-blocking) ────────────────
    try:
        conn, addr = server.accept()
        try:
            conn.recv(1024)
        except Exception:
            pass
        conn.send((
            "HTTP/1.1 200 OK\r\n"
            "Content-Type: application/json\r\n"
            "Connection: close\r\n"
            "\r\n"
            f'{{ "volume": {volume:.2f}, "rms": {rms_val:.3f} }}\r\n'
        ).encode("utf-8"))
        conn.close()
    except OSError:
        pass
    except Exception as e:
        print("Server error:", e)
