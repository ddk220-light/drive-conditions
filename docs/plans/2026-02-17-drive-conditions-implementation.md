# Drive Conditions Webapp — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a webapp that shows weather and road conditions along a driving route with turn-by-turn instructions annotated with forecasted weather at each segment.

**Architecture:** Fetch-on-demand — user enters origin/destination/time, backend fetches route from Google Routes, samples waypoints every ~15 miles, fetches weather from NWS + Open-Meteo + Tomorrow.io in parallel, fetches Caltrans road conditions, merges everything into a unified timeline returned to a vanilla JS frontend with Google Maps.

**Tech Stack:** Python Flask, asyncio/aiohttp, vanilla JS, Google Maps JS API, Google Routes API, NWS api.weather.gov, Open-Meteo, Tomorrow.io, Caltrans CWWP2

**Design Doc:** `docs/plans/2026-02-17-drive-conditions-design.md`

---

## Task 1: Project Scaffolding

**Files:**
- Create: `requirements.txt`
- Create: `config.py`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `app.py` (minimal Flask shell)

**Step 1: Create `.gitignore`**

```
__pycache__/
*.pyc
.env
venv/
.venv/
*.egg-info/
```

**Step 2: Create `requirements.txt`**

```
flask>=3.0
aiohttp>=3.9
python-dotenv>=1.0
polyline>=2.0
```

**Step 3: Create `.env.example`**

```
GOOGLE_API_KEY=your_google_api_key_here
TOMORROW_API_KEY=your_tomorrow_io_api_key_here
```

**Step 4: Create `config.py`**

```python
import os
from dotenv import load_dotenv

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
TOMORROW_API_KEY = os.getenv("TOMORROW_API_KEY")

NWS_USER_AGENT = "drive-conditions/1.0 (contact@example.com)"

WAYPOINT_INTERVAL_MILES = 15
RWIS_MATCH_RADIUS_MILES = 15

CALTRANS_DISTRICTS = [1, 2, 3, 6, 7, 8, 9, 10, 11]
CALTRANS_RWIS_DISTRICTS = [2, 3, 6, 8, 9, 10]

CALTRANS_CC_URL = "https://cwwp2.dot.ca.gov/data/d{district}/cc/ccStatusD{district}.json"
CALTRANS_RWIS_URL = "https://cwwp2.dot.ca.gov/data/d{district}/rwis/rwisStatusD{district}.json"
```

**Step 5: Create minimal `app.py`**

```python
from flask import Flask

app = Flask(__name__)

@app.route("/")
def index():
    return "Drive Conditions - Coming Soon"

if __name__ == "__main__":
    app.run(debug=True, port=5001)
```

**Step 6: Create virtualenv and install deps**

Run:
```bash
cd /Users/deepak/AI/drive-conditions
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**Step 7: Verify Flask starts**

Run: `python3 app.py`
Expected: Server starts on port 5001, `curl http://localhost:5001/` returns "Drive Conditions - Coming Soon"

**Step 8: Commit**

```bash
git add .gitignore requirements.txt .env.example config.py app.py
git commit -m "feat: project scaffolding with Flask, config, and dependencies"
```

---

## Task 2: Routing Module — Google Routes API + Polyline Decoding

**Files:**
- Create: `routing.py`
- Create: `tests/test_routing.py`

**Step 1: Write tests for polyline decoding and waypoint sampling**

```python
# tests/test_routing.py
import math
from routing import decode_polyline, sample_waypoints, compute_etas
from datetime import datetime, timezone, timedelta

def test_decode_polyline_basic():
    """Test decoding a known encoded polyline."""
    # Google's example: _p~iF~ps|U_ulLnnqC_mqNvxq`@
    points = decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@")
    assert len(points) == 3
    assert abs(points[0][0] - 38.5) < 0.01
    assert abs(points[0][1] - (-120.2)) < 0.01

def test_sample_waypoints_spacing():
    """Sampling should produce waypoints roughly every N miles."""
    # Straight line ~100 miles: SF (37.77, -122.42) to Sacramento (38.58, -121.49)
    points = [
        (37.77, -122.42),
        (37.90, -122.20),
        (38.00, -122.00),
        (38.10, -121.80),
        (38.20, -121.70),
        (38.30, -121.60),
        (38.58, -121.49),
    ]
    sampled = sample_waypoints(points, interval_miles=30)
    # Should have at least origin + destination + some intermediate points
    assert len(sampled) >= 3
    assert sampled[0] == points[0]
    assert sampled[-1] == points[-1]

def test_compute_etas():
    """ETAs should be cumulative from departure time."""
    waypoints = [(37.77, -122.42), (38.00, -122.00), (38.58, -121.49)]
    total_duration_seconds = 5400  # 90 minutes
    departure = datetime(2026, 2, 21, 6, 0, tzinfo=timezone(timedelta(hours=-8)))

    etas = compute_etas(waypoints, total_duration_seconds, departure)
    assert len(etas) == 3
    assert etas[0] == departure
    assert etas[-1] == departure + timedelta(seconds=5400)
    # Middle point should be between start and end
    assert etas[0] < etas[1] < etas[2]
```

**Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_routing.py -v`
Expected: FAIL — `routing` module doesn't exist yet

**Step 3: Implement `routing.py`**

```python
# routing.py
import math
import aiohttp
from datetime import datetime, timedelta
from config import GOOGLE_API_KEY, WAYPOINT_INTERVAL_MILES

try:
    import polyline as polyline_lib
    def decode_polyline(encoded):
        return polyline_lib.decode(encoded)
except ImportError:
    def decode_polyline(encoded):
        """Fallback pure-Python polyline decoder."""
        points = []
        index = 0
        lat = 0
        lng = 0
        while index < len(encoded):
            for var in ('lat', 'lng'):
                shift = 0
                result = 0
                while True:
                    b = ord(encoded[index]) - 63
                    index += 1
                    result |= (b & 0x1F) << shift
                    shift += 5
                    if b < 0x20:
                        break
                dlat_or_dlng = ~(result >> 1) if (result & 1) else (result >> 1)
                if var == 'lat':
                    lat += dlat_or_dlng
                else:
                    lng += dlat_or_dlng
            points.append((lat / 1e5, lng / 1e5))
        return points


def haversine_miles(lat1, lon1, lat2, lon2):
    """Distance between two lat/lon points in miles."""
    R = 3958.8  # Earth radius in miles
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def sample_waypoints(points, interval_miles=None):
    """Sample waypoints from a decoded polyline at regular distance intervals.
    Always includes first and last point."""
    if interval_miles is None:
        interval_miles = WAYPOINT_INTERVAL_MILES
    if len(points) <= 2:
        return list(points)

    sampled = [points[0]]
    accumulated = 0.0

    for i in range(1, len(points)):
        d = haversine_miles(points[i-1][0], points[i-1][1],
                           points[i][0], points[i][1])
        accumulated += d
        if accumulated >= interval_miles:
            sampled.append(points[i])
            accumulated = 0.0

    if sampled[-1] != points[-1]:
        sampled.append(points[-1])

    return sampled


def compute_etas(waypoints, total_duration_seconds, departure):
    """Compute ETA at each waypoint assuming constant speed along the route."""
    if len(waypoints) <= 1:
        return [departure]

    # Compute cumulative distances
    distances = [0.0]
    for i in range(1, len(waypoints)):
        d = haversine_miles(waypoints[i-1][0], waypoints[i-1][1],
                           waypoints[i][0], waypoints[i][1])
        distances.append(distances[-1] + d)

    total_distance = distances[-1]
    if total_distance == 0:
        return [departure] * len(waypoints)

    etas = []
    for d in distances:
        fraction = d / total_distance
        eta = departure + timedelta(seconds=total_duration_seconds * fraction)
        etas.append(eta)

    return etas


async def fetch_route(origin, destination, departure_time):
    """Fetch route from Google Routes API.

    Returns dict with keys: polyline, steps, total_distance_meters,
    total_duration_seconds, summary.
    """
    url = "https://routes.googleapis.com/directions/v2:computeRoutes"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_API_KEY,
        "X-Goog-FieldMask": (
            "routes.polyline.encodedPolyline,"
            "routes.legs.steps.navigationInstruction,"
            "routes.legs.steps.localizedValues,"
            "routes.legs.steps.startLocation,"
            "routes.legs.steps.endLocation,"
            "routes.legs.duration,"
            "routes.legs.distanceMeters,"
            "routes.description"
        ),
    }
    body = {
        "origin": {"address": origin},
        "destination": {"address": destination},
        "travelMode": "DRIVE",
        "departureTime": departure_time,
        "routingPreference": "TRAFFIC_AWARE",
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=body, headers=headers) as resp:
            data = await resp.json()

    if "routes" not in data or not data["routes"]:
        raise ValueError(f"No route found: {data.get('error', data)}")

    route = data["routes"][0]
    legs = route.get("legs", [])

    steps = []
    for leg in legs:
        for step in leg.get("steps", []):
            nav = step.get("navigationInstruction", {})
            steps.append({
                "instruction": nav.get("instructions", ""),
                "maneuver": nav.get("maneuver", ""),
                "start_location": step.get("startLocation", {}).get("latLng", {}),
                "end_location": step.get("endLocation", {}).get("latLng", {}),
            })

    total_duration_seconds = sum(
        int(leg["duration"].rstrip("s")) for leg in legs if "duration" in leg
    )
    total_distance_meters = sum(
        leg.get("distanceMeters", 0) for leg in legs
    )

    return {
        "polyline": route.get("polyline", {}).get("encodedPolyline", ""),
        "steps": steps,
        "total_distance_meters": total_distance_meters,
        "total_duration_seconds": total_duration_seconds,
        "summary": route.get("description", ""),
    }
```

**Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_routing.py -v`
Expected: All 3 tests PASS

**Step 5: Commit**

```bash
git add routing.py tests/test_routing.py
git commit -m "feat: routing module with polyline decoding, waypoint sampling, and Google Routes client"
```

---

## Task 3: NWS Weather Module

**Files:**
- Create: `weather_nws.py`
- Create: `tests/test_weather_nws.py`

**Step 1: Write tests**

```python
# tests/test_weather_nws.py
from weather_nws import parse_hourly_forecast, find_forecast_for_time
from datetime import datetime, timezone, timedelta

SAMPLE_PERIOD = {
    "startTime": "2026-02-21T06:00:00-08:00",
    "endTime": "2026-02-21T07:00:00-08:00",
    "temperature": 48,
    "temperatureUnit": "F",
    "windSpeed": "10 mph",
    "windDirection": "SW",
    "shortForecast": "Partly Cloudy",
    "probabilityOfPrecipitation": {"value": 20},
    "relativeHumidity": {"value": 75},
}

def test_parse_hourly_forecast():
    result = parse_hourly_forecast(SAMPLE_PERIOD)
    assert result["temperature_f"] == 48
    assert result["wind_speed_mph"] == 10
    assert result["condition_text"] == "Partly Cloudy"
    assert result["precipitation_probability"] == 20

def test_find_forecast_for_time():
    periods = [
        {**SAMPLE_PERIOD, "startTime": "2026-02-21T06:00:00-08:00"},
        {**SAMPLE_PERIOD, "startTime": "2026-02-21T07:00:00-08:00",
         "temperature": 50, "shortForecast": "Cloudy"},
    ]
    target = datetime(2026, 2, 21, 6, 30,
                      tzinfo=timezone(timedelta(hours=-8)))
    result = find_forecast_for_time(periods, target)
    assert result["temperature_f"] == 48  # matches 6 AM period
```

**Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_weather_nws.py -v`
Expected: FAIL

**Step 3: Implement `weather_nws.py`**

```python
# weather_nws.py
import re
import aiohttp
from datetime import datetime, timezone
from config import NWS_USER_AGENT


def parse_hourly_forecast(period):
    """Parse a single NWS hourly forecast period into normalized dict."""
    wind_match = re.search(r"(\d+)", period.get("windSpeed", "0"))
    wind_speed = int(wind_match.group(1)) if wind_match else 0

    precip = period.get("probabilityOfPrecipitation", {})
    precip_pct = precip.get("value") if precip.get("value") is not None else 0

    return {
        "temperature_f": period.get("temperature"),
        "wind_speed_mph": wind_speed,
        "wind_direction": period.get("windDirection", ""),
        "condition_text": period.get("shortForecast", ""),
        "precipitation_probability": precip_pct,
    }


def find_forecast_for_time(periods, target_time):
    """Find the forecast period that contains the target time."""
    for period in periods:
        start = datetime.fromisoformat(period["startTime"])
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        # NWS periods are 1 hour each
        end_str = period.get("endTime")
        if end_str:
            end = datetime.fromisoformat(end_str)
        else:
            from datetime import timedelta
            end = start + timedelta(hours=1)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)

        if start <= target_time < end:
            return parse_hourly_forecast(period)

    # Fallback: return closest period
    if periods:
        closest = min(periods,
                      key=lambda p: abs(
                          (datetime.fromisoformat(p["startTime"]) - target_time).total_seconds()
                      ))
        return parse_hourly_forecast(closest)
    return None


async def fetch_nws_forecast(lat, lon, session=None):
    """Fetch hourly forecast from NWS for a lat/lon point.

    Two-step: /points → /gridpoints forecast/hourly
    Returns list of parsed forecast periods.
    """
    headers = {"User-Agent": NWS_USER_AGENT, "Accept": "application/geo+json"}
    own_session = session is None
    if own_session:
        session = aiohttp.ClientSession()

    try:
        # Step 1: resolve point to grid
        points_url = f"https://api.weather.gov/points/{lat:.4f},{lon:.4f}"
        async with session.get(points_url, headers=headers) as resp:
            if resp.status != 200:
                return None
            points_data = await resp.json()

        forecast_url = points_data["properties"]["forecastHourly"]

        # Step 2: fetch hourly forecast
        async with session.get(forecast_url, headers=headers) as resp:
            if resp.status != 200:
                return None
            forecast_data = await resp.json()

        return forecast_data["properties"]["periods"]

    except Exception:
        return None
    finally:
        if own_session:
            await session.close()


async def fetch_nws_alerts(lat, lon, session=None):
    """Fetch active weather alerts near a point."""
    headers = {"User-Agent": NWS_USER_AGENT, "Accept": "application/geo+json"}
    own_session = session is None
    if own_session:
        session = aiohttp.ClientSession()

    try:
        url = f"https://api.weather.gov/alerts/active?point={lat:.4f},{lon:.4f}"
        async with session.get(url, headers=headers) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()

        alerts = []
        for feature in data.get("features", []):
            props = feature["properties"]
            alerts.append({
                "type": props.get("event", ""),
                "headline": props.get("headline", ""),
                "severity": props.get("severity", "").lower(),
                "description": props.get("description", ""),
            })
        return alerts

    except Exception:
        return []
    finally:
        if own_session:
            await session.close()
```

**Step 4: Run tests**

Run: `python3 -m pytest tests/test_weather_nws.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add weather_nws.py tests/test_weather_nws.py
git commit -m "feat: NWS weather module with hourly forecast parsing and alerts"
```

---

## Task 4: Open-Meteo Weather Module

**Files:**
- Create: `weather_openmeteo.py`
- Create: `tests/test_weather_openmeteo.py`

**Step 1: Write tests**

```python
# tests/test_weather_openmeteo.py
from weather_openmeteo import parse_openmeteo_hourly, find_data_for_time
from datetime import datetime, timezone, timedelta

SAMPLE_RESPONSE = {
    "hourly": {
        "time": ["2026-02-21T06:00", "2026-02-21T07:00", "2026-02-21T08:00"],
        "temperature_2m": [8.5, 9.2, 10.1],
        "precipitation": [0.0, 0.5, 2.1],
        "snowfall": [0.0, 0.0, 0.0],
        "snow_depth": [0.0, 0.0, 0.0],
        "visibility": [16000, 8000, 3000],
        "wind_speed_10m": [12.0, 18.5, 25.0],
        "wind_gusts_10m": [20.0, 30.0, 45.0],
        "wind_direction_10m": [225, 230, 240],
        "freezing_level_height": [1600, 1500, 1400],
        "weather_code": [1, 61, 63],
    },
    "hourly_units": {
        "temperature_2m": "°C",
    }
}

def test_parse_openmeteo_hourly():
    result = parse_openmeteo_hourly(SAMPLE_RESPONSE, hour_index=1)
    assert abs(result["temperature_f"] - 48.56) < 0.1  # 9.2°C -> F
    assert result["precipitation_mm_hr"] == 0.5
    assert result["wind_speed_mph"] > 11  # 18.5 km/h -> mph
    assert result["visibility_miles"] < 5.0  # 8000m -> miles

def test_find_data_for_time():
    pst = timezone(timedelta(hours=-8))
    target = datetime(2026, 2, 21, 7, 30, tzinfo=pst)
    result = find_data_for_time(SAMPLE_RESPONSE, target)
    # Should match the 07:00 slot (index 1)
    assert result["precipitation_mm_hr"] == 0.5
```

**Step 2: Run tests to verify failure**

Run: `python3 -m pytest tests/test_weather_openmeteo.py -v`
Expected: FAIL

**Step 3: Implement `weather_openmeteo.py`**

```python
# weather_openmeteo.py
import aiohttp
from datetime import datetime, timezone, timedelta

OPENMETEO_URL = "https://api.open-meteo.com/v1/forecast"

HOURLY_VARS = (
    "temperature_2m,precipitation,snowfall,snow_depth,"
    "visibility,wind_speed_10m,wind_gusts_10m,wind_direction_10m,"
    "freezing_level_height,weather_code"
)


def c_to_f(c):
    return round(c * 9 / 5 + 32, 1)


def kmh_to_mph(kmh):
    return round(kmh * 0.621371, 1)


def m_to_miles(m):
    return round(m / 1609.344, 1)


def m_to_ft(m):
    return round(m * 3.28084)


def parse_openmeteo_hourly(data, hour_index):
    """Parse Open-Meteo response at a specific hour index."""
    h = data["hourly"]
    temp_c = h["temperature_2m"][hour_index]
    return {
        "temperature_f": c_to_f(temp_c),
        "precipitation_mm_hr": h["precipitation"][hour_index],
        "snowfall_cm_hr": h["snowfall"][hour_index],
        "snow_depth_in": round(h["snow_depth"][hour_index] / 2.54, 1),
        "visibility_miles": m_to_miles(h["visibility"][hour_index]),
        "wind_speed_mph": kmh_to_mph(h["wind_speed_10m"][hour_index]),
        "wind_gusts_mph": kmh_to_mph(h["wind_gusts_10m"][hour_index]),
        "wind_direction_deg": h["wind_direction_10m"][hour_index],
        "freezing_level_ft": m_to_ft(h["freezing_level_height"][hour_index]),
        "weather_code": h["weather_code"][hour_index],
    }


def find_data_for_time(data, target_time):
    """Find the hourly slot closest to target_time and parse it."""
    times = data["hourly"]["time"]
    # Open-Meteo returns times in the requested timezone (or UTC)
    # Parse and find closest
    best_index = 0
    best_diff = float("inf")

    for i, t_str in enumerate(times):
        t = datetime.fromisoformat(t_str)
        # If no timezone, assume same as target
        if t.tzinfo is None and target_time.tzinfo is not None:
            t = t.replace(tzinfo=target_time.tzinfo)
        diff = abs((t - target_time).total_seconds())
        if diff < best_diff:
            best_diff = diff
            best_index = i

    return parse_openmeteo_hourly(data, best_index)


async def fetch_openmeteo(latitudes, longitudes, forecast_days=7, session=None):
    """Fetch Open-Meteo forecast for multiple coordinates.

    Args:
        latitudes: list of floats
        longitudes: list of floats

    Returns: list of raw response dicts (one per coordinate).
    """
    own_session = session is None
    if own_session:
        session = aiohttp.ClientSession()

    try:
        results = []
        # Open-Meteo supports comma-separated multi-location
        lat_str = ",".join(f"{lat:.4f}" for lat in latitudes)
        lon_str = ",".join(f"{lon:.4f}" for lon in longitudes)

        params = {
            "latitude": lat_str,
            "longitude": lon_str,
            "hourly": HOURLY_VARS,
            "forecast_days": forecast_days,
            "temperature_unit": "celsius",
            "wind_speed_unit": "kmh",
            "timezone": "America/Los_Angeles",
        }

        async with session.get(OPENMETEO_URL, params=params) as resp:
            data = await resp.json()

        # Single location returns a dict; multiple returns a list
        if isinstance(data, list):
            results = data
        else:
            results = [data]

        return results

    except Exception:
        return [None] * len(latitudes)
    finally:
        if own_session:
            await session.close()
```

**Step 4: Run tests**

Run: `python3 -m pytest tests/test_weather_openmeteo.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add weather_openmeteo.py tests/test_weather_openmeteo.py
git commit -m "feat: Open-Meteo weather module with batch coordinate fetching"
```

---

## Task 5: Tomorrow.io Weather Module

**Files:**
- Create: `weather_tomorrow.py`
- Create: `tests/test_weather_tomorrow.py`

**Step 1: Write tests**

```python
# tests/test_weather_tomorrow.py
from weather_tomorrow import parse_tomorrow_hourly, find_data_for_time
from datetime import datetime, timezone, timedelta

SAMPLE_INTERVAL = {
    "startTime": "2026-02-21T06:00:00-08:00",
    "values": {
        "temperature": 9.0,
        "precipitationProbability": 25,
        "precipitationType": 1,  # 1=rain
        "windSpeed": 15.0,
        "windGust": 28.0,
        "visibility": 12.0,
        "weatherCode": 1100,
    }
}

def test_parse_tomorrow_hourly():
    result = parse_tomorrow_hourly(SAMPLE_INTERVAL)
    assert abs(result["temperature_f"] - 48.2) < 0.5
    assert result["precipitation_probability"] == 25
    assert result["precipitation_type"] == "rain"
    assert result["road_risk_score"] is None  # Not in basic response

def test_find_data_for_time():
    intervals = [
        {**SAMPLE_INTERVAL, "startTime": "2026-02-21T06:00:00-08:00"},
        {**SAMPLE_INTERVAL, "startTime": "2026-02-21T07:00:00-08:00",
         "values": {**SAMPLE_INTERVAL["values"], "temperature": 11.0}},
    ]
    pst = timezone(timedelta(hours=-8))
    target = datetime(2026, 2, 21, 6, 20, tzinfo=pst)
    result = find_data_for_time(intervals, target)
    assert abs(result["temperature_f"] - 48.2) < 0.5  # matches 6 AM
```

**Step 2: Run tests to verify failure**

Run: `python3 -m pytest tests/test_weather_tomorrow.py -v`
Expected: FAIL

**Step 3: Implement `weather_tomorrow.py`**

```python
# weather_tomorrow.py
import aiohttp
from datetime import datetime, timezone, timedelta
from config import TOMORROW_API_KEY

TOMORROW_URL = "https://api.tomorrow.io/v4/timelines"

PRECIP_TYPE_MAP = {0: "none", 1: "rain", 2: "snow", 3: "freezing_rain", 4: "sleet"}

WEATHER_CODE_MAP = {
    1000: "Clear", 1100: "Mostly Clear", 1101: "Partly Cloudy",
    1102: "Mostly Cloudy", 1001: "Cloudy", 2000: "Fog", 2100: "Light Fog",
    4000: "Drizzle", 4001: "Rain", 4200: "Light Rain", 4201: "Heavy Rain",
    5000: "Snow", 5001: "Flurries", 5100: "Light Snow", 5101: "Heavy Snow",
    6000: "Freezing Drizzle", 6001: "Freezing Rain", 6200: "Light Freezing Rain",
    6201: "Heavy Freezing Rain", 7000: "Ice Pellets", 7101: "Heavy Ice Pellets",
    7102: "Light Ice Pellets", 8000: "Thunderstorm",
}


def c_to_f(c):
    return round(c * 9 / 5 + 32, 1)


def kmh_to_mph(kmh):
    return round(kmh * 0.621371, 1)


def parse_tomorrow_hourly(interval):
    """Parse a single Tomorrow.io timeline interval."""
    v = interval["values"]
    temp_c = v.get("temperature", 0)
    precip_type_code = v.get("precipitationType", 0)

    return {
        "temperature_f": c_to_f(temp_c),
        "precipitation_probability": v.get("precipitationProbability", 0),
        "precipitation_type": PRECIP_TYPE_MAP.get(precip_type_code, "unknown"),
        "wind_speed_mph": kmh_to_mph(v.get("windSpeed", 0)),
        "wind_gusts_mph": kmh_to_mph(v.get("windGust", 0)),
        "visibility_miles": round(v.get("visibility", 16), 1),
        "weather_code": v.get("weatherCode"),
        "weather_text": WEATHER_CODE_MAP.get(v.get("weatherCode"), "Unknown"),
        "road_risk_score": v.get("roadRisk"),
        "road_risk_label": v.get("roadRiskLabel"),
    }


def find_data_for_time(intervals, target_time):
    """Find the interval closest to target_time."""
    best = None
    best_diff = float("inf")

    for interval in intervals:
        t = datetime.fromisoformat(interval["startTime"])
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        diff = abs((t - target_time).total_seconds())
        if diff < best_diff:
            best_diff = diff
            best = interval

    if best:
        return parse_tomorrow_hourly(best)
    return None


async def fetch_tomorrow(lat, lon, session=None):
    """Fetch hourly forecast from Tomorrow.io for a single point.

    Returns list of interval dicts.
    """
    own_session = session is None
    if own_session:
        session = aiohttp.ClientSession()

    try:
        params = {
            "location": f"{lat:.4f},{lon:.4f}",
            "fields": (
                "temperature,precipitationProbability,precipitationType,"
                "windSpeed,windGust,visibility,weatherCode"
            ),
            "timesteps": "1h",
            "units": "metric",
            "apikey": TOMORROW_API_KEY,
        }

        async with session.get(TOMORROW_URL, params=params) as resp:
            data = await resp.json()

        timelines = data.get("data", {}).get("timelines", [])
        if timelines:
            return timelines[0].get("intervals", [])
        return []

    except Exception:
        return []
    finally:
        if own_session:
            await session.close()
```

**Step 4: Run tests**

Run: `python3 -m pytest tests/test_weather_tomorrow.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add weather_tomorrow.py tests/test_weather_tomorrow.py
git commit -m "feat: Tomorrow.io weather module with road risk and precipitation type"
```

---

## Task 6: Caltrans Road Conditions Module

**Files:**
- Create: `road_conditions.py`
- Create: `tests/test_road_conditions.py`

**Step 1: Write tests**

```python
# tests/test_road_conditions.py
from road_conditions import match_rwis_to_waypoint, parse_chain_control

SAMPLE_RWIS_STATION = {
    "location": {"latitude": 38.80, "longitude": -120.03},
    "airTemperature": {"value": 35, "unit": "F"},
    "surfaceTemperature": {"value": 32, "unit": "F"},
    "surfaceStatus": "Wet",
    "visibility": {"value": 0.5, "unit": "mi"},
    "windSpeed": {"value": 25, "unit": "mph"},
    "precipitationType": "Rain",
}

def test_match_rwis_to_waypoint_nearby():
    stations = [SAMPLE_RWIS_STATION]
    waypoint = (38.81, -120.04)  # very close
    result = match_rwis_to_waypoint(stations, waypoint, radius_miles=15)
    assert result is not None
    assert result["pavement_status"] == "Wet"
    assert result["visibility_miles"] == 0.5

def test_match_rwis_to_waypoint_too_far():
    stations = [SAMPLE_RWIS_STATION]
    waypoint = (37.0, -122.0)  # ~130 miles away
    result = match_rwis_to_waypoint(stations, waypoint, radius_miles=15)
    assert result is None

def test_parse_chain_control():
    sample = {
        "statusDate": "2026-02-21T06:00:00",
        "highway": "80",
        "direction": "E",
        "controlStatus": "R1",
        "beginPostmile": 30.0,
        "endPostmile": 60.0,
        "description": "Chains required on I-80 Eastbound",
    }
    result = parse_chain_control(sample)
    assert result["highway"] == "80"
    assert result["level"] == "R1"
    assert result["description"] == "Chains required on I-80 Eastbound"
```

**Step 2: Run tests to verify failure**

Run: `python3 -m pytest tests/test_road_conditions.py -v`
Expected: FAIL

**Step 3: Implement `road_conditions.py`**

```python
# road_conditions.py
import aiohttp
from routing import haversine_miles
from config import (
    CALTRANS_DISTRICTS, CALTRANS_RWIS_DISTRICTS,
    CALTRANS_CC_URL, CALTRANS_RWIS_URL, RWIS_MATCH_RADIUS_MILES,
)


def parse_chain_control(entry):
    """Parse a single chain control entry."""
    return {
        "highway": entry.get("highway", ""),
        "direction": entry.get("direction", ""),
        "level": entry.get("controlStatus", ""),
        "begin_postmile": entry.get("beginPostmile"),
        "end_postmile": entry.get("endPostmile"),
        "description": entry.get("description", ""),
    }


def match_rwis_to_waypoint(stations, waypoint, radius_miles=None):
    """Find the nearest RWIS station to a waypoint within radius.

    Args:
        stations: list of RWIS station dicts (with location.latitude/longitude)
        waypoint: (lat, lon) tuple
        radius_miles: max distance to match

    Returns: parsed station data dict or None
    """
    if radius_miles is None:
        radius_miles = RWIS_MATCH_RADIUS_MILES

    best = None
    best_dist = float("inf")

    for station in stations:
        loc = station.get("location", {})
        slat = loc.get("latitude")
        slon = loc.get("longitude")
        if slat is None or slon is None:
            continue

        dist = haversine_miles(waypoint[0], waypoint[1], slat, slon)
        if dist < best_dist and dist <= radius_miles:
            best_dist = dist
            best = station

    if best is None:
        return None

    vis = best.get("visibility", {})
    vis_val = vis.get("value") if isinstance(vis, dict) else None
    wind = best.get("windSpeed", {})
    wind_val = wind.get("value") if isinstance(wind, dict) else None

    return {
        "pavement_status": best.get("surfaceStatus"),
        "pavement_temp_f": (best.get("surfaceTemperature", {}) or {}).get("value"),
        "air_temp_f": (best.get("airTemperature", {}) or {}).get("value"),
        "visibility_miles": vis_val,
        "wind_speed_mph": wind_val,
        "precipitation_type": best.get("precipitationType"),
        "distance_miles": round(best_dist, 1),
    }


async def fetch_chain_controls(session=None):
    """Fetch chain control data from all Caltrans districts.

    Returns list of parsed chain control entries.
    """
    own_session = session is None
    if own_session:
        session = aiohttp.ClientSession()

    try:
        all_controls = []
        for district in CALTRANS_DISTRICTS:
            url = CALTRANS_CC_URL.format(district=district)
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        entries = data if isinstance(data, list) else data.get("data", [])
                        for entry in entries:
                            parsed = parse_chain_control(entry)
                            if parsed["level"]:  # Only include active controls
                                all_controls.append(parsed)
            except Exception:
                continue  # Skip failed districts

        return all_controls

    finally:
        if own_session:
            await session.close()


async def fetch_rwis_stations(session=None):
    """Fetch RWIS pavement sensor data from Caltrans districts.

    Returns list of station dicts with location and readings.
    """
    own_session = session is None
    if own_session:
        session = aiohttp.ClientSession()

    try:
        all_stations = []
        for district in CALTRANS_RWIS_DISTRICTS:
            url = CALTRANS_RWIS_URL.format(district=district)
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        stations = data if isinstance(data, list) else data.get("data", [])
                        all_stations.extend(stations)
            except Exception:
                continue

        return all_stations

    finally:
        if own_session:
            await session.close()
```

**Step 4: Run tests**

Run: `python3 -m pytest tests/test_road_conditions.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add road_conditions.py tests/test_road_conditions.py
git commit -m "feat: Caltrans road conditions module with RWIS matching and chain control parsing"
```

---

## Task 7: Assembler — Merge Weather + Road Data + Severity Scoring

**Files:**
- Create: `assembler.py`
- Create: `tests/test_assembler.py`

**Step 1: Write tests**

```python
# tests/test_assembler.py
from assembler import merge_weather, compute_severity, classify_rain_intensity, classify_fog_level

def test_merge_weather_averages_temperature():
    nws = {"temperature_f": 48, "precipitation_probability": 20, "wind_speed_mph": 10, "condition_text": "Cloudy"}
    openmeteo = {"temperature_f": 49, "precipitation_mm_hr": 0.5, "wind_speed_mph": 12, "wind_gusts_mph": 20, "visibility_miles": 8.0, "snow_depth_in": 0, "freezing_level_ft": 5000, "wind_direction_deg": 225}
    tomorrow = {"temperature_f": 47, "precipitation_probability": 30, "precipitation_type": "rain", "wind_speed_mph": 11, "wind_gusts_mph": 18, "visibility_miles": 10.0, "road_risk_score": 2, "road_risk_label": "Low"}

    merged = merge_weather(nws=nws, openmeteo=openmeteo, tomorrow=tomorrow)
    # Temperature: average of openmeteo (49) and tomorrow (47) = 48
    assert merged["temperature_f"] == 48.0
    # Wind: max of all = 12
    assert merged["wind_speed_mph"] == 12
    # Precip probability: max = 30
    assert merged["precipitation_probability"] == 30
    # Condition text from NWS
    assert merged["condition_text"] == "Cloudy"
    # Road risk from Tomorrow
    assert merged["road_risk_score"] == 2

def test_compute_severity_green():
    weather = {"visibility_miles": 10, "wind_speed_mph": 10, "wind_gusts_mph": 15, "precipitation_mm_hr": 0.0}
    score, label = compute_severity(weather, road_conditions=None, alerts=[])
    assert label == "green"
    assert score <= 3

def test_compute_severity_yellow():
    weather = {"visibility_miles": 3.0, "wind_speed_mph": 25, "wind_gusts_mph": 35, "precipitation_mm_hr": 1.5}
    score, label = compute_severity(weather, road_conditions=None, alerts=[])
    assert label == "yellow"

def test_compute_severity_red():
    weather = {"visibility_miles": 0.5, "wind_speed_mph": 40, "wind_gusts_mph": 55, "precipitation_mm_hr": 6.0}
    score, label = compute_severity(weather, road_conditions=None, alerts=[])
    assert label == "red"

def test_classify_rain_intensity():
    assert classify_rain_intensity(0.0) == "none"
    assert classify_rain_intensity(0.3) == "light"
    assert classify_rain_intensity(2.0) == "moderate"
    assert classify_rain_intensity(5.0) == "heavy"

def test_classify_fog_level():
    assert classify_fog_level(10.0) == "none"
    assert classify_fog_level(3.0) == "patchy"
    assert classify_fog_level(0.5) == "dense"
```

**Step 2: Run tests to verify failure**

Run: `python3 -m pytest tests/test_assembler.py -v`
Expected: FAIL

**Step 3: Implement `assembler.py`**

```python
# assembler.py
from datetime import datetime


def classify_rain_intensity(mm_hr):
    if mm_hr is None or mm_hr < 0.1:
        return "none"
    elif mm_hr < 0.5:
        return "light"
    elif mm_hr < 4.0:
        return "moderate"
    else:
        return "heavy"


def classify_fog_level(visibility_miles):
    if visibility_miles is None or visibility_miles > 5.0:
        return "none"
    elif visibility_miles > 1.0:
        return "patchy"
    else:
        return "dense"


def merge_weather(nws=None, openmeteo=None, tomorrow=None):
    """Merge weather data from up to 3 sources using design merge rules.

    Returns a single unified weather dict.
    """
    sources = []
    result = {}

    # Temperature: average of Open-Meteo and Tomorrow.io
    temps = []
    if openmeteo and openmeteo.get("temperature_f") is not None:
        temps.append(openmeteo["temperature_f"])
        sources.append("Open-Meteo")
    if tomorrow and tomorrow.get("temperature_f") is not None:
        temps.append(tomorrow["temperature_f"])
        if "Tomorrow.io" not in sources:
            sources.append("Tomorrow.io")
    if nws and nws.get("temperature_f") is not None and not temps:
        temps.append(nws["temperature_f"])
    result["temperature_f"] = round(sum(temps) / len(temps), 1) if temps else None

    # Wind speed/gusts: max of all (conservative)
    winds = [s.get("wind_speed_mph", 0) for s in [nws, openmeteo, tomorrow] if s]
    result["wind_speed_mph"] = max(winds) if winds else 0
    gusts = [s.get("wind_gusts_mph", 0) for s in [openmeteo, tomorrow] if s and s.get("wind_gusts_mph")]
    result["wind_gusts_mph"] = max(gusts) if gusts else result["wind_speed_mph"]

    # Wind direction: from Open-Meteo
    result["wind_direction_deg"] = (openmeteo or {}).get("wind_direction_deg")

    # Precip probability: max (conservative)
    probs = [s.get("precipitation_probability", 0) for s in [nws, tomorrow] if s]
    result["precipitation_probability"] = max(probs) if probs else 0

    # Precip type: Tomorrow.io preferred
    result["precipitation_type"] = (tomorrow or {}).get("precipitation_type", "none")

    # Precip mm/hr: Open-Meteo
    result["precipitation_mm_hr"] = (openmeteo or {}).get("precipitation_mm_hr", 0)
    result["rain_intensity"] = classify_rain_intensity(result["precipitation_mm_hr"])

    # Visibility: min (conservative)
    vis = [s.get("visibility_miles") for s in [openmeteo, tomorrow] if s and s.get("visibility_miles") is not None]
    result["visibility_miles"] = min(vis) if vis else None
    result["fog_level"] = classify_fog_level(result["visibility_miles"])

    # Snow: Open-Meteo
    result["snow_depth_in"] = (openmeteo or {}).get("snow_depth_in", 0)
    result["freezing_level_ft"] = (openmeteo or {}).get("freezing_level_ft")

    # Condition text: NWS
    result["condition_text"] = (nws or {}).get("condition_text", (tomorrow or {}).get("weather_text", ""))

    # Road risk: Tomorrow.io
    result["road_risk_score"] = (tomorrow or {}).get("road_risk_score")
    result["road_risk_label"] = (tomorrow or {}).get("road_risk_label")

    if nws:
        sources.append("NWS")

    return result


def compute_severity(weather, road_conditions=None, alerts=None):
    """Compute severity score (0-10) and label (green/yellow/red).

    Based on design thresholds:
    - Green (0-3): vis > 5mi, wind < 20mph, precip < 0.5mm/hr, no advisories
    - Yellow (4-6): vis 1-5mi, wind 20-35mph, precip 0.5-4mm/hr, or advisory
    - Red (7-10): vis < 1mi, wind > 35mph, precip > 4mm/hr, flooding/closure
    """
    score = 0
    alerts = alerts or []

    vis = weather.get("visibility_miles")
    wind = weather.get("wind_speed_mph", 0)
    gusts = weather.get("wind_gusts_mph", 0)
    precip = weather.get("precipitation_mm_hr", 0)

    # Visibility scoring
    if vis is not None:
        if vis < 0.25:
            score += 4
        elif vis < 1.0:
            score += 3
        elif vis < 3.0:
            score += 2
        elif vis < 5.0:
            score += 1

    # Wind scoring (use gusts if available, else sustained)
    effective_wind = max(wind, gusts * 0.7) if gusts else wind
    if effective_wind > 45:
        score += 3
    elif effective_wind > 35:
        score += 2.5
    elif effective_wind > 25:
        score += 1.5
    elif effective_wind > 20:
        score += 1

    # Precipitation scoring
    if precip > 8.0:
        score += 3
    elif precip > 4.0:
        score += 2.5
    elif precip > 2.0:
        score += 1.5
    elif precip > 0.5:
        score += 1

    # Road conditions
    if road_conditions:
        chain = road_conditions.get("chain_control")
        if chain:
            level = chain.get("level", "")
            if level == "R3":
                score += 3
            elif level == "R2":
                score += 2
            elif level == "R1":
                score += 1

        pavement = road_conditions.get("pavement_status", "")
        if pavement and pavement.lower() in ("ice", "snow"):
            score += 2
        elif pavement and pavement.lower() == "wet":
            score += 0.5

    # Alerts
    for alert in alerts:
        sev = alert.get("severity", "")
        if sev in ("extreme", "severe"):
            score += 2
        elif sev == "moderate":
            score += 1

    score = min(10, round(score))

    if score <= 3:
        return score, "green"
    elif score <= 6:
        return score, "yellow"
    else:
        return score, "red"


def build_segments(waypoints, etas, route_steps, weather_data, road_data, alerts_by_segment):
    """Assemble the final segments list for the API response.

    Args:
        waypoints: list of (lat, lon) tuples
        etas: list of datetime objects
        route_steps: list of step dicts from routing
        weather_data: list of merged weather dicts (one per waypoint)
        road_data: list of road condition dicts (one per waypoint, may be None)
        alerts_by_segment: list of alert lists (one per waypoint)

    Returns: list of segment dicts matching the API response schema.
    """
    segments = []
    cumulative_miles = 0.0

    for i, (wp, eta) in enumerate(zip(waypoints, etas)):
        if i > 0:
            from routing import haversine_miles
            cumulative_miles += haversine_miles(
                waypoints[i-1][0], waypoints[i-1][1], wp[0], wp[1]
            )

        weather = weather_data[i] if i < len(weather_data) else {}
        road = road_data[i] if i < len(road_data) else None
        seg_alerts = alerts_by_segment[i] if i < len(alerts_by_segment) else []

        severity_score, severity_label = compute_severity(weather, road, seg_alerts)

        # Find matching turn instruction
        instruction = ""
        if route_steps:
            # Find the step whose start location is closest to this waypoint
            best_step = None
            best_dist = float("inf")
            for step in route_steps:
                sloc = step.get("start_location", {})
                slat = sloc.get("latitude") or sloc.get("lat", 0)
                slng = sloc.get("longitude") or sloc.get("lng", 0)
                from routing import haversine_miles as hv
                d = hv(wp[0], wp[1], slat, slng)
                if d < best_dist:
                    best_dist = d
                    best_step = step
            if best_step:
                instruction = best_step.get("instruction", "")

        segments.append({
            "index": i,
            "location": {
                "lat": round(wp[0], 5),
                "lng": round(wp[1], 5),
            },
            "mile_marker": round(cumulative_miles, 1),
            "eta": eta.isoformat(),
            "turn_instruction": instruction,
            "weather": weather,
            "road_conditions": {
                "chain_control": (road or {}).get("chain_control"),
                "pavement_status": (road or {}).get("pavement_status"),
                "alerts": seg_alerts,
            },
            "severity_score": severity_score,
            "severity_label": severity_label,
        })

    return segments
```

**Step 4: Run tests**

Run: `python3 -m pytest tests/test_assembler.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add assembler.py tests/test_assembler.py
git commit -m "feat: assembler with weather merging, severity scoring, and segment building"
```

---

## Task 8: Flask App — API Endpoint and Orchestration

**Files:**
- Modify: `app.py`

**Step 1: Implement the full Flask app with `/api/route-weather` endpoint**

Replace `app.py` with the full orchestration logic:

```python
# app.py
import asyncio
from datetime import datetime, timezone, timedelta
from flask import Flask, request, jsonify, render_template

import config
from routing import fetch_route, decode_polyline, sample_waypoints, compute_etas
from weather_nws import fetch_nws_forecast, fetch_nws_alerts, find_forecast_for_time
from weather_openmeteo import fetch_openmeteo, find_data_for_time as find_openmeteo_for_time
from weather_tomorrow import fetch_tomorrow, find_data_for_time as find_tomorrow_for_time
from road_conditions import fetch_chain_controls, fetch_rwis_stations, match_rwis_to_waypoint
from assembler import merge_weather, build_segments

app = Flask(__name__)


async def fetch_all_weather(waypoints, etas):
    """Fetch weather from all 3 sources for all waypoints in parallel."""
    import aiohttp

    async with aiohttp.ClientSession() as session:
        # Open-Meteo: batch all coordinates in one call
        lats = [wp[0] for wp in waypoints]
        lons = [wp[1] for wp in waypoints]
        openmeteo_task = fetch_openmeteo(lats, lons, session=session)

        # NWS: one call per waypoint (need /points then /forecast)
        nws_tasks = [fetch_nws_forecast(wp[0], wp[1], session=session) for wp in waypoints]

        # NWS alerts: one call per waypoint
        nws_alert_tasks = [fetch_nws_alerts(wp[0], wp[1], session=session) for wp in waypoints]

        # Tomorrow.io: one call per waypoint
        tomorrow_tasks = [fetch_tomorrow(wp[0], wp[1], session=session) for wp in waypoints]

        # Road conditions: fetch all districts once
        cc_task = fetch_chain_controls(session=session)
        rwis_task = fetch_rwis_stations(session=session)

        # Gather all
        results = await asyncio.gather(
            openmeteo_task,
            asyncio.gather(*nws_tasks),
            asyncio.gather(*nws_alert_tasks),
            asyncio.gather(*tomorrow_tasks),
            cc_task,
            rwis_task,
            return_exceptions=True,
        )

    openmeteo_results = results[0] if not isinstance(results[0], Exception) else [None] * len(waypoints)
    nws_results = results[1] if not isinstance(results[1], Exception) else [None] * len(waypoints)
    nws_alerts = results[2] if not isinstance(results[2], Exception) else [[] for _ in waypoints]
    tomorrow_results = results[3] if not isinstance(results[3], Exception) else [[] for _ in waypoints]
    chain_controls = results[4] if not isinstance(results[4], Exception) else []
    rwis_stations = results[5] if not isinstance(results[5], Exception) else []

    # Process per-waypoint
    weather_data = []
    road_data = []
    alerts_by_segment = []

    for i, (wp, eta) in enumerate(zip(waypoints, etas)):
        # NWS
        nws_parsed = None
        if nws_results[i]:
            nws_parsed = find_forecast_for_time(nws_results[i], eta)

        # Open-Meteo
        openmeteo_parsed = None
        if openmeteo_results and i < len(openmeteo_results) and openmeteo_results[i]:
            openmeteo_parsed = find_openmeteo_for_time(openmeteo_results[i], eta)

        # Tomorrow.io
        tomorrow_parsed = None
        if tomorrow_results[i]:
            tomorrow_parsed = find_tomorrow_for_time(tomorrow_results[i], eta)

        merged = merge_weather(nws=nws_parsed, openmeteo=openmeteo_parsed, tomorrow=tomorrow_parsed)
        weather_data.append(merged)

        # Road conditions
        rwis_match = match_rwis_to_waypoint(rwis_stations, wp)
        road_data.append(rwis_match)

        # Alerts
        seg_alerts = nws_alerts[i] if i < len(nws_alerts) else []
        alerts_by_segment.append(seg_alerts)

    return weather_data, road_data, alerts_by_segment, chain_controls


@app.route("/api/route-weather")
def route_weather():
    origin = request.args.get("origin")
    destination = request.args.get("destination")
    departure_str = request.args.get("departure")

    if not origin or not destination or not departure_str:
        return jsonify({"error": "Missing required params: origin, destination, departure"}), 400

    try:
        departure = datetime.fromisoformat(departure_str)
    except ValueError:
        return jsonify({"error": "Invalid departure format. Use ISO 8601."}), 400

    async def do_work():
        # 1. Fetch route
        route = await fetch_route(origin, destination, departure.isoformat())

        # 2. Decode polyline and sample waypoints
        points = decode_polyline(route["polyline"])
        waypoints = sample_waypoints(points)
        etas = compute_etas(waypoints, route["total_duration_seconds"], departure)

        # 3. Fetch all weather + road data
        weather_data, road_data, alerts_by_segment, chain_controls = await fetch_all_weather(waypoints, etas)

        # 4. Build segments
        segments = build_segments(
            waypoints, etas, route["steps"],
            weather_data, road_data, alerts_by_segment,
        )

        # 5. Collect unique alerts
        all_alerts = []
        seen = set()
        for i, seg_alerts in enumerate(alerts_by_segment):
            for alert in seg_alerts:
                key = alert.get("headline", "")
                if key not in seen:
                    seen.add(key)
                    alert_with_segments = {**alert, "affected_segments": [i]}
                    all_alerts.append(alert_with_segments)
                else:
                    for a in all_alerts:
                        if a.get("headline") == key:
                            a["affected_segments"].append(i)

        total_miles = round(route["total_distance_meters"] / 1609.344, 1)
        total_minutes = round(route["total_duration_seconds"] / 60)
        arrival = departure + timedelta(seconds=route["total_duration_seconds"])

        sources = ["NWS", "Open-Meteo", "Tomorrow.io", "Caltrans CWWP2"]

        return {
            "route": {
                "summary": route["summary"],
                "total_distance_miles": total_miles,
                "total_duration_minutes": total_minutes,
                "departure": departure.isoformat(),
                "arrival": arrival.isoformat(),
                "polyline": route["polyline"],
            },
            "segments": segments,
            "alerts": all_alerts,
            "sources": sources,
        }

    result = asyncio.run(do_work())
    return jsonify(result)


@app.route("/")
def index():
    return render_template("index.html", google_api_key=config.GOOGLE_API_KEY)


if __name__ == "__main__":
    app.run(debug=True, port=5001)
```

**Step 2: Manually test the API endpoint**

Run: `python3 app.py`
Then: `curl "http://localhost:5001/api/route-weather?origin=San+Mateo,CA&destination=Mendocino,CA&departure=2026-02-21T06:00:00-08:00" | python3 -m json.tool`

Expected: JSON response with route, segments, alerts, and sources. Some weather fields may be null if API keys aren't configured yet.

**Step 3: Commit**

```bash
git add app.py
git commit -m "feat: Flask API orchestration with parallel weather fetching"
```

---

## Task 9: Frontend — HTML + Vanilla JS + Google Maps

**Files:**
- Create: `templates/index.html`

**Step 1: Implement the full frontend**

Create `templates/index.html` with:
- Input form (origin, destination, date/time, Get Route button)
- Split layout: Google Map (left) + driving instructions panel (right)
- Map shows route polyline colored by severity (green/yellow/red)
- Weather markers at each waypoint
- Instruction panel shows ETA, weather, turn instructions per segment
- Route summary bar at bottom with overall conditions
- Fog overlay (gray), wind arrows, rain intensity labels
- Alert banners for NWS advisories
- Loading spinner during API call
- Error handling for failed requests

Key frontend behaviors:
- On "Get Route" click, call `/api/route-weather` with form values
- Decode polyline and draw on map with colored segments
- Add markers at each waypoint with weather info windows
- Populate instruction panel with segment cards
- Show summary bar with top hazards

The HTML should be self-contained (inline CSS + JS, no build step). Use Google Maps JS API loaded via script tag with the API key from Flask template variable.

Default form values for testing: origin="San Mateo, CA", destination="Mendocino, CA", date/time="2026-02-21T06:00"

**Step 2: Test in browser**

Run: `python3 app.py`
Open: `http://localhost:5001/`
Click "Get Route" with default values.
Expected: Map shows route with colored segments, instruction panel populates with weather data.

**Step 3: Commit**

```bash
git add templates/index.html
git commit -m "feat: frontend with Google Maps, weather-annotated route, and driving instructions"
```

---

## Task 10: End-to-End Test — San Mateo to Mendocino

**Files:** None (manual verification)

**Step 1: Ensure API keys are configured**

Check `.env` has valid keys:
- `GOOGLE_API_KEY` — with Routes API + Maps JS API enabled
- `TOMORROW_API_KEY` — from app.tomorrow.io

**Step 2: Start the server**

Run: `python3 app.py`

**Step 3: Test the full flow**

Open `http://localhost:5001/` in browser.
- Verify default form values: San Mateo, CA → Mendocino, CA, Feb 21 2026 6:00 AM
- Click "Get Route"
- Verify: route appears on map with colored segments
- Verify: instruction panel shows ~10-15 segments with ETAs and weather
- Verify: weather data includes temperature, rain, wind, visibility
- Verify: severity colors appear on map (green/yellow/red)
- Verify: any NWS alerts show as banners
- Verify: route summary bar shows overall conditions

**Step 4: Test API directly**

```bash
curl "http://localhost:5001/api/route-weather?origin=San+Mateo,CA&destination=Mendocino,CA&departure=2026-02-21T06:00:00-08:00" | python3 -m json.tool
```

Verify JSON structure matches design doc schema.

**Step 5: Final commit**

```bash
git add -A
git commit -m "feat: drive-conditions webapp MVP complete"
```
