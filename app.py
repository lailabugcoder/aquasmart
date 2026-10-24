import math, os, time, requests
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask, jsonify, request, send_file

app = Flask(__name__)
KEY = os.environ.get("OPENWEATHER_KEY", "")
TOKEN = os.environ.get("PI_TOKEN", "")
CITY = os.environ.get("CITY", "Pembroke Pines")
AI_KEY = os.environ.get("ANTHROPIC_API_KEY", "")           # optional: turns on the AI advisor
MODEL = os.environ.get("AI_MODEL", "claude-sonnet-5-5")
HF_TOKEN = os.environ.get("HF_TOKEN", "")                 # optional: free AI advisor through Hugging Face
HF_MODEL = os.environ.get("HF_MODEL", "meta-llama/Llama-3.1-8B-Instruct")
HISTORY, WX, FX, AI_CALLS = [], {"t": 0, "d": None}, {"t": 0, "d": None}, []
OWM = "https://api.openweathermap.org/data/2.5/"
# name: (too dry below %, too wet above %, care tip). Starting values: calibrate with your own sensor.
PLANTS = {
    "lawn": (30, 70, "St. Augustine lawn: water deeply and less often instead of a little every day."),
    "hibiscus": (40, 75, "Hibiscus likes evenly moist, well-drained soil and wilts fast when it dries out."),
    "areca": (40, 75, "Areca palms like evenly moist soil but dislike sitting in soggy ground."),
    "garden": (40, 75, "Vegetables do best with steady moisture, so avoid swings between bone dry and soaked."),
    "native": (20, 55, "Florida-friendly natives need little water once established, so water less than you think."),
    "succulent": (15, 40, "Succulents rot in soggy soil, so let it dry out between waterings."),
}
DAYS = {"odd": (2, 5), "even": (3, 6)}   # Broward year-round rule: odd = Wed/Sat, even = Thu/Sun
NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def weather():
    if time.time() - WX["t"] > 600:
        try:
            r = requests.get(OWM + "weather", params={"q": CITY, "appid": KEY, "units": "imperial"}, timeout=5).json()
            WX["d"] = {"temp": round(r["main"]["temp"]), "humidity": r["main"]["humidity"],
                       "desc": r["weather"][0]["description"].title(),
                       "rain": any(w["main"] in ("Rain", "Drizzle", "Thunderstorm") for w in r["weather"])}
            WX["t"] = time.time()
        except Exception:
            pass
    return WX["d"]


def forecast():
    if time.time() - FX["t"] > 1800:
        try:
            items = requests.get(OWM + "forecast", params={"q": CITY, "appid": KEY, "units": "imperial", "cnt": 8},
                                 timeout=5).json()["list"]
            soon = next((i for i in items if i.get("pop", 0) >= 0.5), None)
            FX["d"] = {"rain_chance": round(max(i.get("pop", 0) for i in items) * 100),
                       "hours": max(0, round((soon["dt"] - time.time()) / 3600)) if soon else None,
                       "high": round(max(i["main"]["temp"] for i in items))}
            FX["t"] = time.time()
        except Exception:
            pass
    return FX["d"]


def rules(addr):
    if addr not in DAYS:
        return None
    n = datetime.now(ZoneInfo("America/New_York"))
    ok_day, ok_hour = n.weekday() in DAYS[addr], (n.hour < 10 or n.hour >= 16)
    if ok_day and ok_hour:
        return True, "Broward rules allow watering at your address right now (before 10 AM or after 4 PM)."
    if ok_day:
        return False, "Today is a watering day for your address, but sprinklers are off from 10 AM to 4 PM. Water after 4 PM."
    nxt = min(DAYS[addr], key=lambda d: (d - n.weekday()) % 7)
    return False, f"Next allowed day for your address: {NAMES[nxt]}, before 10 AM or after 4 PM."


def demo_data():                                          # simulated Pi readings so judges can preview the sensor features
    now, hist = int(time.time()), []
    for i in range(24, -1, -1):
        t = now - i * 600
        k = t / 3600
        hist.append({"t": t, "temp": round(79 + 4 * math.sin(k), 1), "hum": round(58 + 8 * math.cos(k), 1),
                     "soil": round(52 + 30 * math.sin(k / 2))})
    return hist[-1], hist


def recommend(w, soil, f, plant):
    low, high, _ = PLANTS[plant]
    if w and w["rain"]:
        return "skip", "Rain detected. Skip watering today."
    if f and f["rain_chance"] >= 60 and f["hours"] is not None and f["hours"] <= 12:
        return "hold", f"Rain is likely in about {f['hours']} hours ({f['rain_chance']}% chance). Hold off and let the rain do the work."
    if soil is not None:
        if soil < low:
            return "water", f"Soil is dry ({round(soil)}%) for your {plant}. Water now, ideally early morning."
        if soil > high:
            return "skip", f"Soil is wet ({round(soil)}%). No watering needed."
    if w and w["temp"] >= 90:
        return "ok", "It is hot out. If the soil is dry, water at dawn or dusk to cut evaporation."
    if w and w["humidity"] > 85:
        return "hold", "Very humid outside. Check the soil before watering."
    return "ok", "Conditions are fine. Water only if the soil feels dry."


def snapshot(plant, addr, demo):
    plant = plant if plant in PLANTS else "garden"
    w, f = weather(), forecast()
    if demo:
        last, hist, online = *demo_data(), True
    else:
        hist, last = HISTORY, (HISTORY[-1] if HISTORY else None)
        online = bool(last and time.time() - last["t"] < 120)
    soil = last["soil"] if online and last else None
    level, msg = recommend(w, soil, f, plant)
    rule = rules(addr)
    if rule and level == "water" and not rule[0]:
        level, msg = "hold", "Soil is dry, but county rules do not allow watering right now. " + rule[1]
    return dict(w=w, f=f, last=last, hist=hist, online=online, soil=soil, level=level, msg=msg,
                rule=rule[1] if rule else None, plant=plant, demo=demo)


@app.route("/")
def home():
    return send_file("index.html")


@app.route("/api/reading", methods=["POST"])
def reading():
    if not TOKEN or request.headers.get("X-Token") != TOKEN:
        return jsonify(error="unauthorized"), 401
    d = request.get_json(force=True, silent=True) or {}
    HISTORY.append({"t": int(time.time()), "temp": d.get("temp"), "hum": d.get("hum"), "soil": d.get("soil")})
    del HISTORY[:-288]
    return jsonify(ok=True)


@app.route("/api/state")
def state():
    a = request.args
    s = snapshot(a.get("plant"), a.get("addr"), a.get("demo") == "1")
    return jsonify(weather=s["w"], forecast=s["f"], pi=s["last"] if s["online"] else None, online=s["online"],
                   demo=s["demo"], history=s["hist"], level=s["level"], message=s["msg"], rule=s["rule"],
                   tip=PLANTS[s["plant"]][2], ai=bool(AI_KEY or HF_TOKEN))


@app.route("/api/advice", methods=["POST"])
def advice():
    if not (AI_KEY or HF_TOKEN):
        return jsonify(error="The AI advisor is not turned on for this site."), 503
    now = time.time()
    AI_CALLS[:] = [t for t in AI_CALLS if now - t < 3600]
    if len(AI_CALLS) >= 20:                              # caps cost: 20 answers per hour for the whole site
        return jsonify(error="The advisor is resting. Try again in a few minutes."), 429
    AI_CALLS.append(now)
    d = request.get_json(silent=True) or {}
    s = snapshot(d.get("plant"), d.get("addr"), bool(d.get("demo")))
    soil_txt = f"{round(s['soil'])}%" if s["soil"] is not None else "no sensor connected"
    facts = (f"Location: {CITY}, Florida. Plant: {s['plant']}. Weather now: {s['w']}. Next 24 hours: {s['f']}. "
             f"Soil moisture: {soil_txt}. County watering rule: {s['rule'] or 'address not given'}. "
             f"Rule-based recommendation: {s['msg']}")
    system = ("You advise South Florida homeowners on watering. Use only the facts given. "
              "Write 3 short, specific tips, under 90 words total, in plain sentences. Never invent numbers.")
    try:
        if HF_TOKEN:                                     # Hugging Face is used first because it has a free tier
            err = ""
            for m in dict.fromkeys([HF_MODEL, "deepseek-ai/DeepSeek-V3-0324"]):   # try the chosen model, then a backup
                try:
                    r = requests.post("https://router.huggingface.co/v1/chat/completions",
                                      headers={"Authorization": f"Bearer {HF_TOKEN}"},
                                      json={"model": m, "max_tokens": 400,
                                            "messages": [{"role": "system", "content": system},
                                                         {"role": "user", "content": facts}]}, timeout=12)
                    body = r.json() if r.content else {}
                    text = ((body.get("choices") or [{}])[0].get("message", {}).get("content") or "").strip() if r.ok else ""
                    if text:
                        return jsonify(advice=text)
                    err = f"{m}: HTTP {r.status_code} {str(body.get('error', body))[:150]}"
                except Exception as e:
                    err = f"{m}: {type(e).__name__}"
                print("HF advisor error:", err, flush=True)
            return jsonify(error="The advisor could not respond. Details: " + err), 502
        r = requests.post("https://api.anthropic.com/v1/messages",
                          headers={"x-api-key": AI_KEY, "anthropic-version": "2023-06-01"},
                          json={"model": MODEL, "max_tokens": 300, "system": system,
                                "messages": [{"role": "user", "content": facts}]}, timeout=25)
        return jsonify(advice=r.json()["content"][0]["text"])
    except Exception:
        return jsonify(error="The advisor could not respond. Try again in a minute."), 502


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
