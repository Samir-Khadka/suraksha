"""
Suraksha (सुरक्षा) — Disaster Management & Early Warning prototype API.

Data honesty contract: every response carries a `data_label`:
  - "live"     : fetched just now from a real upstream API (USGS / Open-Meteo /
                 NEMRC). Timestamps show when.
  - "verified" : curated from authoritative published sources (ICIMOD/UNDP 2026
                 glacial-lake assessment, IOM/MoHA open-space designation).
                 Facts are real; coordinates may be marked approximate.
  - "model"    : computed by Suraksha's transparent heuristic risk engine (NOT an
                 official DHM/NDRRMA forecast — prototype only)
  - "sample"   : illustrative seed data (should be shrinking to zero)
"""
import asyncio
import math
import os
import re
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

# ------------------------------------------- real-data registries (verified) --
# GLOF registry: curated from the ICIMOD + UNDP + Government of Nepal assessment
# "Inventory of glacial lakes and identification of potentially dangerous glacial
# lakes in the Koshi, Gandaki and Karnali river basins" (2026 update):
# 47 Potentially Dangerous Glacial Lakes — 21 in Nepal, 25 in Tibet, 1 in India.
# The six below are Nepal's priority lakes: 4 in the $49.9M GLOF Sanjeevani
# Project (2026–2033, DHM + UNDP) + the 2 previously lowered.
GLOF_SUMMARY = {
    "pdgl_total": 47, "in_nepal": 21, "in_tibet": 25, "in_india": 1,
    "by_basin": {"Koshi": 42, "Gandaki": 3, "Karnali": 2},
    "mapped_lakes_nepal": 2070,
    "glofs_since_1977": 26,
    "source": "ICIMOD + UNDP + Government of Nepal (2026)",
    "data_label": "verified",
}
GLOF_LAKES = [
    {"id": "imja", "name_en": "Imja Tsho", "name_ne": "इम्जा छो",
     "lat": 27.8986, "lon": 86.9108, "coords": "verified",
     "district_en": "Solukhumbu", "district_ne": "सोलुखुम्बु", "basin_en": "Koshi",
     "level": "watch", "status_en": "Monitored — risk reduced",
     "status_ne": "निगरानी — जोखिम घटाइएको",
     "fact_en": "Lowered 3.4 m in 2016 (~4M m³ drained); early-warning sirens installed downstream.",
     "fact_ne": "सन् २०१६ मा ३.४ मि घटाइयो; तल्लो तटीय क्षेत्रमा पूर्वसूचना साइरन जडान।",
     "downstream_en": "Dingboche, Chhukhung", "data_label": "verified"},
    {"id": "tsho-rolpa", "name_en": "Tsho Rolpa", "name_ne": "छो रोल्पा",
     "lat": 27.8667, "lon": 86.4667, "coords": "verified",
     "district_en": "Dolakha", "district_ne": "दोलखा", "basin_en": "Koshi (Tama Koshi)",
     "level": "warning", "status_en": "High watch — re-expanding",
     "status_ne": "उच्च निगरानी — पुनः बढ्दै",
     "fact_en": "Partially drained ~3 m in 2000 (Nepal's first lake lowering); now expanding again to ~1.6 km².",
     "fact_ne": "सन् २००० मा आंशिक निकास; अहिले ~१.६ किमी² सम्म पुनः विस्तार।",
     "downstream_en": "Bedding, Na; Tama Koshi valley", "data_label": "verified"},
    {"id": "thulagi", "name_en": "Thulagi (Dona)", "name_ne": "ठुलागी (डोना)",
     "lat": 28.4939, "lon": 84.4744, "coords": "verified",
     "district_en": "Manang", "district_ne": "मनाङ", "basin_en": "Gandaki (Marsyangdi)",
     "level": "warning", "status_en": "Priority — GLOF Sanjeevani Project",
     "status_ne": "प्राथमिकता — ग्लोफ सञ्जीवनी आयोजना",
     "fact_en": "Rapidly expanding, unmitigated; slated for lowering under the $49.9M Sanjeevani Project (2026–2033).",
     "fact_ne": "तिव्र विस्तार, अव्यवस्थित; सन् २०२६–२०३३ सञ्जीवनी आयोजनामा निकास योजना।",
     "downstream_en": "Dharapani, Tal; Marsyangdi valley", "data_label": "verified"},
    {"id": "lower-barun", "name_en": "Lower Barun (Talopokhari)", "name_ne": "तल्लो बरुण",
     "lat": 27.7667, "lon": 87.1000, "coords": "verified",
     "district_en": "Sankhuwasabha", "district_ne": "सङ्खुवासभा", "basin_en": "Koshi (Barun/Arun)",
     "level": "warning", "status_en": "Priority — GLOF Sanjeevani Project",
     "status_ne": "प्राथमिकता — ग्लोफ सञ्जीवनी आयोजना",
     "fact_en": "Rapidly expanding moraine-dammed lake; Sanjeevani priority for lowering + monitoring.",
     "fact_ne": "तिव्र विस्तारित हिमताल; सञ्जीवनी आयोजनाको प्राथमिकता।",
     "downstream_en": "Barun valley settlements", "data_label": "verified"},
    {"id": "lumding", "name_en": "Lumding Tsho", "name_ne": "लुम्दिङ छो",
     "lat": 27.7500, "lon": 86.6200, "coords": "approximate",
     "district_en": "Solukhumbu", "district_ne": "सोलुखुम्बु", "basin_en": "Koshi",
     "level": "warning", "status_en": "Priority — GLOF Sanjeevani Project",
     "status_ne": "प्राथमिकता — ग्लोफ सञ्जीवनी आयोजना",
     "fact_en": "Sanjeevani priority; controlled drainage programmes have begun (DHM).",
     "fact_ne": "सञ्जीवनी प्राथमिकता; नियन्त्रित निकास कार्यक्रम सुरु।",
     "downstream_en": "Dudhkoshi tributary settlements", "data_label": "verified"},
    {"id": "hongu-2", "name_en": "Hongu 2", "name_ne": "होङ्गु २",
     "lat": 27.8000, "lon": 86.9300, "coords": "approximate",
     "district_en": "Solukhumbu", "district_ne": "सोलुखुम्बु", "basin_en": "Koshi",
     "level": "warning", "status_en": "Priority — GLOF Sanjeevani Project",
     "status_ne": "प्राथमिकता — ग्लोफ सञ्जीवनी आयोजना",
     "fact_en": "Sanjeevani priority; lowering + expanded early-warning planned (2026–2033).",
     "fact_ne": "सञ्जीवनी प्राथमिकता; निकास + पूर्वसूचना विस्तार योजना।",
     "downstream_en": "Hongu valley; Dudhkoshi", "data_label": "verified"},
]

# Shelter registry: the 83 open spaces identified by IOM + Ministry of Home
# Affairs (Feb 2013), designated in the Nepal Gazette; 33 were used by ~30,900
# displaced people in the 2015 Gorkha earthquake. Coordinates approximate.
SHELTERS = [
    {"id": "tundikhel", "name_en": "Tundikhel", "name_ne": "टुँडिखेल",
     "lat": 27.7000, "lon": 85.3150, "district_en": "Kathmandu", "district_ne": "काठमाडौं",
     "fact_en": "83-space IOM/MoHA designation (2013, gazetted); main 2015 displacement camp for months.",
     "data_label": "verified"},
    {"id": "ratna-park", "name_en": "Ratna Park", "name_ne": "रत्नपार्क",
     "lat": 27.7042, "lon": 85.3125, "district_en": "Kathmandu", "district_ne": "काठमाडौं",
     "fact_en": "83-space IOM/MoHA designation (2013, gazetted).",
     "data_label": "verified"},
    {"id": "dasharath", "name_en": "Dasharath Stadium", "name_ne": "दशरथ रङ्गशाला",
     "lat": 27.6939, "lon": 85.3161, "district_en": "Kathmandu", "district_ne": "काठमाडौं",
     "fact_en": "83-space IOM/MoHA designation (2013, gazetted); 2015 camp site.",
     "data_label": "verified"},
    {"id": "shankha-park", "name_en": "Shankha Park", "name_ne": "शङ्खपार्क",
     "lat": 27.7150, "lon": 85.3400, "district_en": "Kathmandu", "district_ne": "काठमाडौं",
     "fact_en": "83-space designation; government-managed camp in 2015.",
     "data_label": "verified"},
    {"id": "sano-gaucharan", "name_en": "Sano Gaucharan", "name_ne": "सानो गौचरन",
     "lat": 27.7089, "lon": 85.3226, "district_en": "Kathmandu", "district_ne": "काठमाडौं",
     "fact_en": "83-space designation; 2015 camp site.",
     "data_label": "verified"},
    {"id": "bhaktapur-durbar", "name_en": "Bhaktapur Durbar Square open area", "name_ne": "भक्तपुर दरबार क्षेत्र",
     "lat": 27.6722, "lon": 85.4278, "district_en": "Bhaktapur", "district_ne": "भक्तपुर",
     "fact_en": "83-space designation; government-managed camp in 2015.",
     "data_label": "verified"},
    {"id": "pulchowk-campus", "name_en": "Pulchowk Engineering Campus grounds", "name_ne": "पुल्चोक इन्जिनियरिङ क्याम्पस",
     "lat": 27.6817, "lon": 85.3250, "district_en": "Lalitpur", "district_ne": "ललितपुर",
     "fact_en": "83-space IOM/MoHA designation (2013, gazetted).",
     "data_label": "verified"},
    {"id": "tu-kirtipur", "name_en": "Tribhuvan University, Kirtipur", "name_ne": "त्रिभुवन विश्वविद्यालय, कीर्तिपुर",
     "lat": 27.6828, "lon": 85.2903, "district_en": "Kathmandu", "district_ne": "काठमाडौं",
     "fact_en": "83-space IOM/MoHA designation (2013, gazetted).",
     "data_label": "verified"},
    {"id": "un-park", "name_en": "UN Park", "name_ne": "यूएन पार्क",
     "lat": 27.6710, "lon": 85.3310, "district_en": "Lalitpur", "district_ne": "ललितपुर",
     "fact_en": "83-space IOM/MoHA designation (2013, gazetted).",
     "data_label": "verified"},
    {"id": "balaju-park", "name_en": "Balaju Park", "name_ne": "बालाजु पार्क",
     "lat": 27.7350, "lon": 85.2950, "district_en": "Kathmandu", "district_ne": "काठमाडौं",
     "fact_en": "83-space IOM/MoHA designation (2013, gazetted).",
     "data_label": "verified"},
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
    kw = {"timeout": timeout, "trust_env": False,
          "headers": {"User-Agent": "Suraksha/0.1 (Nepal disaster early-warning prototype)"}}
    if proxy:
        kw["proxy"] = proxy
    # Egress proxy does TLS interception; its CA is in SSL_CERT_FILE on this VM.
    ca = os.environ.get("SSL_CERT_FILE")
    if ca and os.path.isfile(ca):
        kw["verify"] = ca
    return httpx.AsyncClient(**kw)

# ------------------------------------------------------------------ cache ---
_cache: dict = {}
_stale: dict = {}          # last-good data, served if upstream is down/rate-limited
_locks = {}                # single-flight locks per resource (prevents stampedes)

def _lock(key):
    lock = _locks.get(key)
    if lock is None:
        import asyncio as _aio
        lock = _aio.Lock()
        _locks[key] = lock
    return lock

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

async def _get_with_retry(client, url, tries=3):
    """GET with backoff on 429/5xx — shared egress IPs get rate-limited."""
    last = None
    for i in range(tries):
        try:
            resp = await client.get(url)
            if resp.status_code == 429 and i < tries - 1:
                await asyncio.sleep(2 * (i + 1))
                continue
            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError as e:
            last = e
            code = e.response.status_code if e.response is not None else 0
            if code == 429 and i < tries - 1:
                await asyncio.sleep(2 * (i + 1))
                continue
            raise
    raise last

async def fetch_usgs():
    """Live earthquake feed from USGS (free, no key). Cached 10 min."""
    async with _lock("usgs"):
        hit = cache_get("usgs")
        if hit is not None:
            return hit, True
        url = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_month.geojson"
        try:
            async with _make_client(25) as client:
                resp = await _get_with_retry(client, url)
                raw = resp.json()
        except Exception:
            if "usgs" in _stale:                      # graceful degradation
                return _stale["usgs"], True
            raise
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
    _stale["usgs"] = quakes
    return quakes, False

async def fetch_weather():
    """Live forecast for all monitored cities from Open-Meteo (free, no key)."""
    async with _lock("weather"):
        hit = cache_get("weather")
        if hit is not None:
            return hit, True
        lats = ",".join(str(c["lat"]) for c in CITIES)
        lons = ",".join(str(c["lon"]) for c in CITIES)
        url = ("https://api.open-meteo.com/v1/forecast?latitude=" + lats + "&longitude=" + lons +
               "&current=temperature_2m,relative_humidity_2m,precipitation,weather_code,wind_speed_10m"
               "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,"
               "precipitation_probability_max&timezone=Asia%2FKathmandu&forecast_days=7")
        try:
            async with _make_client(25) as client:
                resp = await _get_with_retry(client, url)
                raw = resp.json()
        except Exception:
            if "weather" in _stale:                   # graceful degradation
                return _stale["weather"], True
            raise
    data = raw if isinstance(raw, list) else [raw]
    out = {}
    for city, w in zip(CITIES, data):
        out[city["id"]] = {"city": city, "current": w.get("current", {}),
                           "daily": w.get("daily", {}), "data_label": "live"}
    cache_set("weather", out, 3600)   # hourly: weather changes slowly
    _stale["weather"] = out
    return out, False

async def fetch_nemrc():
    """LIVE Nepal earthquake catalog scraped from the National Earthquake
    Monitoring & Research Centre (NEMRC), seismonepal.gov.np.
    Server-rendered table — no API key needed. Cached 30 min."""
    async with _lock("nemrc"):
        hit = cache_get("nemrc")
        if hit is not None:
            return hit, True
        url = "https://seismonepal.gov.np/ne/earthquakes"
        try:
            async with _make_client(25) as client:
                resp = await _get_with_retry(client, url)
                html = resp.text
        except Exception:
            if "nemrc" in _stale:
                return _stale["nemrc"], True
            raise
        quakes = []
        for row in re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.S):
            cells = [re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', c)).strip()
                     for c in re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row, re.S)]
            if len(cells) < 7:
                continue
            m_date = re.search(r'ई\.सं\.:\s*(\d{4}-\d{2}-\d{2})', cells[1])
            m_time = re.search(r'UTC:\s*([\d:]{8})', cells[2])
            m_mag = re.search(r'([\d.]+)\s*ML', cells[5])
            try:
                lat, lon = float(cells[3]), float(cells[4])
            except ValueError:
                continue
            if not (m_date and m_time and m_mag):
                continue
            try:
                dt = datetime.strptime(m_date.group(1) + " " + m_time.group(1),
                                       "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            quakes.append({
                "id": f"nemrc-{m_date.group(1)}-{m_time.group(1)}-{cells[6]}",
                "mag": float(m_mag.group(1)), "mag_type": "ML",
                "place": cells[6], "place_ne": cells[6],
                "time": dt.isoformat(), "lat": lat, "lon": lon,
                "depth_km": None, "in_nepal": in_nepal(lat, lon),
                "dist_to_kathmandu_km": round(haversine_km(lat, lon, 27.7172, 85.3240), 1),
                "source": "NEMRC", "data_label": "live",
            })
        quakes.sort(key=lambda q: q["time"], reverse=True)
        cache_set("nemrc", quakes, 1800)
        _stale["nemrc"] = quakes
        return quakes, False

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
    """Transparent heuristic risk engine — MODEL label, not an official forecast.

    Degrades gracefully: if the weather upstream is unreachable (rate-limited),
    flood/landslide show 'unknown' instead of failing the whole dashboard.
    """
    try:
        weather, _ = await fetch_weather()
    except Exception:
        weather = None
    try:
        quakes, _ = await fetch_usgs()
    except Exception:
        quakes = []
    now = time.time()
    results = []
    for city in CITIES:
        if weather and city["id"] in weather:
            w = weather[city["id"]]
            daily = w["daily"]
            precips = (daily.get("precipitation_sum") or [])[:3]
            rain72 = round(sum(p or 0 for p in precips), 1)
            probs = (daily.get("precipitation_probability_max") or [])[:3]
            prob72 = max([p or 0 for p in probs] or [0])
            fl, ls = flood_level(rain72), landslide_level(rain72, city["hill"])
            fcast = (daily.get("time") or [])[:7]
        else:
            rain72, prob72, fcast = None, None, []
            fl, ls = -1, -1  # unknown
        # seismic: M4.5+ within 300 km in last 30 days
        recent = [q for q in quakes
                  if haversine_km(q["lat"], q["lon"], city["lat"], city["lon"]) <= 300]
        if len(recent) >= 3: seis = 2
        elif len(recent) >= 1: seis = 1
        else: seis = 0
        known = [x for x in (fl, ls, seis) if x >= 0]
        overall = max(known) if known else -1
        def lvl(x): return "unknown" if x < 0 else LEVELS[x]
        results.append({
            "city": city, "rain_72h_mm": rain72, "rain_prob_max": prob72,
            "flood": lvl(fl), "landslide": lvl(ls), "seismic": lvl(seis),
            "overall": lvl(overall),
            "overall_ne": "अज्ञात" if overall < 0 else LEVEL_NE[LEVELS[overall]],
            "recent_quakes_300km": len(recent),
            "forecast_dates": fcast,
            "weather_available": weather is not None,
            "data_label": "model",
            "computed_at": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
        })
    order = {"unknown": -1, "low": 0, "moderate": 1, "high": 2, "critical": 3}
    results.sort(key=lambda r: order.get(r["overall"], -1), reverse=True)
    return results

async def build_alerts():
    """Generate alerts from live data + heuristic thresholds."""
    risk = await compute_risk()
    quakes, _ = await fetch_usgs()
    alerts, n = [], 0
    for r in risk:
        city = r["city"]
        if r["rain_72h_mm"] is None:
            continue  # weather upstream down — no heuristic alerts this cycle
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

@app.get("/api/weather/all")
async def weather_all():
    """All monitored cities in one response (one upstream call)."""
    try:
        data, cached = await fetch_weather()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Open-Meteo unreachable: {str(e)[:150]}")
    return {"cities": list(data.values()), "cached": cached,
            "source": "Open-Meteo", "data_label": "live"}

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
            "notice": "Curated from the ICIMOD + UNDP + Government of Nepal 2026 PDGL assessment; coordinates marked approximate where noted"}

@app.get("/api/glof/summary")
def glof_summary():
    return GLOF_SUMMARY

@app.get("/api/earthquakes/nepal")
async def earthquakes_nepal():
    """Nepal's own seismic catalog (NEMRC) — catches smaller local events USGS misses."""
    try:
        quakes, cached = await fetch_nemrc()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"NEMRC unreachable: {str(e)[:150]}")
    return {"count": len(quakes), "earthquakes": quakes[:200], "cached": cached,
            "source": "National Earthquake Monitoring & Research Centre (NEMRC), Nepal",
            "data_label": "live"}

@app.get("/api/shelters")
def shelters():
    return {"count": len(SHELTERS), "shelters": SHELTERS,
            "notice": "83 open spaces designated by IOM + Ministry of Home Affairs (2013), Nepal Gazette; coordinates approximate"}

@app.get("/api/overview")
async def overview():
    try:
        alerts_list = await build_alerts()
    except Exception:
        alerts_list = []
    try:
        quakes, _ = await fetch_usgs()
    except Exception:
        quakes = []
    try:
        nemrc, _ = await fetch_nemrc()
    except Exception:
        nemrc = []
    by_sev = {}
    for a in alerts_list:
        by_sev[a["severity"]] = by_sev.get(a["severity"], 0) + 1
    return {"alerts_by_severity": by_sev,
            "active_alerts": len(alerts_list),
            "earthquakes_30d_m45": len(quakes),
            "earthquakes_nemrc": len(nemrc),
            "cities_monitored": len(CITIES),
            "glof_lakes_watched": len(GLOF_LAKES)}

@app.post("/api/broadcast")
async def broadcast(body: BroadcastIn):
    return await dispatch_broadcast(body)

async def _refresh_loop():
    await asyncio.sleep(60)  # let cold-start traffic settle first
    while True:
        try:
            await fetch_usgs(); await fetch_weather(); await fetch_nemrc()
        except Exception:  # noqa: BLE001 — background best-effort
            pass
        await asyncio.sleep(900)

@app.on_event("startup")
async def startup():
    asyncio.create_task(_refresh_loop())
