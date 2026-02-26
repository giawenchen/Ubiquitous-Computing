import time
import math
import board
import wifi
import socketpool
import displayio
import terminalio
from adafruit_display_text import label
import adafruit_icm20x

# =====================================================
# CONFIGURATION
# =====================================================

SAMPLE_RATE = 50
WINDOW_SIZE = 50              # 1 second buffer
UPDATE_INTERVAL = 0.2

# Intensity thresholds (tune on real wrist)
ACCEL_MIN = 0.12
ACCEL_MAX = 0.60

# Frequency thresholds (brushing band)
FREQ_MIN = 1.5
FREQ_MAX = 4.5
IDEAL_FREQ = 3.0

# =====================================================
# IMU SETUP
# =====================================================

i2c = board.I2C()
imu = adafruit_icm20x.ICM20948(i2c)

# =====================================================
# DISPLAY SETUP
# =====================================================

display = board.DISPLAY
group = displayio.Group()
display.root_group = group

title = label.Label(terminalio.FONT, text="SMART BRUSH", x=10, y=15)
motion_label = label.Label(terminalio.FONT, text="Motion: 0.00", x=10, y=40)
freq_label = label.Label(terminalio.FONT, text="Freq: 0.00 Hz", x=10, y=60)
volume_label = label.Label(terminalio.FONT, text="Volume: 0.00", x=10, y=80)
bar_label = label.Label(terminalio.FONT, text="[                    ]", x=10, y=105)
ip_label = label.Label(terminalio.FONT, text="Connecting WiFi...", x=10, y=125)

group.append(title)
group.append(motion_label)
group.append(freq_label)
group.append(volume_label)
group.append(bar_label)
group.append(ip_label)

# =====================================================
# WIFI SETUP
# =====================================================

SSID = "YOUR_WIFI"
PASSWORD = "YOUR_PASSWORD"

print("Connecting to WiFi...")
wifi.radio.connect(SSID, PASSWORD)
pool = socketpool.SocketPool(wifi.radio)
ip_label.text = "IP: {}".format(wifi.radio.ipv4_address)
print("Connected:", wifi.radio.ipv4_address)

server = pool.socket()
server.bind(("0.0.0.0", 80))
server.listen(1)

# =====================================================
# SIGNAL PROCESSING
# =====================================================

def accel_dynamic():
    ax, ay, az = imu.acceleration
    ax /= 9.81
    ay /= 9.81
    az /= 9.81
    mag = math.sqrt(ax*ax + ay*ay + az*az)
    return abs(mag - 1.0)

def rms(values):
    return math.sqrt(sum(v*v for v in values) / len(values))

def zero_crossing_freq(values):
    mean = sum(values) / len(values)
    crossings = 0
    for i in range(1, len(values)):
        if (values[i-1] - mean) * (values[i] - mean) < 0:
            crossings += 1
    return (crossings / 2) / (len(values) / SAMPLE_RATE)

def compute_volume(rms_val, freq_val):

    # Intensity factor (0–1)
    if rms_val < ACCEL_MIN or rms_val > ACCEL_MAX:
        intensity_factor = 0
    else:
        intensity_factor = (rms_val - ACCEL_MIN) / (ACCEL_MAX - ACCEL_MIN)

    # Frequency factor (penalize far from ideal)
    if freq_val < FREQ_MIN or freq_val > FREQ_MAX:
        freq_factor = 0
    else:
        freq_factor = 1 - abs(freq_val - IDEAL_FREQ) / (FREQ_MAX - FREQ_MIN)

    return max(0.0, min(1.0, intensity_factor * freq_factor))

# =====================================================
# RUNTIME VARIABLES
# =====================================================

buffer = [0.0] * WINDOW_SIZE
buf_index = 0
volume = 0.0

last_sample = time.monotonic()
last_update = time.monotonic()

# =====================================================
# MAIN LOOP
# =====================================================

while True:

    now = time.monotonic()

    # ---------------- Sample IMU ----------------
    if now - last_sample >= 1.0 / SAMPLE_RATE:
        last_sample = now
        buffer[buf_index] = accel_dynamic()
        buf_index = (buf_index + 1) % WINDOW_SIZE

    # ---------------- Update Logic ----------------
    if now - last_update >= UPDATE_INTERVAL:
        last_update = now

        rms_val = rms(buffer)
        freq_val = zero_crossing_freq(buffer)
        raw_volume = compute_volume(rms_val, freq_val)

        # Smooth output
        if raw_volume < volume:
            alpha = 0.05
        else:
            alpha = 0.3

        volume = alpha * raw_volume + (1 - alpha) * volume

        # Update Display
        motion_label.text = "Motion: {:.2f}".format(rms_val)
        freq_label.text = "Freq: {:.2f} Hz".format(freq_val)
        volume_label.text = "Volume: {:.2f}".format(volume)

        bar_len = 20
        filled = int(volume * bar_len)
        bar_label.text = "[" + "█"*filled + " "*(bar_len-filled) + "]"

    # ---------------- Simple HTTP Server ----------------
    try:
        conn, addr = server.accept()
        request = conn.recv(1024)

        response = """HTTP/1.1 200 OK
Content-Type: application/json

{{"volume": {:.2f}}}
""".format(volume)

        conn.send(response.encode("utf-8"))
        conn.close()

    except:
        pass