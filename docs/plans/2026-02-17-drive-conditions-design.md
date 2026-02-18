# Drive Conditions Webapp — Design Document

**Date:** 2026-02-17
**Status:** Approved

## Overview

A webapp that shows weather and road conditions along a driving route, with turn-by-turn instructions annotated with forecasted weather at each segment. Initially focused on routes within 8 hours of San Francisco.

## Architecture: Fetch-on-Demand

User enters origin/destination/departure time → backend fetches route → samples waypoints → fetches weather from 3 sources + Caltrans road conditions in parallel → assembles unified timeline → returns to frontend.

No caching or database for MVP. Every request fetches fresh data.

## Tech Stack

- **Backend:** Python Flask, asyncio + aiohttp for parallel API fetching
- **Frontend:** Vanilla JS, single HTML page, Google Maps JS API
- **Routing:** Google Routes API
- **Weather:** NWS + Open-Meteo + Tomorrow.io (all three)
- **Road conditions:** Caltrans CWWP2 (chain control + RWIS pavement sensors) — CA only

## Data Flow

```
User Input (origin, destination, departure time)
    │
    ▼
Flask Backend (/api/route-weather)
    │
    ├─► Google Routes API
    │       → encoded polyline + turn-by-turn steps + leg durations
    │
    ├─► Decode polyline → sample waypoints every ~15 miles
    │       → compute ETA at each waypoint (departure + cumulative duration)
    │
    ├─► For each waypoint, fetch in parallel:
    │       ├─ NWS api.weather.gov (hourly forecast + active alerts)
    │       ├─ Open-Meteo (snow depth, visibility, freezing level, precip, wind)
    │       └─ Tomorrow.io (road risk score, ice/snow accumulation)
    │
    ├─► Caltrans CWWP2 feeds (chain control + RWIS stations)
    │       → match stations/segments to route by proximity
    │
    └─► Assemble unified response:
            → turn-by-turn steps with weather at each segment
            → alerts/warnings along route
            → road condition overlays (chain control, pavement status)
```

## Backend Modules

| Module | Responsibility |
|--------|---------------|
| `app.py` | Flask app, routes, request handling |
| `routing.py` | Google Routes API client, polyline decoding, waypoint sampling |
| `weather_nws.py` | NWS forecast + alerts fetcher |
| `weather_openmeteo.py` | Open-Meteo hourly data fetcher |
| `weather_tomorrow.py` | Tomorrow.io forecast + road risk fetcher |
| `road_conditions.py` | Caltrans CWWP2 chain control + RWIS fetcher |
| `assembler.py` | Merges route + weather + road data into unified timeline |
| `config.py` | API keys, constants, waypoint sampling interval |

## API Endpoint

```
GET /api/route-weather?origin=San+Mateo,CA&destination=Mendocino,CA&departure=2026-02-21T06:00:00-08:00
```

### Response Structure

```json
{
  "route": {
    "summary": "US-101 N to CA-1 N",
    "total_distance_miles": 178,
    "total_duration_minutes": 215,
    "departure": "2026-02-21T06:00:00-08:00",
    "arrival": "2026-02-21T09:35:00-08:00",
    "polyline": "encoded_polyline_string"
  },
  "segments": [
    {
      "index": 0,
      "location": { "lat": 37.56, "lng": -122.32, "name": "San Mateo, CA" },
      "mile_marker": 0,
      "eta": "2026-02-21T06:00:00-08:00",
      "turn_instruction": "Head north on US-101 N",
      "weather": {
        "temperature_f": 48,
        "precipitation_probability": 20,
        "precipitation_mm_hr": 0.2,
        "precipitation_type": "rain",
        "rain_intensity": "light",
        "wind_speed_mph": 8,
        "wind_gusts_mph": 15,
        "wind_direction_deg": 270,
        "visibility_miles": 10,
        "fog_level": "none",
        "snow_depth_in": 0,
        "freezing_level_ft": 5200,
        "condition_text": "Partly Cloudy",
        "road_risk_score": 2,
        "road_risk_label": "Low"
      },
      "road_conditions": {
        "chain_control": null,
        "pavement_status": null,
        "alerts": []
      },
      "severity_score": 1,
      "severity_label": "green"
    }
  ],
  "alerts": [
    {
      "type": "Wind Advisory",
      "headline": "Wind Advisory until Saturday 6PM",
      "affected_segments": [8, 9, 10],
      "severity": "moderate"
    }
  ],
  "sources": ["NWS", "Open-Meteo", "Tomorrow.io", "Caltrans CWWP2"]
}
```

## Weather Data Merging

Three sources, each with a distinct role:

| Source | Primary role | Strengths |
|--------|-------------|-----------|
| Tomorrow.io | Road risk score, precipitation type | Road-specific risk scoring, ice/freezing rain detection |
| Open-Meteo | Numeric values (temp, wind, snow, visibility, freezing level) | Highest resolution numeric data, batch-friendly API |
| NWS | Alerts, condition text, human-readable forecast | Authoritative US source for weather warnings |

### Merge Rules

- `temperature_f`: Average of Open-Meteo and Tomorrow.io
- `wind_speed_mph`, `wind_gusts_mph`: Max of all sources (conservative for safety)
- `precipitation_probability`: Max of all sources (conservative)
- `precipitation_type`: Tomorrow.io preferred (best rain/snow/sleet/freezing rain distinction)
- `precipitation_mm_hr`: Open-Meteo (most granular)
- `visibility_miles`: Min of all sources (conservative)
- `snow_depth_in`, `freezing_level_ft`: Open-Meteo
- `condition_text`: NWS (best human-readable descriptions)
- `road_risk_score/label`: Tomorrow.io exclusively
- `alerts`: NWS exclusively

If any source fails, proceed with remaining sources. Response `sources` array indicates which contributed.

## Hazard Priority

Primary focus on rain, fog, and wind (the real hazards for coastal/NorCal routes). Snow/chains secondary — only relevant for Sierra routes.

| Hazard | Primary sources | Where it matters |
|--------|----------------|------------------|
| **Fog** | RWIS visibility sensors, Open-Meteo visibility, NWS fog advisories | CA-1 coast, Tule fog in Central Valley, bridges |
| **Rain intensity** | Open-Meteo precip mm/hr, Tomorrow.io precip type/intensity, NWS flood watches | CA-128, mountain roads, poor drainage areas |
| **Wind** | RWIS wind speed, Open-Meteo gusts, NWS wind advisories | CA-1 coastal bluffs, Altamont Pass, ridge roads |
| **Flooding/slides** | NWS flood/debris flow warnings, Caltrans closures | CA-1 (landslide-prone), mountain canyons |
| Snow/chains | Chain control feed, RWIS pavement temp | Sierra routes (I-80, US-50) only |

## Severity Scoring

For map color coding and segment classification:

- **Green (0-3):** Visibility > 5 mi, wind < 20 mph, precip < 0.5 mm/hr, no advisories
- **Yellow (4-6):** Visibility 1-5 mi (patchy fog), wind 20-35 mph, light rain 0.5-4 mm/hr, or advisory active
- **Red (7-10):** Visibility < 1 mi (dense fog), wind > 35 mph, heavy rain > 4 mm/hr, flooding/slide warning, or road closure

## Caltrans Road Conditions

### Chain Control (`ccStatusD{district}.json`)
- Districts: 1, 2, 3, 6, 7, 8, 9, 10, 11
- R1/R2/R3 levels, matched to route by highway name + postmile
- Only populated during active winter storms

### RWIS Pavement Sensors (`rwisStatusD{district}.json`)
- Districts: 2, 3, 6, 8, 9, 10
- Lat/lon stations matched to nearest waypoint within 15 miles
- Reports: pavement temp/status, air temp, wind, visibility, precip type

### Relevant Districts for SF 8-hour Radius
- District 1: Mendocino/Humboldt (CA-1, US-101 north)
- District 3: Sacramento/Sierra (I-80, US-50)
- District 6: Central Valley/Yosemite (CA-99, CA-41)
- District 10: Stockton/Tahoe (CA-4, CA-88)

## Frontend Layout

```
┌─────────────────────────────────────────────────────┐
│  [Origin]  [Destination]  [Date/Time]  [Get Route]  │
├────────────────────────┬────────────────────────────┤
│                        │  DRIVING INSTRUCTIONS       │
│                        │                            │
│    GOOGLE MAP          │  6:00 AM - San Mateo       │
│    with route drawn    │  48°F, Partly Cloudy       │
│    + colored segments  │  ► Head north on US-101 N  │
│    (green/yellow/red   │                            │
│     by weather         │  6:45 AM - Petaluma        │
│     severity)          │  45°F, Light Rain (60%)    │
│                        │  ► Continue on US-101 N    │
│    + weather markers   │                            │
│    at waypoints        │  7:30 AM - Cloverdale      │
│                        │  42°F, Rain (80%)          │
│    + alert zones       │  ⚠ Wind Advisory           │
│    highlighted         │  ► Exit onto CA-128 W      │
│                        │                            │
│                        │  8:15 AM - Boonville       │
│                        │  40°F, Heavy Rain (90%)    │
│                        │  ► Continue on CA-128 W    │
│                        │                            │
│                        │  9:35 AM - Mendocino       │
│                        │  46°F, Cloudy              │
│                        │  ✓ Arrive at destination   │
├────────────────────────┴────────────────────────────┤
│  ROUTE SUMMARY: Expect rain from Petaluma onward.   │
│  Wind advisory on CA-128. No chain controls.        │
└─────────────────────────────────────────────────────┘
```

### Map Visuals
- Route colored green/yellow/red by severity per segment
- Fog segments: gray haze overlay
- Wind: direction arrows at affected waypoints
- Rain: light/moderate/heavy indicators with mm/hr
- NWS advisories called out prominently in route summary and affected segments

## Test Route

San Mateo, CA → Mendocino, CA — Saturday 2026-02-21 at 6:00 AM PST

## External API Keys Required

| Service | Key type | Where to get it |
|---------|----------|-----------------|
| Google Routes API | API key with Routes + Maps JS enabled | console.cloud.google.com |
| Tomorrow.io | API key | app.tomorrow.io |
| NWS | None (just User-Agent header) | — |
| Open-Meteo | None (non-commercial) | — |
| Caltrans CWWP2 | None | — |
