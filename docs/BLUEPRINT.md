# Suraksha (सुरक्षा) — Disaster Management & Early Warning System for Nepal

**System Architecture Blueprint — v0.2 (2026-10-30)**
**Author:** Samir Khadka · **Status:** Blueprint + working system (live on Render)

### v0.2 changelog (2026-10-30, "make it real")
- **NEMRC live**: `/api/earthquakes/nepal` scrapes Nepal's own seismic catalog (catches M4+ local events USGS misses); violet layer on the map.
- **GLOF verified**: registry replaced with the real ICIMOD + UNDP + Government of Nepal 2026 assessment — 6 priority lakes (Imja Tsho, Tsho Rolpa, Thulagi, Lower Barun, Lumding Tsho, Hongu 2) with real mitigation facts (2016 Imja lowering, 2000 Tsho Rolpa drainage, $49.9M Sanjeevani Project 2026–2033); `/api/glof/summary` carries the 47/21/25/1 stats.
- **Shelters verified**: 10 real open spaces from the IOM + Ministry of Home Affairs 83-space designation (2013, Nepal Gazette), incl. 2015 camp usage; coordinates approximate.
- Data-honesty labels extended: `live` / `verified` / `model` / `sample` (sample now ~zero).
- DHM river-watch socket.io endpoint reverse-engineered (`/gss/socket.io`, events `river_watch`/`rainfall_watch`) but sandbox proxy blocks WS POSTs — production integration planned.

### v0.3 changelog (2026-10-30, "all 77 districts")
- **Coverage expanded from 9 cities to all 77 districts** (Samir's direction): every district has HQ coordinates, hill/Terai flag, province grouping, and bilingual names. Weather (Open-Meteo batch, MET Norway fallback with 10-way concurrency), risk engine, alerts, and map all run on 77 districts.
- **Frontend**: district picker is now a province-grouped dropdown; risk table defaults to "needs attention" (moderate+) with a show-all-77 toggle, scrollable with sticky header; forecast header names the selected district; stat card reads "Districts monitored: 77".
- New endpoints: `/api/districts` (alias `/api/cities` kept), `/api/weather?district=<id>` (alias `?city=` kept).

### v0.4 changelog (2026-10-30, "make the Planned badges real")
- **DHM river gauges LIVE** (`/api/rivers`, verified 2026-10-30 ~23:15 NPT — 337 stations): DHM's hydrology.gov.np real-time feed, hand-rolled engine.io v4 client over a **direct `wss://` WebSocket** (`websockets` lib, Origin header). Hard-won findings: (1) the server kills polling-only sessions immediately after the socket.io `40` ack — the WS upgrade is mandatory, so python-socketio's default polling-first flow dies with 'Unexpected connection error'; (2) initial connect emits `client_request`→`river_test` (`river_watch` is reconnect-only); server replies on `river_test`/`rainfall_watch`/`river_discharge`; (3) engine.io pings (`2`) must be ponged (`3`) or the session is killed at pingTimeout; (4) level mapping must be prefix-based — 'BELOW WARNING LEVEL' contains 'WARNING' (naive substring → every station 'warning'); (5) sensor-fault filter: levels >100 m flagged suspect (a live 100008.5 m reading seen). 15-min cache, honest 502 when the feed yields nothing.
- **Incident reports LIVE** (`/api/incidents`): GDACS global disaster API filtered to Nepal (free, no key) — e.g. the 2026-08-26 Red-alert Bhotekoshi-Trishuli flood. New "Disaster Incidents" section with GDACS report links.
- **Sentinel-2 LIVE** (`/api/glof/satellite`): Copernicus OData (free, no key) — latest low-cloud (<30%, fallback <60%) Sentinel-2 scene per priority lake; shown on each GLOF card ("last clear satellite view"). Pixel-level NDWI change detection stays v2.
- **Source health** (`/api/sources/status`): every upstream probed from the production server; rendered as live dots in Data Sources. BIPAD confirmed unreachable from production too → line now reads Planned with the honest reason; DHM + GDACS used directly instead.

---

## 1. Mission

Minimize the effects and losses of disasters in Nepal — flood, landslide, earthquake,
and glacial lake outburst floods (GLOF) — driving **preventable human deaths toward zero**
through early warning, clear public communication, and coordinated response.

Deaths in Nepal's disasters are rarely caused by lack of courage; they are caused by
lack of *lead time*. The 2015 Gorkha earthquake killed ~9,000 people; the August 2024
Thame GLOF destroyed homes in minutes with almost no warning; every monsoon, floods and
landslides kill hundreds across the hills and Terai. Suraksha exists to buy minutes,
hours, and days — and to make sure those minutes reach the right people in a language
they understand.

### Design principles

1. **Lead time is the product.** Every architectural choice is judged by whether it
   shortens the path from detection to a villager's phone.
2. **Free-first.** Every dependency must have a free tier that covers national scale.
   No paid gate between a sensor reading and a warning.
3. **Bilingual by default.** Nepali (नेपाली) first, English second — alerts a farmer in
   Dolakha can't read are not alerts.
4. **Honest data labels.** Live data, model estimates, and sample/illustrative data are
   always visually distinguished. A prototype risk score must never be mistaken for an
   official DHM/NDRRMA forecast.
5. **Degrade gracefully.** When the internet dies (it does, in disasters), SMS, FM radio
   hooks, and cached offline data keep working.
6. **Build on Nepal's institutions, don't duplicate them.** BIPAD/NDRRMA, DHM, and the
   National Earthquake Monitoring & Research Centre (NEMRC) are the authorities;
   Suraksha is the fast, modern interface layer on top.

---

## 2. Hazard scope & Nepal context

| Hazard | Nepal reality | Warning window available |
|---|---|---|
| Monsoon / flash flood | Terai inundation, riverbank erosion; Koshi, Narayani, Karnali basins | Hours–days (rainfall forecast + river gauges) |
| Landslide | Hill highways (Araniko, Prithvi), monsoon slope failures | Hours (rainfall thresholds) to minutes |
| Earthquake | Himalayan arc; 2015 Gorkha M7.8; aftershock sequences | Seconds (EEW) to none — preparedness is the product |
| GLOF | 20+ potentially dangerous glacial lakes (Imja Tsho, Tsho Rolpa, Thulagi, Lower Barun); Thame 2024 proved the threat is current | Minutes–hours with lake sensors; days with satellite monitoring |

**Cascading hazards** are first-class: earthquake → landslide → landslide-dammed lake →
outburst flood. The risk engine models chains, not isolated events.

---

## 3. System architecture

Five layers, event-driven. Data flows one way — from ground truth to human action —
with feedback loops for verification.

```
┌─────────────────────────────────────────────────────────────────┐
│ LAYER 1 — INGESTION (sensors, APIs, satellites, people)          │
│  USGS eq feed · Open-Meteo · DHM gauges (via BIPAD) · NEMRC      │
│  IoT lake-level sensors (LoRa) · Sentinel-2 imagery · citizens   │
└──────────────────────────────┬──────────────────────────────────┘
                               │ normalized events (CloudEvents)
┌──────────────────────────────▼──────────────────────────────────┐
│ LAYER 2 — RISK ENGINE (stream processing + models)              │
│  Threshold rules (v0.1) → statistical models (v1) → ML (v2)      │
│  Flood · Landslide · Seismic · GLOF sub-engines + cascade model  │
└──────────────────────────────┬──────────────────────────────────┘
                               │ scored risk events (0–100 + level)
┌──────────────────────────────▼──────────────────────────────────┐
│ LAYER 3 — ALERT ORCHESTRATION (decide who must know, now)        │
│  Severity classification · geo-targeting (district→ward)         │
│  Deduplication · escalation timers · bilingual message builder   │
└──────────────────────────────┬──────────────────────────────────┘
                               │ addressed alerts
┌──────────────────────────────▼──────────────────────────────────┐
│ LAYER 4 — DISSEMINATION (every channel that survives disaster)   │
│  SMS/WhatsApp (own messaging API) · push (FCM) · sirens (API)    │
│  FM radio ticker hook · IVR voice calls · dashboard banners      │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│ LAYER 5 — APPLICATIONS                                          │
│  Public dashboard (this prototype) · Responder console (v1)      │
│  Admin / NEOC liaison panel (v1) · Offline field app (v2)        │
└─────────────────────────────────────────────────────────────────┘
```

### Layer 1 — Ingestion

* **Pollers** (prototype: in-process scheduler; production: Celery beat / cron workers)
  pull each source on its natural cadence: USGS every 5 min, Open-Meteo every 30 min,
  DHM/BIPAD every 15 min.
* Every reading is normalized to a common `HazardEvent` schema
  `{source, hazard_type, location, time, measurements, confidence}` and appended to an
  immutable event log (PostgreSQL in production; SQLite/JSONL in prototype).
* **Citizen reports** (v1): geo-tagged flood/landslide/road-block reports with photo,
  triaged by a verification queue before they influence the risk score.

### Layer 2 — Risk engine

* **v0.1 (prototype, heuristic — labeled as such):** transparent threshold rules, e.g.
  72-hour forecast rainfall ≥ 50 mm → flood watch; ≥ 100 mm → flood warning.
  Heuristics are auditable and explainable — a feature, not a weakness, at this stage.
* **v1:** statistical models calibrated on DHM historical gauge data + ICIMOD landslide
  inventories.
* **v2:** ML (gradient boosting / LSTM on rainfall sequences) for flash-flood nowcasting;
  InSAR + Sentinel-2 change detection for GLOF lake growth.
* **Cascade model:** any M6+ earthquake in the hills raises landslide susceptibility for
  30 days within 100 km; any landslide report near a river raises downstream flood watch.

### Layer 3 — Alert orchestration

* Four severity levels: **Advisory (जानकारी)** → **Watch (निगरानी)** →
  **Warning (चेतावनी)** → **Emergency (आपतकालीन)**.
* Geo-targeting down to municipality/ward using official admin boundary data.
* Escalation timers: an unacknowledged Warning auto-escalates; duplicate alerts within
  the window are merged, not re-sent (alert fatigue kills trust).
* Every alert carries: what, where, until-when, what-to-do (3 actions max), and source.

### Layer 4 — Dissemination

* **Primary:** SMS + WhatsApp through the project's own messaging API
  (console provider in prototype → Meta/Twilio in production; SMS to arbitrary numbers
  is never free — budget this line item honestly).
* **Secondary:** FCM push, dashboard banners, FM radio ticker API hook, IVR voice calls
  in Nepali for illiterate recipients (v2).
* **Last resort:** siren-system API integration at municipal level; cached offline
  bulletins in the field app.

### Layer 5 — Applications

* **Public dashboard** (this prototype): live map, hazard feeds, 7-day outlook,
  shelter directory, "what to do" guides per hazard.
* **Responder console** (v1): incident board, resource inventory (link to BIPAD),
  team dispatch, acknowledgment tracking.
* **Admin / NEOC liaison** (v1): threshold tuning, broadcast composer with approval
  workflow (two-person rule for Emergency level), audit log.

---

## 4. API & data source catalog

| Source | Provides | Cost | Auth | Verification status (2026-10-30) |
|---|---|---|---|---|
| USGS Earthquake Hazards Program | Real-time global earthquakes (GeoJSON feeds) | Free | None | ✅ LIVE in prototype |
| Open-Meteo | Current + 16-day forecast, hourly precipitation | Free | None | ✅ LIVE in prototype |
| BIPAD (bipadportal.gov.np/api) | Nepal incidents, DHM rain/river gauges, NEMRC quakes | Free | None (public) | ❌ Unreachable from sandbox AND production (probed) — DHM direct + GDACS used instead |
| DHM Nepal (via BIPAD) | River water levels, rainfall stations, flood forecast | Free | Via BIPAD | ⚠️ Via BIPAD integration |
| NEMRC (seismonepal.gov.np) | Nepal earthquake catalog (ML events USGS misses) | Free | None (scraped) | ✅ LIVE in v0.2 (`/api/earthquakes/nepal`) |
| ICIMOD + UNDP + GoN (2026 PDGL assessment) | 47 dangerous glacial lakes (21 Nepal / 25 Tibet / 1 India); Sanjeevani priority lakes | Free | Published | ✅ LIVE in v0.2 (verified registry, `/api/glof/lakes` + `/api/glof/summary`) |
| IOM + MoHA (2013, Nepal Gazette) | 83 designated open spaces / shelters | Free | Published | ✅ LIVE in v0.2 (verified registry, `/api/shelters`) |
| DHM hydrology.gov.np (socket.io `/gss/socket.io`) | Real-time river water levels (337 stations) | Free | None (WS) | ✅ LIVE in v0.4 (`/api/rivers`, verified 2026-10-30). Direct-wss engine.io client (server kills polling-only sessions); initial connect emits `client_request`→`river_test`; ping/pong keepalive; prefix-based level mapping; >100 m sensor-fault filter. |
| Sentinel-2 / Copernicus | Lake area change detection | Free | Account | 🔜 v2 |
| GDACS | Global disaster alerts (RSS/API) | Free | None | 🔜 v1 (backup feed) |
| Own messaging API | SMS/WhatsApp/RCS + OTP dispatch | Free (console) / provider rates | API key | ✅ Adapter in prototype (console), live keys = production step |
| FCM | Mobile push notifications | Free | Firebase | 🔜 v1 |
| OpenWeatherMap | Fallback weather | Free tier | Key | 🔜 fallback only |

---

## 5. Module designs

### 5.1 Earthquake module
USGS feed (M4.5+ 30-day, M2.5+ 7-day for Nepal bbox 26–31°N, 80–89°E) → map markers
scaled by magnitude, depth-colored. "Felt it?" crowdsource button (v1). Preparedness
content: drop-cover-hold, 72-hour kit, building-retrofit links. Earthquake early warning
(seconds of lead time) is a v2 research track — Japan/Mexico-style EEW needs dense
seismometer networks Nepal doesn't have yet; the honest v0.1 product is *rapid
situational awareness + preparedness*, not prediction.

### 5.2 Flood module
72-hour precipitation forecast per basin-city + DHM river gauge levels (production) →
flood watch/warning per district. Monsoon-season mode (June–September) tightens
thresholds automatically. Terai inundation maps (v2, with DHM).

### 5.3 Landslide module
Rainfall-intensity × slope-susceptibility heuristic (v0.1) → susceptibility raster from
ICIMOD inventories (v1). Highway-corridor watch (Araniko, Prithvi, Muglin–Narayangadh)
with citizen road-block reports.

### 5.4 GLOF watch module
The signature Nepal module. Lake registry (Imja Tsho, Tsho Rolpa, Thulagi, Lower Barun,
Lumding + ICIMOD's full dangerous-lake list in v1) with: satellite area trend (v2),
**lake-level + moraine sensors via LoRa** (production hardware track), downstream
village inundation polygons, and siren/SMS trigger chains. Thame 2024 is the reference
scenario the module is designed against: from sensor anomaly to downstream SMS in
under 5 minutes.

---

## 6. Data model (core entities)

`hazard_events` (immutable log) · `risk_scores` (district × hazard × time) ·
`alerts` (severity, geotarget, messages EN/NE, channel receipts) ·
`shelters` (open spaces, capacity, facilities) · `glof_lakes` (registry + readings) ·
`reports` (citizen, triage state) · `subscriptions` (phone/ward/hazard preferences) ·
`audit_log` (every Emergency broadcast, two-person approval).

---

## 7. Tech stack

| Concern | Prototype (v0.1, today) | Production (v1+) |
|---|---|---|
| API | FastAPI (Python) | FastAPI, horizontally scaled |
| DB | SQLite / JSONL cache | PostgreSQL + PostGIS + TimescaleDB |
| Queue/stream | In-process scheduler | Redis + Celery / Kafka |
| Frontend | Single-page app, Leaflet, no build step | React + TypeScript, PWA, offline-first |
| Maps | Leaflet + OpenStreetMap | + PostGIS vector tiles |
| i18n | EN/NE dictionary | EN/NE (+ Maithili/Bhojpuri v2) |
| Deploy | Render free / local uvicorn | Docker + K8s / Oracle Cloud free tier |
| Monitoring | UptimeRobot (existing) | + Prometheus/Grafana |

---

## 8. UI/UX design system

Light, calm, high-contrast — panic is the enemy of comprehension. Severity colors are
the only saturated elements on the page: 🟢 Advisory · 🟡 Watch · 🟠 Warning ·
🔴 Emergency. Every screen answers three questions in order: **Am I safe right now?
What is happening near me? What should I do?** Bilingual toggle persists. Data-source
badges on every number: LIVE / MODEL / SAMPLE.

---

## 9. Security & reliability

JWT + httpOnly cookies for responder/admin roles (same pattern as CricScore-v2);
rate-limited public API; alert-broadcast requires authenticated role + two-person
approval at Emergency level; immutable audit log; all PII (phone numbers) encrypted
at rest; no tracking on the public dashboard.

---

## 10. Roadmap

* **v0.1 (today):** blueprint + working prototype — live USGS + Open-Meteo, heuristic
  risk engine, dashboard, alert simulation via messaging-API adapter.
* **v1:** BIPAD/DHM live integration, responder console, citizen reports with triage,
  FCM push, real SMS via provider, district-level geo-targeting.
* **v2:** ML nowcasting, Sentinel-2 GLOF monitoring, LoRa lake-sensor pilot (2 lakes),
  IVR voice alerts, offline field app, Maithili/Bhojpuri.
* **Production:** NEOC liaison, municipal siren integration, national drill program.
  **The drill program is what converts warnings into zero deaths** — technology alone
  doesn't save anyone; practiced communities do.

---

## 11. Honest limitations

* Prototype risk scores are **transparent heuristics, not operational forecasts**.
  They must never be presented as DHM/NDRRMA guidance.
* GLOF early warning without in-situ sensors is monitoring, not warning — the sensor
  network is a hardware + permitting track, not just code.
* SMS to arbitrary numbers is never free; the dissemination budget is a real line item.
* Earthquake *prediction* is not a feature and never will be; the earthquake product
  is rapid awareness + preparedness.
* "Zero deaths" is an asymptote: the system minimizes *preventable* deaths from
  warning-amenable hazards (flood, landslide, GLOF). The last mile is always human —
  drills, trust, and local leadership.
