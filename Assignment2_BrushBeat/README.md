# BrushBeat — Wrist-Controlled Music Interface
### INFO 5304 Final Project -Jia Bo(jb2848) Jiawen Chen(jc3785)

---

## Concept

BrushBeat embeds an IMU sensor in a wristband worn during toothbrushing.
The intensity and energy of wrist motion is mapped in real time to the
volume of music playing on a laptop speaker:

- **Still wrist** → silence
- **Slow / gentle strokes** → quiet music
- **Steady medium brushing** → moderate volume
- **Vigorous hard brushing** → full volume

The goal is to make a mundane routine (brushing teeth) feel more
engaging and embodied — your body literally controls the music.

---

## Files

| File | Runs on | Purpose |
|------|---------|---------|
| `code.py` | Feather board | IMU sampling, UI display, WiFi HTTP server |
| `wrist_controller.py` | Mac laptop | Polls Feather, controls system volume, plays music |
| `brushbeat_demo.html` | Any browser | Standalone concept demo (no hardware needed) |

---

## Hardware

- **Adafruit ESP32-S2 TFT Feather** (240×135 display, WiFi)
- **ICM20948 IMU breakout** wired to I2C (SDA/SCL pins)
- Worn on wrist during toothbrushing

---

## Setup & Run

### 1. Feather board

Copy these files to the CIRCUITPY drive root:
```
code.py
lib/adafruit_icm20x.mpy
lib/adafruit_display_text/   (folder)
```

Edit WiFi credentials at the top of `code.py`:
```python
WIFI_OPTIONS = [
    ("YourNetwork", "YourPassword"),
]
```

The board will display its IP address on boot, e.g. `172.20.10.4`

### 2. Laptop (macOS)

Install dependencies once:
```bash
brew install mpv yt-dlp
```

Edit the Feather's IP in `wrist_controller.py`:
```python
FEATHER_IP = "172.20.10.4"   # ← change to your board's IP
```

Run:
```bash
python3 wrist_controller.py
```

Both devices must be on the **same WiFi network or hotspot**.
University networks (e.g. Cornell RedRover) block device-to-device
traffic — use a phone hotspot instead.

### 3. Demo (no hardware)

Open `brushbeat_demo.html` in any browser. Click the state buttons
or let it auto-cycle to simulate motion states.

---

## System Architecture

```
┌─────────────────┐        WiFi / HTTP         ┌──────────────────────┐
│  Wristband      │  GET / → {"volume": 0.72}  │  MacBook             │
│                 │ ─────────────────────────> │                      │
│  ICM20948 IMU   │                            │  wrist_controller.py │
│  50 Hz sampling │                            │  ↓                   │
│  RMS → volume   │                            │  osascript volume    │
│  BrushBeat UI   │                            │  ↓                   │
│  HTTP server    │                            │  mpv → speaker       │
└─────────────────┘                            └──────────────────────┘
```

---

## Signal Processing (code.py)

1. Sample 3-axis acceleration at 50 Hz
2. Compute dynamic magnitude: `|√(ax²+ay²+az²) − 1g|`
3. Rolling RMS over 1-second window (50 samples)
4. Linear map RMS → volume (0.0–1.0)
5. Exponential smoothing: fast rise (α=0.4), slower fall (α=0.2)
6. Classify into STILL / gentle / medium / HARD for UI

---

## Music Choice

**"Intro" — The xx (2009)**

Purely instrumental. Opens near-silence with a single clean guitar
note, then builds layer by layer over 2 minutes. The natural dynamic
range and ~1.5–2 Hz rhythm mirrors the brushing frequency range,
making the wrist feel like it's conducting the song.

---

## Calibration

With `DEBUG = True` in `code.py`, open a serial monitor to see:
```
rms=0.0231  vol=0.00  [STILL]
rms=0.0842  vol=0.18  [gentle]
rms=0.2340  vol=0.54  [medium]
rms=0.4710  vol=0.98  [HARD]
```

Adjust `MOTION_DEAD`, `MOTION_MIN`, `MOTION_MAX` in `code.py`
to match your personal brushing motion range.
