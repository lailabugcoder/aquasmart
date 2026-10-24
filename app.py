import os, time, requests
from flask import Flask, jsonify, request, send_file

app = Flask(__name__)
KEY = os.environ.get("OPENWEATHER_KEY", "")
TOKEN = os.environ.get("PI_TOKEN", "")
CITY = os.environ.get("CITY", "Pembroke Pines")
HISTORY, WX = [], {"t": 0, "d": None}   # in memory: resets when the host restarts


def weather():
    if time.time() - WX["t"] > 600:      # refresh every 10 minutes
        try:
            r = requests.get("https://api.openweathermap.org/data/2.5/weather",
                             params={"q": CITY, "appid": KEY, "units": "imperial"},
                             timeout=5).json()
            WX["d"] = {"temp": round(r["main"]["temp"]), "humidity": r["main"]["humidity"],
                       "desc": r["weather"][0]["description"].title(),
                       "rain": any(w["main"] in ("Rain", "Drizzle", "Thunderstorm")
                                   for w in r["weather"])}
            WX["t"] = time.time()
        except Exception:
            pass
    return WX["d"]


def recommend(w, soil):
    if w and w["rain"]:
        return "skip", "Rain detected. Skip watering today."
    if soil is not None:
        if soil < 30:
            return "water", f"Soil is dry ({round(soil)}%). Water now, ideally early morning."
        if soil > 70:
            return "skip", f"Soil is wet ({round(soil)}%). No watering needed."
    if w and w["humidity"] > 85:
        return "hold", "Very humid outside. Check the soil before watering."
    return "ok", "Conditions are fine. Water only if the soil feels dry."


@app.route("/")
def home():
    return send_file("index.html")


@app.route("/api/reading", methods=["POST"])
def reading():
    if not TOKEN or request.headers.get("X-Token") != TOKEN:
        return jsonify(error="unauthorized"), 401
    d = request.get_json(force=True, silent=True) or {}
    HISTORY.append({"t": int(time.time()), "temp": d.get("temp"),
                    "hum": d.get("hum"), "soil": d.get("soil")})
    del HISTORY[:-288]                   # keep the latest 288 readings
    return jsonify(ok=True)


@app.route("/api/state")
def state():
    w = weather()
    last = HISTORY[-1] if HISTORY else None
    online = bool(last and time.time() - last["t"] < 120)
    level, msg = recommend(w, last["soil"] if online else None)
    return jsonify(weather=w, pi=last if online else None, online=online,
                   history=HISTORY, level=level, message=msg)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
