"""
Suraksha (सुरक्षा) — Disaster Management & Early Warning prototype API.

Data honesty contract: every response carries a `data_label`:
  - "live"   : fetched just now from a real upstream API (USGS / Open-Meteo)
  - "model"  : computed by Suraksha's transparent heuristic risk engine (NOT an
               official DHM/NDRRMA forecast — prototype only)
  - "sample" : illustrative seed data (shelters, GLOF lake registry)
"""
import asyncio
import math
import os
import time
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------- cities ----
CITIES = [
    {"id": "kathmandu",  "name_en": "Kathmandu",  "name_ne": "काठमाडौं",  "lat": 27.7172, "lon": 85.3240, "hill": True},
    {"id": "pokhara",    "name_en": "Pokhara",    "name_ne": "पोखरा",     "lat": 28.2096, "lon": 83.9856, "hill": True},
    {"id": "biratnagar", "name_en": "Biratnagar", "name_ne": "विराटनगर",  "lat": 26.4525, "lon": 87.2718, "hill": False},
    {"id": "nepalgunj",  "name_en": "Nepalgunj",  "name_ne": "नेपालगञ्ज", "lat": 28.0500, "lon": 81.6167, "hill": False},
    {"id": "dhangadhi",  "name_en": "Dhangadhi",  "name_ne": "धनगढी",     "lat": 28.7076, "lon": 80.5845, "hill": False},
    {"id": "damak",      "name_en": "Damak",      "name_ne": "दमक",        "lat": 26.6500, "lon": 87.7000, "hill": False},
    {"id": "urlabari",   "name_en": "Urlabari",   "name_ne": "उर्लाबारी", "lat": 26.6636, "lon": 87.7000, "hill": False},
    {"id": "jomsom",     "name_en": "Jomsom",     "name_ne": "जोमसोम",    "lat": 28.7806, "lon": 83.7222, "hill": True},
    {"id": "lukla",      "name_en": "Lukla",      "name_ne": "लुक्ला",     "lat": 27.6869, "lon": 86.7297, "hill": True},
]

# ------------------------------------------------------- sample registries --
# SAMPLE DATA — illustrative only, not operational records.
GLOF_LAKES = [
    {"id": "imja",   "name_en": "Imja Tsho",  "name_ne": "इम्जा छो",   "lat": 27.8986, "lon": 86.9108,
     "status_en": "High watch", "status_ne": "उच्च निगरानी", "level": "warning",
     "note_en": "Sample record — production uses ICIMOD inventory + sensor data.",
     "downstream_en": "Dingboche, Chhukhung", "data_label": "sample"},
    {"id": "tsho-rolpa", "name_en": "Tsho Rolpa", "name_ne": "छो रोल्पा", "lat": 27.8667, "lon": 86.4667,
     "status_en": "High watch", "status_ne": "उच्च निगरानी", "level": "warning",
     "note_en": "Sample record — production uses ICIMOD inventory + sensor data.",
     "downstream_en": "Bedding, Na", "data_label": "sample"},
    {"id": "thulagi", "name_en": "Thulagi", "name_ne": "ठुलागी", "lat": 28.4939, "lon": 84.4744,
     "status_en": "Moderate watch", "status_ne": "मध्यम निगरानी", "level": "watch",
     "note_en": "Sample record — production uses ICIMOD inventory + sensor data.",
     "downstream_en": "Dharapani, Tal", "data_label": "sample"},
    {"id": "lower-barun", "name_en": "Lower Barun", "name_ne": "तल्लो बरुण", "lat": 27.7667, "lon": 87.1000,
     "status_en": "Moderate watch", "status_ne": "मध्यम निगरानी", "level": "watch",
     "note_en": "Sample record — production uses ICIMOD inventory + sensor data.",
     "downstream_en": "Barun valley settlements", "data_label": "sample"},
]

SHELTERS = [
    {"id": "tundikhel", "name_en": "Tundikhel Open Space", "name_ne": "टुँडिखेल खुला क्षेत्र",
     "lat": 27.7000, "lon": 85.3150, "district_en": "Kathmandu", "district_ne": "काठमाडौं",
     "capacity_en": "Sample — verify with local authority", "data_label": "sample"},
    {"id": "dasharath", "name_en": "Dasharath Stadium Grounds", "name_ne": "दशरथ रङ्गशाला",
     "lat": 27.6939, "lon": 85.3161, "district_en": "Kathmandu", "district_ne": "काठमाडौं",
     "capacity_en": "Sample — verify with local authority", "data_label": "sample"},
    {"id": "bhrikutimandap", "name_en": "Bhrikutimandap", "name_ne": "भृकुटीमण्डप",
     "lat": 27.7040, "lon": 85.3200, "district_en": "Kathmandu", "district_ne": "काठमाडौं",
     "capacity_en": "Sample — verify with local authority", "data_label": "sample"},
    {"id": "chyasal", "name_en": "Chyasal Ground", "name_ne": "च्यासल मैदान",
     "lat": 27.6670, "lon": 85.3250, "district_en": "Lalitpur", "district_ne": "ललितपुर",
     "capacity_en": "Sample — verify with local authority", "data_label": "sample"},
]

ACTIONS = {
    "flood": {
        "en": ["Move to higher ground away from rivers",
               "Do not walk or drive through flooded roads",
               "Keep phone charged and documents dry"],
        "ne": ["नदीबाट टाढा अग्लो स्थानमा जानुहोस्",
               "डुबेका बाटोमा नहिँड्नुहोस्, गाडी नचलाउनुहोस्",
               "फोन चार्ज र कागजात सुख्खा राख्नुहोस्"]},
    "landslide": {
        "en": ["Leave slopes and cracked houses immediately",
               "Avoid travel on hill highways in heavy rain",
               "Listen for unusual rumbling sounds"],
        "ne": ["भिर र चर्केका घर तुरुन्त छोड्नुहोस्",
               "भारी वर्षामा पहाडी राजमार्ग यात्रा नगर्नुहोस्",
               "असामान्य गडगडाहट सुनेमा सतर्क रहनुहोस्"]},
    "earthquake": {
        "en": ["Drop, cover and hold on during shaking",
               "Move to open space after shaking stops",
               "Check gas and electricity; expect aftershocks"],
        "ne": ["कम्पन हुँदा निहुरनुहोस्, छोप्नुहोस्, समात्नुहोस्",
               "कम्पन रोकिएपछि खुला ठाउँमा जानुहोस्",
               "ग्यास र बिजुली जाँच्नुहोस्; परकम्प आउन सक्छ"]},
    "glof": {
        "en": ["Move to high ground immediately — do not wait",
               "Follow the marked evacuation route uphill",
               "Warn neighbours as you move"],
        "ne": ["तुरुन्त अग्लो ठाउँमा जानुहोस् — नपर्खनुहोस्",
               "तोकिएको बाटो हुँदै उकालो जानुहोस्",
               "जाँदाजाँदै छिमेकीलाई खबर गर्नुहोस्"]},
}

LEVELS = ["low", "moderate", "high", "critical"]  # index = severity
LEVEL_NE = {"low": "सामान्य", "moderate": "मध्यम", "high": "उच्च", "critical": "अति उच्च"}

# ------------------------------------------------------------------ http ---
# Sandbox note: the VM's NO_PROXY list contains bracketed IPv6 entries that
# httpx's trust_env parsing chokes on, so we bypass env parsing and pass the
# egress proxy explicitly. On normal hosts (no proxy vars) this is a direct
# connection.
def _make_client(timeout):
    proxy = (os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
             or os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy"))
    kw = {"timeout": timeout, "trust_env": False}
    if proxy:
        kw["proxy"] = proxy
    # Egress proxy does TLS interception; its CA is in SSL_CERT_FILE on this VM.
    ca = os.environ.get("SSL_CERT_FILE")
    if ca and os.path.isfile(ca):
        kw["verify"] = ca
    return httpx.AsyncClient(**kw)

# ------------------------------------------------------------------ cache ---
_cache: dict = {}

def cache_get(key):
    entry = _cache.get(key)
    if entry and time.time() < entry["expires"]:
        return entry["data"]
    return None

def cache_set(key, data, ttl):
    _cache[key] = {"data": data, "expires": time.time() + ttl}

# ---------------------------------------------------------------- helpers ---
def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))

def in_nepal(lat, lon):
    return 26.0 <= lat <= 31.0 and 80.0 <= lon <= 89.0

async def fetch_usgs():
    """Live earthquake feed from USGS (free, no key). Cached 10 min."""
    hit = cache_get("usgs")
    if hit is not None:
        return hit, True
    url = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_month.geojson"
    async with _make_client(25) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        raw = resp.json()
    quakes = []
    for f in raw.get("features", []):
        p, g = f["properties"], f["geometry"]
        lon, lat, depth = g["coordinates"]
        quakes.append({
            "id": f["id"], "mag": p.get("mag"), "place": p.get("place"),
            "time": datetime.fromtimestamp(p["time"] / 1000, tz=timezone.utc).isoformat(),
            "lat": lat, "lon": lon, "depth_km": depth,
            "tsunami": bool(p.get("tsunami")), "url": p.get("url"),
            "in_nepal": in_nepal(lat, lon),
            "dist_to_kathmandu_km": round(haversine_km(lat, lon, 27.7172, 85.3240), 1),
        })
    quakes.sort(key=lambda q: q["time"], reverse=True)
    cache_set("usgs", quakes, 600)
    return quakes, False

async def fetch_weather():
    """Live forecast for all monitored cities from Open-Meteo (free, no key)."""
    hit = cache_get("weather")
    if hit is not None:
        return hit, True
    lats = ",".join(str(c["lat"]) for c in CITIES)
    lons = ",".join(str(c["lon"]) for c in CITIES)
    url = ("https://api.open-meteo.com/v1/forecast?latitude=" + lats + "&longitude=" + lons +
           "&current=temperature_2m,relative_humidity_2m,precipitation,weather_code,wind_speed_10m"
           "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,"
           "precipitation_probability_max&timezone=Asia%2FKathmandu&forecast_days=7")
    async with _make_client(25) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        raw = resp.json()
    data = raw if isinstance(raw, list) else [raw]
    out = {}
    for city, w in zip(CITIES, data):
        out[city["id"]] = {"city": city, "current": w.get("current", {}),
                           "daily": w.get("daily", {}), "data_label": "live"}
    cache_set("weather", out, 1800)
    return out, False

# ------------------------------------------------------------- risk engine --
def flood_level(rain72):
    if rain72 >= 100: return 3
    if rain72 >= 50: return 2
    if rain72 >= 25: return 1
    return 0

def landslide_level(rain72, hill):
    if not hill: return 0
    if rain72 >= 80: return 3
    if rain72 >= 40: return 2
    if rain72 >= 20: return 1
    return 0

async def compute_risk():
    """Transparent heuristic risk engine — MODEL label, not an official forecast."""
    weather, _ = await fetch_weather()
    quakes, _ = await fetch_usgs()
    now = time.time()
    results = []
    for city in CITIES:
        w = weather[city["id"]]
        daily = w["daily"]
        precips = (daily.get("precipitation_sum") or [])[:3]
        rain72 = round(sum(p or 0 for p in precips), 1)
        probs = (daily.get("precipitation_probability_max") or [])[:3]
        prob72 = max([p or 0 for p in probs] or [0])
        fl, ls = flood_level(rain72), landslide_level(rain72, city["hill"])
        # seismic: M4.5+ within 300 km in last 30 days
        recent = [q for q in quakes
                  if haversine_km(q["lat"], q["lon"], city["lat"], city["lon"]) <= 300]
        if len(recent) >= 3: seis = 2
        elif len(recent) >= 1: seis = 1
        else: seis = 0
        overall = max(fl, ls, seis)
        results.append({
            "city": city, "rain_72h_mm": rain72, "rain_prob_max": prob72,
            "flood": LEVELS[fl], "landslide": LEVELS[ls], "seismic": LEVELS[seis],
            "overall": LEVELS[overall], "overall_ne": LEVEL_NE[LEVELS[overall]],
            "recent_quakes_300km": len(recent),
            "forecast_dates": (daily.get("time") or [])[:7],
            "data_label": "model",
            "computed_at": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
        })
    results.sort(key=lambda r: LEVELS.index(r["overall"]), reverse=True)
    return results

async def build_alerts():
    """Generate alerts from live data + heuristic thresholds."""
    risk = await compute_risk()
    quakes, _ = await fetch_usgs()
    alerts, n = [], 0
    for r in risk:
        city = r["city"]
        for hazard, key in (("flood", "flood"), ("landslide", "landslide")):
            lvl = LEVELS.index(r[key])
            if lvl >= 2:  # high or critical
                n += 1
                sev = "warning" if lvl == 3 else "watch"
                alerts.append({
                    "id": f"{hazard}-{city['id']}-{n}",
                    "severity": sev, "hazard": hazard,
                    "area_en": city["name_en"], "area_ne": city["name_ne"],
                    "headline_en": f"{hazard.title()} {sev}: {city['name_en']} — {r['rain_72h_mm']} mm rain expected in 72h",
                    "headline_ne": f"{'बाढी' if hazard == 'flood' else 'पहिरो'} {'चेतावनी' if sev == 'warning' else 'निगरानी'}: {city['name_ne']} — ७२ घण्टामा {r['rain_72h_mm']} मिमि वर्षा",
                    "actions_en": ACTIONS[hazard]["en"], "actions_ne": ACTIONS[hazard]["ne"],
                    "issued_at": r["computed_at"], "source": "suraksha-heuristic",
                    "data_label": "model",
                })
    # earthquake alerts: M5.5+ inside Nepal in last 7 days (LIVE source)
    week_ago = time.time() - 7 * 86400
    for q in quakes:
        qt = datetime.fromisoformat(q["time"]).timestamp()
        if q["in_nepal"] and (q["mag"] or 0) >= 5.5 and qt >= week_ago:
            n += 1
            alerts.append({
                "id": f"earthquake-{q['id']}", "severity": "warning", "hazard": "earthquake",
                "area_en": q["place"] or "Nepal", "area_ne": "नेपाल",
                "headline_en": f"Earthquake M{q['mag']}: {q['place']}",
                "headline_ne": f"भूकम्प M{q['mag']}: {q['place']}",
                "actions_en": ACTIONS["earthquake"]["en"], "actions_ne": ACTIONS["earthquake"]["ne"],
                "issued_at": q["time"], "source": "usgs-live", "data_label": "live",
                "usgs_url": q["url"],
            })
    order = {"emergency": 0, "warning": 1, "watch": 2, "advisory": 3}
    alerts.sort(key=lambda a: order.get(a["severity"], 9))
    return alerts

# ------------------------------------------------------------- messaging ----
class BroadcastIn(BaseModel):
    channel: str = "sms"          # sms | whatsapp | push
    area_en: str = "Kathmandu"
    message_en: str
    message_ne: str = ""

async def dispatch_broadcast(body: BroadcastIn):
    """Alert dissemination adapter. Console provider in prototype;
    set MESSAGING_API_URL + MESSAGING_API_KEY to forward to the real
    unified messaging API (POST /v1/messages)."""
    url = os.environ.get("MESSAGING_API_URL")
    key = os.environ.get("MESSAGING_API_KEY")
    payload = {"channel": body.channel, "area": body.area_en,
               "message_en": body.message_en, "message_ne": body.message_ne}
    if url and key:
        try:
            async with _make_client(15) as client:
                resp = await client.post(url.rstrip("/") + "/v1/messages",
                                         json=payload,
                                         headers={"Authorization": f"Bearer {key}"})
                return {"status": "forwarded", "provider_status": resp.status_code,
                        "data_label": "live"}
        except Exception as e:  # noqa: BLE001 — prototype adapter
            return {"status": "provider_error", "detail": str(e)[:200],
                    "data_label": "live"}
    print(f"[suraksha-broadcast:{body.channel}] {body.area_en} :: {body.message_en}")
    return {"status": "simulated",
            "note": "Console provider — set MESSAGING_API_URL/KEY for real dispatch",
            "echo": payload, "data_label": "sample"}

# ------------------------------------------------------------------- app ----
app = FastAPI(title="Suraksha API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])

static_dir = os.path.join(BASE_DIR, "static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
def index():
    return FileResponse(os.path.join(static_dir, "index.html"))

@app.get("/api/health")
def health():
    return {"status": "ok", "service": "suraksha", "version": "0.1.0",
            "time": datetime.now(timezone.utc).isoformat()}

@app.get("/api/cities")
def cities():
    return {"cities": CITIES, "data_label": "live"}

@app.get("/api/earthquakes")
async def earthquakes(days: int = Query(30, ge=1, le=30),
                      min_magnitude: float = Query(4.5, ge=0),
                      nepal_only: bool = False):
    try:
        quakes, cached = await fetch_usgs()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"USGS unreachable: {str(e)[:150]}")
    cutoff = time.time() - days * 86400
    out = [q for q in quakes
           if (q["mag"] or 0) >= min_magnitude
           and datetime.fromisoformat(q["time"]).timestamp() >= cutoff
           and (not nepal_only or q["in_nepal"])]
    return {"count": len(out), "earthquakes": out[:500], "cached": cached,
            "source": "USGS Earthquake Hazards Program", "data_label": "live"}

@app.get("/api/weather")
async def weather(city: str = Query("kathmandu")):
    try:
        data, cached = await fetch_weather()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Open-Meteo unreachable: {str(e)[:150]}")
    if city not in data:
        raise HTTPException(404, f"Unknown city '{city}'")
    w = data[city]
    return {"city": w["city"], "current": w["current"], "daily": w["daily"],
            "cached": cached, "source": "Open-Meteo", "data_label": "live"}

@app.get("/api/risk")
async def risk():
    try:
        results = await compute_risk()
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Risk engine failed: {str(e)[:150]}")
    return {"cities": results,
            "method": "heuristic thresholds on 72h forecast precipitation — prototype, not an official forecast",
            "data_label": "model"}

@app.get("/api/alerts")
async def alerts():
    try:
        items = await build_alerts()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Alert engine failed: {str(e)[:150]}")
    return {"count": len(items), "alerts": items}

@app.get("/api/glof/lakes")
def glof_lakes():
    return {"count": len(GLOF_LAKES), "lakes": GLOF_LAKES,
            "notice": "Sample registry — production uses ICIMOD inventory + lake sensors"}

@app.get("/api/shelters")
def shelters():
    return {"count": len(SHELTERS), "shelters": SHELTERS,
            "notice": "Sample data — verify capacity with local authorities"}

@app.get("/api/overview")
async def overview():
    alerts_list = await build_alerts()
    quakes, _ = await fetch_usgs()
    by_sev = {}
    for a in alerts_list:
        by_sev[a["severity"]] = by_sev.get(a["severity"], 0) + 1
    return {"alerts_by_severity": by_sev,
            "active_alerts": len(alerts_list),
            "earthquakes_30d_m45": len(quakes),
            "cities_monitored": len(CITIES),
            "glof_lakes_watched": len(GLOF_LAKES)}

@app.post("/api/broadcast")
async def broadcast(body: BroadcastIn):
    return await dispatch_broadcast(body)

async def _refresh_loop():
    while True:
        try:
            await fetch_usgs(); await fetch_weather()
        except Exception:  # noqa: BLE001 — background best-effort
            pass
        await asyncio.sleep(900)

@app.on_event("startup")
async def startup():
    asyncio.create_task(_refresh_loop())
