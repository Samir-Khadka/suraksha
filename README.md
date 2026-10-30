# Suraksha (सुरक्षा) — Disaster Management & Early Warning for Nepal

Bilingual EN/NE prototype: live earthquake + weather data, heuristic risk engine,
alert feed, GLOF watch, shelter directory, safety guides.

**Docs:** `docs/BLUEPRINT.md` — full system architecture (5 layers, API catalog,
module designs, roadmap v0.1 → production).

## Run locally

```bash
cd ~/workspace/suraksha
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8077
```

Open http://localhost:8077

## API

- `GET /api/health` — service status
- `GET /api/overview` — dashboard counters
- `GET /api/earthquakes?days=30&min_magnitude=4.5&nepal_only=false` — USGS live
- `GET /api/weather?city=kathmandu` — Open-Meteo live (9 monitored cities)
- `GET /api/risk` — heuristic district risk (MODEL — not an official forecast)
- `GET /api/alerts` — generated alerts, bilingual
- `GET /api/glof/lakes` — glacial lake registry (SAMPLE)
- `GET /api/shelters` — emergency shelters (SAMPLE)
- `POST /api/broadcast` — alert dispatch adapter (console in prototype;
  set `MESSAGING_API_URL` + `MESSAGING_API_KEY` to forward to the real
  unified messaging API)

## Data honesty

Every response carries `data_label`: `live` (USGS/Open-Meteo just fetched),
`model` (Suraksha heuristic — prototype only), `sample` (illustrative seeds).
