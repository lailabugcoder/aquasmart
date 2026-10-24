import os, time, requests, board, adafruit_dht

SITE = os.environ.get("SITE_URL", "http://localhost:5000")
TOKEN = os.environ.get("PI_TOKEN", "")
SOIL_ENABLED = False            # set True once the soil sensor is wired and calibrated
DRY_RAW, WET_RAW = 0.60, 0.25   # measure with scan.py: sensor in air = dry, in water = wet

dht = adafruit_dht.DHT22(board.D4)
if SOIL_ENABLED:
    from gpiozero import MCP3008
    soil = MCP3008(channel=0)


def soil_pct():
    pct = (soil.value - DRY_RAW) / (WET_RAW - DRY_RAW) * 100   # works if the scale runs either way
    return max(0, min(100, pct))


while True:
    try:
        data = {"temp": round(dht.temperature * 9 / 5 + 32, 1), "hum": round(dht.humidity, 1)}
        if SOIL_ENABLED:
            data["soil"] = round(soil_pct())
        requests.post(SITE + "/api/reading", json=data, headers={"X-Token": TOKEN}, timeout=8)
        print("sent", data)
    except Exception as e:
        print("retrying:", e)
    time.sleep(30)
