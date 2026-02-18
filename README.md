# Drive Conditions

A web app that forecasts weather and road conditions along your driving route. Enter an origin, destination, and departure time to see a color-coded map and turn-by-turn breakdown of what you'll encounter on the road.

Built for routes within ~8 hours of San Francisco, with California-specific road data (chain control, pavement sensors).

![Python](https://img.shields.io/badge/python-3.10+-blue) ![Flask](https://img.shields.io/badge/flask-3.0+-green) ![License](https://img.shields.io/badge/license-MIT-gray)

## How It Works

1. Fetches your route from the **Google Routes API**
2. Samples waypoints every ~15 miles along the polyline
3. Computes ETAs at each waypoint based on departure time
4. Fetches weather from **3 independent sources** in parallel:
   - **National Weather Service** — forecasts and active alerts
   - **Open-Meteo** — temperature, wind, snow, visibility, freezing level
   - **Tomorrow.io** — road risk scoring and precipitation type
5. Fetches road conditions from **Caltrans** (chain control + RWIS pavement sensors)
6. Merges everything using conservative rules (worst-case wind, visibility, precip probability)
7. Scores each segment 0–10 for severity and renders it on a color-coded map

## Features

- **Multi-source weather** with graceful degradation if any API fails
- **Severity scoring** — green (safe), yellow (caution), red (hazardous)
- **Fog overlays** on the map for low-visibility segments
- **Chain control** and pavement condition warnings (California)
- **Active weather alerts** (NWS advisories, watches, warnings)
- **Interactive map** — click segments or sidebar cards to explore conditions
- **Turn-by-turn instructions** annotated with weather at each step

## Setup

### Prerequisites

- Python 3.10+
- A [Google Cloud](https://console.cloud.google.com/) API key with **Routes API** and **Maps JavaScript API** enabled
- A [Tomorrow.io](https://app.tomorrow.io/) API key (free tier available)

NWS and Open-Meteo require no API keys. Caltrans data is public.

### Install

```bash
git clone <repo-url>
cd drive-conditions
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Configure

```bash
cp .env.example .env
```

Edit `.env` with your keys:

```
GOOGLE_API_KEY=your_google_api_key_here
TOMORROW_API_KEY=your_tomorrow_io_api_key_here
```

### Run

```bash
python app.py
```

Open [http://localhost:5001](http://localhost:5001).

## API

### `GET /api/route-weather`

| Parameter | Description | Example |
|-----------|-------------|---------|
| `origin` | Starting address | `San Mateo, CA` |
| `destination` | Ending address | `Mendocino, CA` |
| `departure` | ISO 8601 datetime | `2026-02-21T06:00:00-08:00` |

Returns a JSON response with:

- **`route`** — summary, distance, duration, departure/arrival times, encoded polyline
- **`segments[]`** — per-waypoint weather (temp, wind, precip, visibility, fog, snow), road conditions, severity score, turn instructions
- **`alerts[]`** — active weather warnings with affected segments
- **`sources[]`** — which APIs contributed data

## Project Structure

```
app.py                  Flask server and API endpoint
config.py               API keys and constants
routing.py              Google Routes API, polyline decoding, waypoint sampling
weather_nws.py          National Weather Service forecasts and alerts
weather_openmeteo.py    Open-Meteo hourly weather data
weather_tomorrow.py     Tomorrow.io weather and road risk
road_conditions.py      Caltrans chain control and RWIS sensors
assembler.py            Weather merging, severity scoring, segment building
templates/index.html    Single-page frontend (vanilla JS + Google Maps)
tests/                  Unit tests for all backend modules
```

## Weather Merging Strategy

The assembler combines data from multiple sources using safety-first rules:

| Field | Strategy | Rationale |
|-------|----------|-----------|
| Temperature | Average of sources | Best estimate |
| Wind speed | Maximum | Alert to worst case |
| Precipitation probability | Maximum | Don't underestimate rain |
| Precipitation type | Tomorrow.io preferred | Best classification |
| Visibility | Minimum | Conservative for fog/haze |
| Snow/freezing level | Open-Meteo | Most detailed elevation data |
| Alerts | NWS exclusively | Authoritative US source |
| Road risk | Tomorrow.io exclusively | Purpose-built model |

## Testing

```bash
pytest
```

Tests cover weather parsing, route decoding, data merging, severity scoring, and road condition matching.
