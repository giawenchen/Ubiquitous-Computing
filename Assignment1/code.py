import time
import ssl
import wifi
import socketpool
import adafruit_requests
import board
import displayio
import terminalio
import gc
from adafruit_display_text import label

# CONFIG
WIFI_OPTIONS = [
    ("RedRover", None),
    ("WhiteSky-Cornell", "2cgvwj69")
]

CITY = "New York City"
UNITS = "metric"

# OpenWeather (backup / optional)
OPENWEATHER_API_KEY = "YOUR_OPENWEATHER_KEY"

# Spoonacular
SPOONACULAR_API_KEY = "YOUR_SPOONACULAR_KEY"

# DISPLAY SETUP
display = board.DISPLAY
main_group = displayio.Group()
display.root_group = main_group

def clear_screen():
    while len(main_group):
        main_group.pop()

def show_message(text, scale=1, color=0xFFFFFF):
    clear_screen()
    main_group.append(
        label.Label(
            terminalio.FONT,
            text=text,
            scale=scale,
            color=color,
            x=10,
            y=60
        )
    )

# BOOT MESSAGE
show_message("Booting...", scale=2)

# WIFI SETUP
connected = False
for ssid, password in WIFI_OPTIONS:
    try:
        show_message(f"Connecting:\n{ssid}", scale=1)
        if password:
            wifi.radio.connect(ssid, password)
        else:
            wifi.radio.connect(ssid)
        connected = True
        break
    except Exception as e:
        print("WiFi failed:", e)

if not connected:
    show_message("WiFi Failed", scale=2, color=0xFF0000)
    while True:
        pass

pool = socketpool.SocketPool(wifi.radio)
ssl_context = ssl.create_default_context()
requests = adafruit_requests.Session(pool, ssl_context)

# ICON RENDERING
def display_icon(icon_name):
    try:
        bitmap = displayio.OnDiskBitmap(f"/icons/{icon_name}.bmp")
        tile_grid = displayio.TileGrid(
            bitmap,
            pixel_shader=bitmap.pixel_shader,
            x=170,
            y=25
        )
        main_group.append(tile_grid)
    except Exception as e:
        print("Icon error:", e)

# WEATHER (NWS API)
def get_weather():
    headers = {"User-Agent": "CircuitPython-Telltale"}

    # NYC coordinates
    points_url = "https://api.weather.gov/points/40.7128,-74.0060"
    r = requests.get(points_url, headers=headers)
    forecast_url = r.json()["properties"]["forecast"]
    r.close()

    r = requests.get(forecast_url, headers=headers)
    data = r.json()
    r.close()

    current = data["properties"]["periods"][0]
    temp_f = current["temperature"]
    temp_c = int((temp_f - 32) * 5 / 9)
    condition = current["shortForecast"]

    if "Rain" in condition:
        condition = "Rain"
    elif "Cloudy" in condition:
        condition = "Cloudy"
    elif "Sunny" in condition or "Clear" in condition:
        condition = "Clear"
    else:
        condition = "Mixed"

    return temp_c, condition

# FOOD LOGIC 
def decide_food_mood(temp, condition):
    if temp < 5:
        return "Warm & Comforting", "stew"
    elif temp > 25:
        return "Clean & Cooling", "salad"
    elif condition == "Rain":
        return "Hot Soup Time", "soup"
    elif condition == "Clear":
        return "Light & Fresh", "sushi"
    else:
        return "Cozy & Indulgent", "comfort"
    
def get_vitamin_tip(temp, condition):
    if temp < 10 or condition == "Rain":
        return "Tip: Need Vit D (Eggs/Fish)"
    elif condition == "Clear":
        return "Tip: Vit C (Citrus/Greens)"
    else:
        return "Tip: Stay Hydrated!"

# RECIPE API
def fetch_recipe(query):
    url = (
        "https://api.spoonacular.com/recipes/complexSearch"
        f"?query={query}&number=1&addRecipeInformation=true"
        f"&apiKey={SPOONACULAR_API_KEY}"
    )
    r = requests.get(url)
    data = r.json()
    r.close()

    if not data.get("results"):
        return "Simple Pasta", 15

    recipe = data["results"][0]
    return recipe["title"], recipe.get("readyInMinutes", 30)

# UI RENDER
def draw_screen(temp, condition, mood_text, vit_tip, icon_name):
    clear_screen()
    main_group.append(
        label.Label(terminalio.FONT, text=f"New York: {condition}", scale=2, color=0x00FFFF, x=10, y=15)
    )
    main_group.append(
        label.Label(terminalio.FONT, text=f"{temp} C", scale=3, color=0xFFFFFF, x=10, y=42)
    )
    offset_x = 75 if abs(temp) >= 10 else 55
    main_group.append(
        label.Label(terminalio.FONT, text="o", scale=1, color=0xFFFFFF, x=offset_x, y=32)
    )
    main_group.append(
        label.Label(terminalio.FONT, text="Today's Food Mood", scale=1, color=0xAAAAAA, x=10, y=72)
    )
    main_group.append(
        label.Label(terminalio.FONT, text=mood_text, scale=2, color=0xFFFF00, x=10, y=90)
    )
    main_group.append(
        label.Label(terminalio.FONT, text=vit_tip, scale=1, color=0x00FF00, x=10, y=115)
    )
    display_icon(icon_name)

# MAIN LOOP
while True:
    try:
        show_message("Updating...", scale=1)
        temp, condition = get_weather() 
        mood_text, category = decide_food_mood(temp, condition)
        vit_tip = get_vitamin_tip(temp, condition)
        draw_screen(temp, condition, mood_text, vit_tip, category)
        print("Display updated with Vitamin Tip")

    except Exception as e:
        print("Error:", e)
        show_message(f"Error: {str(e)[:15]}", scale=1, color=0xFF0000)

    gc.collect()
    time.sleep(600)