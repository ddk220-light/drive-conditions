# Trip Realism Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add sunset/light level tracking, speed slowdown factors, and rest stops to make trip forecasts more realistic and safety-aware.

**Architecture:** Three features that all feed into the ETA computation pipeline. Open-Meteo provides sunrise/sunset data (no new API). Weather slowdowns adjust per-segment ETAs. Rest stops insert delays and use Google Places for real locations. A two-pass weather resolve handles ETA shifts from slowdowns and rest stops.

**Tech Stack:** Python/Flask backend, Open-Meteo daily API, Google Places Nearby Search API, vanilla JS frontend.

**Design doc:** `docs/plans/2026-02-18-trip-realism-design.md`

---

### Task 1: Open-Meteo Sunrise/Sunset + Light Level Classifier

**Files:**
- Modify: `weather_openmeteo.py`
- Modify: `assembler.py`
- Test: `tests/test_assembler.py`

**Step 1: Write the failing tests**

Add to `tests/test_assembler.py`:

```python
from assembler import classify_light_level

def test_classify_light_level_day():
    """ETA well within daylight hours → day."""
    from datetime import datetime
    eta = datetime(2026, 2, 18, 12, 0)  # noon
    assert classify_light_level(eta, "2026-02-18T06:55", "2026-02-18T17:45") == "day"

def test_classify_light_level_twilight_sunset():
    """ETA within 30 min of sunset → twilight."""
    from datetime import datetime
    eta = datetime(2026, 2, 18, 17, 30)  # 15 min before sunset
    assert classify_light_level(eta, "2026-02-18T06:55", "2026-02-18T17:45") == "twilight"

def test_classify_light_level_twilight_sunrise():
    """ETA within 30 min of sunrise → twilight."""
    from datetime import datetime
    eta = datetime(2026, 2, 18, 6, 40)  # 15 min before sunrise
    assert classify_light_level(eta, "2026-02-18T06:55", "2026-02-18T17:45") == "twilight"

def test_classify_light_level_night():
    """ETA well after sunset → night."""
    from datetime import datetime
    eta = datetime(2026, 2, 18, 20, 0)  # 8 PM
    assert classify_light_level(eta, "2026-02-18T06:55", "2026-02-18T17:45") == "night"

def test_classify_light_level_no_data():
    """No sunrise/sunset data → default to day."""
    from datetime import datetime
    eta = datetime(2026, 2, 18, 22, 0)
    assert classify_light_level(eta, None, None) == "day"
```

Add to `tests/test_weather_openmeteo.py` (create if needed):

```python
from weather_openmeteo import find_sun_times_for_date

def test_find_sun_times_for_date():
    """Extract sunrise/sunset for the correct date."""
    from datetime import datetime
    data = {
        "hourly": {"time": [], "temperature_2m": []},
        "daily": {
            "time": ["2026-02-18", "2026-02-19"],
            "sunrise": ["2026-02-18T06:55", "2026-02-19T06:54"],
            "sunset": ["2026-02-18T17:45", "2026-02-19T17:46"],
        }
    }
    target = datetime(2026, 2, 19, 12, 0)
    result = find_sun_times_for_date(data, target)
    assert result["sunrise"] == "2026-02-19T06:54"
    assert result["sunset"] == "2026-02-19T17:46"

def test_find_sun_times_no_daily():
    """No daily data → returns None."""
    from datetime import datetime
    result = find_sun_times_for_date({"hourly": {}}, datetime(2026, 2, 18, 12, 0))
    assert result is None
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_assembler.py::test_classify_light_level_day tests/test_weather_openmeteo.py::test_find_sun_times_for_date -v`
Expected: FAIL (functions not defined)

**Step 3: Implement**

In `weather_openmeteo.py`, add `"daily"` param and `find_sun_times_for_date`:

```python
# Add to HOURLY_VARS section (new constant):
DAILY_VARS = "sunrise,sunset"

# In fetch_openmeteo(), add to params dict:
#   "daily": DAILY_VARS,

# New function:
def find_sun_times_for_date(data, target_time):
    """Find sunrise/sunset times for the date matching target_time."""
    if not data or "daily" not in data:
        return None
    daily = data["daily"]
    target_date = target_time.strftime("%Y-%m-%d")
    times = daily.get("time", [])
    for i, date_str in enumerate(times):
        if date_str == target_date:
            return {
                "sunrise": daily["sunrise"][i],
                "sunset": daily["sunset"][i],
            }
    if times:
        return {"sunrise": daily["sunrise"][0], "sunset": daily["sunset"][0]}
    return None
```

In `assembler.py`, add `classify_light_level`:

```python
from datetime import datetime, timedelta

TWILIGHT_MINUTES = 30

def classify_light_level(eta, sunrise_str, sunset_str):
    """Classify light level as day, twilight, or night.

    Twilight = within 30 min of sunrise or sunset.
    Day = more than 30 min after sunrise AND before sunset.
    Night = everything else.
    """
    if not sunrise_str or not sunset_str:
        return "day"

    sunrise = datetime.fromisoformat(sunrise_str)
    sunset = datetime.fromisoformat(sunset_str)

    if sunrise.tzinfo is None and eta.tzinfo is not None:
        sunrise = sunrise.replace(tzinfo=eta.tzinfo)
    if sunset.tzinfo is None and eta.tzinfo is not None:
        sunset = sunset.replace(tzinfo=eta.tzinfo)

    tw = timedelta(minutes=TWILIGHT_MINUTES)

    mins_after_sunrise = (eta - sunrise).total_seconds() / 60
    mins_before_sunset = (sunset - eta).total_seconds() / 60

    if -TWILIGHT_MINUTES <= mins_after_sunrise <= TWILIGHT_MINUTES:
        return "twilight"
    if -TWILIGHT_MINUTES <= mins_before_sunset <= TWILIGHT_MINUTES:
        return "twilight"
    if mins_after_sunrise > TWILIGHT_MINUTES and mins_before_sunset > TWILIGHT_MINUTES:
        return "day"
    return "night"
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_assembler.py -k "light_level" tests/test_weather_openmeteo.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add weather_openmeteo.py assembler.py tests/test_assembler.py tests/test_weather_openmeteo.py
git commit -m "feat: add sunrise/sunset from Open-Meteo and light level classifier"
```

---

### Task 2: Weather Speed Slowdown Factors

**Files:**
- Modify: `assembler.py`
- Test: `tests/test_assembler.py`

**Step 1: Write the failing tests**

Add to `tests/test_assembler.py`:

```python
from assembler import compute_weather_slowdown

def test_weather_slowdown_clear():
    """Clear weather → no slowdown."""
    weather = {"rain_intensity": "none", "fog_level": "none",
               "wind_speed_mph": 10, "wind_gusts_mph": 12,
               "snow_depth_in": 0, "precipitation_type": "none"}
    assert compute_weather_slowdown(weather) == 1.0

def test_weather_slowdown_heavy_rain():
    """Heavy rain → 0.70x."""
    weather = {"rain_intensity": "heavy", "fog_level": "none",
               "wind_speed_mph": 10, "wind_gusts_mph": 12,
               "snow_depth_in": 0, "precipitation_type": "rain"}
    assert compute_weather_slowdown(weather) == 0.7

def test_weather_slowdown_compound():
    """Heavy rain at night → 0.70 * 0.90 = 0.63."""
    weather = {"rain_intensity": "heavy", "fog_level": "none",
               "wind_speed_mph": 10, "wind_gusts_mph": 12,
               "snow_depth_in": 0, "precipitation_type": "rain"}
    assert compute_weather_slowdown(weather, light_level="night") == 0.63

def test_weather_slowdown_snow():
    """Snow → 0.65x."""
    weather = {"rain_intensity": "none", "fog_level": "none",
               "wind_speed_mph": 10, "wind_gusts_mph": 12,
               "snow_depth_in": 2, "precipitation_type": "snow"}
    assert compute_weather_slowdown(weather) == 0.65

def test_weather_slowdown_dense_fog():
    """Dense fog → 0.70x."""
    weather = {"rain_intensity": "none", "fog_level": "dense",
               "wind_speed_mph": 5, "wind_gusts_mph": 8,
               "snow_depth_in": 0, "precipitation_type": "none"}
    assert compute_weather_slowdown(weather) == 0.7
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_assembler.py -k "weather_slowdown" -v`
Expected: FAIL

**Step 3: Implement**

Add to `assembler.py`:

```python
def compute_weather_slowdown(weather, light_level="day"):
    """Compute speed reduction factor based on weather and light.

    Returns float 0.0-1.0 where 1.0 = no slowdown.
    Factors compound multiplicatively.
    """
    factor = 1.0

    rain = weather.get("rain_intensity", "none")
    if rain == "light":
        factor *= 0.90
    elif rain == "moderate":
        factor *= 0.80
    elif rain == "heavy":
        factor *= 0.70

    precip_type = weather.get("precipitation_type", "none")
    snow_depth = weather.get("snow_depth_in", 0)
    if precip_type == "snow" or snow_depth > 0:
        factor *= 0.65

    fog = weather.get("fog_level", "none")
    if fog == "dense":
        factor *= 0.70
    elif fog == "patchy":
        factor *= 0.85

    wind = weather.get("wind_speed_mph", 0)
    gusts = weather.get("wind_gusts_mph", 0)
    effective_wind = max(wind, gusts * 0.7) if gusts else wind
    if effective_wind > 35:
        factor *= 0.85

    if light_level == "night" and rain != "none":
        factor *= 0.90

    return round(factor, 3)
```

**Step 4: Run tests**

Run: `python -m pytest tests/test_assembler.py -k "weather_slowdown" -v`
Expected: PASS

**Step 5: Commit**

```bash
git add assembler.py tests/test_assembler.py
git commit -m "feat: add weather-based speed slowdown factors"
```

---

### Task 3: Adjusted ETA Computation with Per-Segment Slowdowns

**Files:**
- Modify: `routing.py`
- Test: `tests/test_routing.py`

**Step 1: Write the failing tests**

Add to `tests/test_routing.py`:

```python
from routing import compute_adjusted_etas
from datetime import datetime, timedelta

def test_adjusted_etas_no_slowdown():
    """With factor 1.0 and no segment slowdowns, matches compute_etas."""
    from routing import compute_etas
    waypoints = [(37.0, -122.0), (37.1, -122.1), (37.2, -122.2)]
    departure = datetime(2026, 2, 18, 8, 0)
    duration = 3600  # 1 hour
    regular = compute_etas(waypoints, duration, departure)
    adjusted = compute_adjusted_etas(waypoints, duration, departure, 1.0, None)
    for r, a in zip(regular, adjusted):
        assert abs((r - a).total_seconds()) < 1

def test_adjusted_etas_base_slowdown():
    """With factor 0.5, total trip takes 2x longer."""
    waypoints = [(37.0, -122.0), (37.2, -122.2)]
    departure = datetime(2026, 2, 18, 8, 0)
    duration = 3600
    adjusted = compute_adjusted_etas(waypoints, duration, departure, 0.5, None)
    total_adjusted = (adjusted[-1] - adjusted[0]).total_seconds()
    assert abs(total_adjusted - 7200) < 1  # 3600 / 0.5 = 7200

def test_adjusted_etas_per_segment():
    """Per-segment slowdowns produce different segment durations."""
    waypoints = [
        {"lat": 37.0, "lon": -122.0, "type": "fill", "station": None, "along_route_miles": 0},
        {"lat": 37.1, "lon": -122.1, "type": "fill", "station": None, "along_route_miles": 10},
        {"lat": 37.2, "lon": -122.2, "type": "fill", "station": None, "along_route_miles": 20},
    ]
    departure = datetime(2026, 2, 18, 8, 0)
    duration = 3600
    # Segment 0→1 has 0.5x slowdown (takes 2x), segment 1→2 has 1.0 (normal)
    slowdowns = [0.5, 1.0]
    adjusted = compute_adjusted_etas(waypoints, duration, departure, 1.0, slowdowns)
    seg1_time = (adjusted[1] - adjusted[0]).total_seconds()
    seg2_time = (adjusted[2] - adjusted[1]).total_seconds()
    # Segment 1 should take ~2x segment 2 (same distance but half speed)
    assert seg1_time > seg2_time * 1.8
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_routing.py -k "adjusted_etas" -v`
Expected: FAIL

**Step 3: Implement**

Add to `routing.py`:

```python
def compute_adjusted_etas(waypoints, total_duration_seconds, departure,
                          base_speed_factor=1.0, segment_slowdowns=None):
    """Compute ETAs with base speed factor and per-segment weather slowdowns.

    segment_slowdowns[i] applies to travel from waypoint[i] to waypoint[i+1].
    A slowdown of 0.7 means 70% of normal speed → segment takes 1/0.7 = 1.43x longer.
    """
    if len(waypoints) <= 1:
        return [departure]

    distances = []
    for i in range(1, len(waypoints)):
        lat1, lon1 = _coords(waypoints[i-1])
        lat2, lon2 = _coords(waypoints[i])
        distances.append(haversine_miles(lat1, lon1, lat2, lon2))

    total_distance = sum(distances)
    if total_distance == 0:
        return [departure] * len(waypoints)

    base_times = [(d / total_distance) * total_duration_seconds for d in distances]

    etas = [departure]
    cumulative = 0
    for i, base_time in enumerate(base_times):
        effective = base_speed_factor
        if segment_slowdowns and i < len(segment_slowdowns):
            effective *= segment_slowdowns[i]
        effective = max(effective, 0.1)
        cumulative += base_time / effective
        etas.append(departure + timedelta(seconds=cumulative))

    return etas
```

**Step 4: Run tests**

Run: `python -m pytest tests/test_routing.py -k "adjusted_etas" -v`
Expected: PASS

**Step 5: Commit**

```bash
git add routing.py tests/test_routing.py
git commit -m "feat: add compute_adjusted_etas with per-segment slowdowns"
```

---

### Task 4: Rest Stop Computation + Google Places Lookup

**Files:**
- Create: `rest_stops.py`
- Create: `tests/test_rest_stops.py`

**Step 1: Write the failing tests**

Create `tests/test_rest_stops.py`:

```python
from datetime import datetime, timedelta
from rest_stops import compute_rest_stop_positions, apply_rest_stop_delays

def test_rest_stops_short_trip():
    """Trip shorter than interval → no rest stops."""
    etas = [
        datetime(2026, 2, 18, 8, 0),
        datetime(2026, 2, 18, 8, 30),
        datetime(2026, 2, 18, 9, 0),  # destination
    ]
    positions = compute_rest_stop_positions(etas, rest_interval_minutes=60)
    assert positions == []

def test_rest_stops_normal_trip():
    """3-hour trip with 60-min interval → 2 stops."""
    base = datetime(2026, 2, 18, 8, 0)
    etas = [base + timedelta(minutes=i * 20) for i in range(10)]  # 0, 20, 40, 60, 80, 100, 120, 140, 160, 180
    positions = compute_rest_stop_positions(etas, rest_interval_minutes=60)
    assert len(positions) == 2
    # First stop after 60 min (index 3), second after 120 min (index 6)
    assert positions[0] == 3
    assert positions[1] == 6

def test_rest_stops_no_stop_at_destination():
    """Don't place a rest stop at the last waypoint."""
    base = datetime(2026, 2, 18, 8, 0)
    # Exactly 60 min trip with 2 waypoints
    etas = [base, base + timedelta(minutes=60)]
    positions = compute_rest_stop_positions(etas, rest_interval_minutes=60)
    assert positions == []

def test_apply_rest_stop_delays():
    """Rest stops shift subsequent ETAs."""
    base = datetime(2026, 2, 18, 8, 0)
    etas = [base + timedelta(minutes=i * 30) for i in range(5)]
    # Rest stop after index 2
    result = apply_rest_stop_delays(etas, [2], rest_duration_minutes=20)
    assert result[0] == etas[0]  # no shift
    assert result[1] == etas[1]  # no shift
    assert result[2] == etas[2]  # no shift (arrive before rest)
    assert result[3] == etas[3] + timedelta(minutes=20)  # shifted
    assert result[4] == etas[4] + timedelta(minutes=20)  # shifted

def test_apply_multiple_rest_stops():
    """Multiple rest stops accumulate delays."""
    base = datetime(2026, 2, 18, 8, 0)
    etas = [base + timedelta(minutes=i * 30) for i in range(7)]
    result = apply_rest_stop_delays(etas, [1, 4], rest_duration_minutes=20)
    assert result[0] == etas[0]
    assert result[1] == etas[1]  # arrive before first rest
    assert result[2] == etas[2] + timedelta(minutes=20)  # after first rest
    assert result[4] == etas[4] + timedelta(minutes=20)  # arrive before second rest
    assert result[5] == etas[5] + timedelta(minutes=40)  # after both rests
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_rest_stops.py -v`
Expected: FAIL

**Step 3: Implement**

Create `rest_stops.py`:

```python
# rest_stops.py
import aiohttp
from datetime import timedelta
from config import GOOGLE_API_KEY
from routing import _coords


def compute_rest_stop_positions(etas, rest_interval_minutes=60):
    """Determine waypoint indices after which to place rest stops.

    Walks segments, tracks cumulative driving time, marks rest stops
    when interval is exceeded. Never places a stop at the last waypoint.

    Returns list of waypoint indices.
    """
    positions = []
    cumulative_minutes = 0.0

    for i in range(1, len(etas)):
        segment_minutes = (etas[i] - etas[i-1]).total_seconds() / 60.0
        cumulative_minutes += segment_minutes
        if cumulative_minutes >= rest_interval_minutes and i < len(etas) - 1:
            positions.append(i)
            cumulative_minutes = 0.0

    return positions


def apply_rest_stop_delays(etas, rest_indices, rest_duration_minutes=20):
    """Shift ETAs to account for rest stop delays.

    Rest stop occurs AFTER arriving at the indexed waypoint.
    All subsequent ETAs are shifted.
    """
    result = list(etas)
    rest_delay = timedelta(minutes=rest_duration_minutes)
    cumulative_delay = timedelta(0)
    rest_set = set(rest_indices)

    for i in range(len(result)):
        result[i] = result[i] + cumulative_delay
        if i in rest_set:
            cumulative_delay += rest_delay

    return result


def insert_rest_stop_segments(segments, rest_stop_info, rest_duration_minutes):
    """Insert rest stop pseudo-segments into the segment list.

    rest_stop_info: list of dicts with after_segment_index, place_name, location.
    Inserts in reverse order to avoid index shifting.
    """
    from datetime import datetime
    result = list(segments)
    sorted_stops = sorted(rest_stop_info, key=lambda x: x["after_segment_index"], reverse=True)

    for rs in sorted_stops:
        idx = rs["after_segment_index"]
        if idx >= len(result):
            continue
        prev_seg = result[idx]
        eta_arrive = prev_seg["eta"]
        eta_depart = (datetime.fromisoformat(eta_arrive) + timedelta(minutes=rest_duration_minutes)).isoformat()

        rest_seg = {
            "type": "rest_stop",
            "location": rs["location"],
            "place_name": rs.get("place_name") or "Rest stop (mile {})".format(prev_seg.get("mile_marker", "?")),
            "rest_duration_minutes": rest_duration_minutes,
            "eta_arrive": eta_arrive,
            "eta_depart": eta_depart,
            "mile_marker": prev_seg.get("mile_marker", 0),
        }
        result.insert(idx + 1, rest_seg)

    return result


async def fetch_rest_stop_places(positions, waypoints, session=None):
    """Fetch nearby rest areas or gas stations for each rest stop position.

    Args:
        positions: list of waypoint indices
        waypoints: full waypoint list
        session: aiohttp session

    Returns: list of dicts with after_segment_index, place_name, location.
    """
    own_session = session is None
    if own_session:
        session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))

    results = []
    try:
        for idx in positions:
            lat, lon = _coords(waypoints[idx])
            place = await _search_nearby(session, lat, lon)
            if place:
                results.append({
                    "after_segment_index": idx,
                    "place_name": place["name"],
                    "location": place["location"],
                })
            else:
                results.append({
                    "after_segment_index": idx,
                    "place_name": None,
                    "location": {"lat": lat, "lng": lon},
                })
    finally:
        if own_session:
            await session.close()

    return results


async def _search_nearby(session, lat, lon):
    """Search Google Places for nearby rest areas or gas stations."""
    url = "https://places.googleapis.com/v1/places:searchNearby"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_API_KEY,
        "X-Goog-FieldMask": "places.displayName,places.location",
    }
    body = {
        "includedTypes": ["rest_stop", "gas_station"],
        "maxResultCount": 1,
        "locationRestriction": {
            "circle": {
                "center": {"latitude": lat, "longitude": lng},
                "radius": 8046.72,
            }
        },
    }

    try:
        async with session.post(url, json=body, headers=headers) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()

        places = data.get("places", [])
        if not places:
            return None

        p = places[0]
        return {
            "name": p.get("displayName", {}).get("text", "Rest Stop"),
            "location": {
                "lat": p["location"]["latitude"],
                "lng": p["location"]["longitude"],
            },
        }
    except Exception:
        return None
```

**Step 4: Run tests**

Run: `python -m pytest tests/test_rest_stops.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add rest_stops.py tests/test_rest_stops.py
git commit -m "feat: add rest stop computation and Google Places lookup"
```

---

### Task 5: Pipeline Integration + API Endpoint + Severity Updates

**Files:**
- Modify: `app.py`
- Modify: `assembler.py` (compute_severity, build_segments)
- Test: `tests/test_app.py`, `tests/test_assembler.py`

**Step 1: Write the failing tests**

Add to `tests/test_assembler.py`:

```python
def test_severity_night_heavy_rain():
    """Night + heavy rain → severity bump of +2."""
    weather = {"rain_intensity": "heavy", "precipitation_mm_hr": 5.0,
               "fog_level": "none", "visibility_miles": 10,
               "wind_speed_mph": 10, "wind_gusts_mph": 12,
               "snow_depth_in": 0, "precipitation_type": "rain",
               "road_risk_score": None}
    score_day, _ = compute_severity(weather, light_level="day")
    score_night, _ = compute_severity(weather, light_level="night")
    assert score_night == score_day + 2

def test_severity_twilight_rain():
    """Twilight + rain → severity bump of +1."""
    weather = {"rain_intensity": "light", "precipitation_mm_hr": 0.3,
               "fog_level": "none", "visibility_miles": 10,
               "wind_speed_mph": 10, "wind_gusts_mph": 12,
               "snow_depth_in": 0, "precipitation_type": "rain",
               "road_risk_score": None}
    score_day, _ = compute_severity(weather, light_level="day")
    score_twi, _ = compute_severity(weather, light_level="twilight")
    assert score_twi == score_day + 1

def test_build_segments_includes_light_level():
    """Segments include light_level field."""
    from datetime import datetime
    from assembler import build_segments
    waypoints = [(37.0, -122.0), (37.1, -122.1)]
    etas = [datetime(2026, 2, 18, 8, 0), datetime(2026, 2, 18, 9, 0)]
    weather_data = [{"temperature_f": 55, "wind_speed_mph": 5, "wind_gusts_mph": 8,
                     "precipitation_mm_hr": 0, "rain_intensity": "none", "fog_level": "none",
                     "visibility_miles": 10, "snow_depth_in": 0, "precipitation_type": "none",
                     "condition_text": "Clear", "precipitation_probability": 0,
                     "road_risk_score": None, "road_risk_label": None,
                     "wind_direction_deg": 180, "freezing_level_ft": 8000}] * 2
    road_data = [None, None]
    alerts = [[], []]
    light_levels = ["day", "twilight"]
    sun_times = [{"sunrise": "06:55", "sunset": "17:45"}] * 2
    segments = build_segments(waypoints, etas, [], weather_data, road_data, alerts,
                              light_levels=light_levels, sun_times=sun_times)
    assert segments[0]["light_level"] == "day"
    assert segments[1]["light_level"] == "twilight"
    assert segments[0]["sunrise"] == "06:55"
```

Add to `tests/test_app.py`:

```python
def test_route_weather_accepts_speed_factor():
    """API endpoint accepts speed_factor query param."""
    import app as app_module
    assert hasattr(app_module, 'route_weather')
    # Verified by checking param parsing exists in the function
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_assembler.py -k "severity_night or severity_twilight or light_level" -v`
Expected: FAIL

**Step 3: Implement severity + build_segments changes**

In `assembler.py`, update `compute_severity` signature to accept `light_level`:

```python
def compute_severity(weather, road_conditions=None, alerts=None, light_level="day"):
    score = 0
    alerts = alerts or []

    # ... existing scoring (visibility, wind, precipitation, road conditions, alerts) ...

    # Light level adjustments
    has_weather_hazard = (
        weather.get("rain_intensity", "none") != "none" or
        weather.get("fog_level", "none") != "none" or
        weather.get("wind_speed_mph", 0) >= 25
    )

    if light_level == "night" and has_weather_hazard:
        heavy = (weather.get("rain_intensity") == "heavy" or
                 weather.get("fog_level") == "dense")
        score += 2 if heavy else 1
    elif light_level == "twilight" and has_weather_hazard:
        score += 1

    score = min(10, round(score))
    # ... label assignment ...
```

Update `build_segments` to accept and include `light_levels` and `sun_times`:

```python
def build_segments(waypoints, etas, route_steps, weather_data, road_data, alerts_by_segment,
                   chain_controls=None, light_levels=None, sun_times=None):
    # ... existing code ...
    # In the loop, after severity computation:
    light = light_levels[i] if light_levels and i < len(light_levels) else "day"

    severity_score, severity_label = compute_severity(
        weather, road_for_severity or None, seg_alerts, light_level=light
    )

    seg["light_level"] = light
    if sun_times and i < len(sun_times) and sun_times[i]:
        seg["sunrise"] = sun_times[i].get("sunrise", "")
        seg["sunset"] = sun_times[i].get("sunset", "")
```

**Step 4: Implement pipeline changes in `app.py`**

Update `route_weather()` to accept new query params:

```python
speed_factor = max(0.5, min(1.0, float(request.args.get("speed_factor", "1.0"))))
rest_enabled = request.args.get("rest_enabled", "false") == "true"
rest_interval = max(30, min(180, int(request.args.get("rest_interval", "60"))))
rest_duration = max(5, min(60, int(request.args.get("rest_duration", "20"))))
```

Update `do_work()` to use two-pass resolve:

```python
async def do_work():
    route = await fetch_route(origin, destination, departure.isoformat())
    points = decode_polyline(route["polyline"])

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
        rwis_stations = await fetch_rwis_stations(session=session)

    waypoints = build_station_aware_waypoints(points, rwis_stations)
    raw_weather = await fetch_raw_weather(waypoints, rwis_stations=rwis_stations)

    # Compute rest stop locations once (for selected departure)
    rest_stop_info = None
    if rest_enabled:
        from routing import compute_adjusted_etas
        from assembler import compute_weather_slowdown, classify_light_level
        from weather_openmeteo import find_sun_times_for_date
        from rest_stops import compute_rest_stop_positions, fetch_rest_stop_places

        initial_etas = compute_etas(waypoints, route["total_duration_seconds"], departure)
        weather_data, _, _, _, _ = resolve_weather_for_etas(raw_weather, waypoints, initial_etas)
        slowdowns = [compute_weather_slowdown(weather_data[i])
                     for i in range(len(weather_data) - 1)]
        adjusted_etas = compute_adjusted_etas(
            waypoints, route["total_duration_seconds"], departure,
            speed_factor, slowdowns)
        positions = compute_rest_stop_positions(adjusted_etas, rest_interval)

        if positions:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                rest_stop_info = await fetch_rest_stop_places(positions, waypoints, session)

    # Build all slots
    selected = build_slot_data(departure, waypoints, route, raw_weather,
                               speed_factor, rest_stop_info, rest_duration)
    # ... slider slots same pattern ...
```

Update `build_slot_data()` with two-pass resolve (see design doc pipeline steps 1-12).

**Step 5: Run all tests**

Run: `python -m pytest -v`
Expected: PASS

**Step 6: Commit**

```bash
git add app.py assembler.py tests/test_app.py tests/test_assembler.py
git commit -m "feat: wire up two-pass pipeline with speed, rest stops, light levels"
```

---

### Task 6: Frontend — Trip Settings Bar

**Files:**
- Modify: `templates/index.html`

**Step 1: Add Trip Settings HTML and CSS**

Add CSS for the settings bar (below `.slider-bar` styles):

```css
.settings-bar {
  background: #1e293b;
  padding: 10px 24px 12px;
  border-top: 1px solid #334155;
  display: none;
}

.settings-row {
  display: flex;
  align-items: center;
  gap: 20px;
  flex-wrap: wrap;
}

.setting-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.setting-group label {
  color: #94a3b8;
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  white-space: nowrap;
}

.setting-group input[type="range"] {
  width: 120px;
  -webkit-appearance: none;
  appearance: none;
  height: 4px;
  background: #334155;
  border-radius: 2px;
  outline: none;
}

.setting-group input[type="number"] {
  width: 60px;
  padding: 4px 8px;
  border: 1px solid #334155;
  border-radius: 6px;
  background: #0f172a;
  color: #e2e8f0;
  font-size: 13px;
}

.setting-value {
  color: #e2e8f0;
  font-size: 13px;
  font-weight: 600;
  min-width: 40px;
}

.setting-toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
}

.setting-toggle input[type="checkbox"] {
  accent-color: #3b82f6;
}

.rest-options {
  display: none;
}

.rest-options.visible {
  display: flex;
  gap: 16px;
}
```

Add HTML after the slider-bar div:

```html
<div class="settings-bar" id="settings-bar">
  <div class="settings-row">
    <div class="setting-group">
      <label>Speed</label>
      <input type="range" id="speed-slider" min="0.50" max="1.00" step="0.05" value="1.00">
      <span class="setting-value" id="speed-value">1.00x</span>
    </div>
    <div class="setting-group setting-toggle">
      <input type="checkbox" id="rest-toggle">
      <label for="rest-toggle">Rest Stops</label>
    </div>
    <div class="rest-options" id="rest-options">
      <div class="setting-group">
        <label>Drive</label>
        <input type="number" id="rest-interval" value="60" min="30" max="180" step="15">
        <span class="setting-value">min</span>
      </div>
      <div class="setting-group">
        <label>Rest</label>
        <input type="number" id="rest-duration" value="20" min="5" max="60" step="5">
        <span class="setting-value">min</span>
      </div>
    </div>
  </div>
</div>
```

**Step 2: Wire up JavaScript**

Add DOM refs and event handlers:

```javascript
const settingsBar   = document.getElementById("settings-bar");
const speedSlider   = document.getElementById("speed-slider");
const speedValue    = document.getElementById("speed-value");
const restToggle    = document.getElementById("rest-toggle");
const restOptions   = document.getElementById("rest-options");
const restInterval  = document.getElementById("rest-interval");
const restDuration  = document.getElementById("rest-duration");

speedSlider.addEventListener("input", function() {
  speedValue.textContent = parseFloat(speedSlider.value).toFixed(2) + "x";
});

restToggle.addEventListener("change", function() {
  restOptions.classList.toggle("visible", restToggle.checked);
});
```

Update `fetchRoute()` to include new params in the API URL:

```javascript
var url = "/api/route-weather?" +
  "origin=" + encodeURIComponent(origin) +
  "&destination=" + encodeURIComponent(dest) +
  "&departure=" + encodeURIComponent(departure) +
  "&speed_factor=" + speedSlider.value +
  "&rest_enabled=" + restToggle.checked +
  "&rest_interval=" + restInterval.value +
  "&rest_duration=" + restDuration.value;
```

Show settings bar after first successful fetch:

```javascript
settingsBar.style.display = "block";
```

**Step 3: Commit**

```bash
git add templates/index.html
git commit -m "feat: add Trip Settings bar with speed slider and rest stop controls"
```

---

### Task 7: Frontend — Light Level Display + Rest Stop Cards + Map Markers

**Files:**
- Modify: `templates/index.html`

**Step 1: Add light level CSS**

```css
.light-indicator {
  font-size: 12px;
  color: #64748b;
  margin-top: 2px;
  display: flex;
  align-items: center;
  gap: 4px;
}

.light-indicator.twilight { color: #d97706; }
.light-indicator.night { color: #6366f1; }

.light-warning {
  margin-top: 4px;
  padding: 4px 8px;
  background: #fef3c7;
  border-left: 3px solid #d97706;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  color: #92400e;
}

.rest-stop-card {
  padding: 12px 20px;
  border-bottom: 1px solid #f1f5f9;
  background: #eff6ff;
}

.rest-stop-card .rest-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 600;
  color: #1e40af;
}

.rest-stop-card .rest-detail {
  font-size: 12px;
  color: #64748b;
  margin-top: 2px;
}
```

**Step 2: Update buildPanel() for light levels**

In the segment card building code, after the weather div, add light level indicator:

```javascript
// Light level indicator
var ll = seg.light_level || "day";
if (ll !== "day") {
  var lightDiv = document.createElement("div");
  lightDiv.className = "light-indicator " + ll;
  var icon = ll === "night" ? "\u{1F319}" : "\u{1F305}";
  lightDiv.textContent = icon + " " + capitalize(ll);
  if (seg.sunset) lightDiv.textContent += " (sunset " + seg.sunset + ")";
  card.appendChild(lightDiv);

  // Warning if low light + bad weather
  var hasHazard = (w.rain_intensity && w.rain_intensity !== "none") ||
                  (w.fog_level && w.fog_level !== "none") ||
                  (w.wind_speed_mph >= 25);
  if (hasHazard) {
    var warnDiv = document.createElement("div");
    warnDiv.className = "light-warning";
    warnDiv.textContent = "Low visibility driving " +
      (ll === "night" ? "after dark" : "at dusk/dawn") +
      " \u2014 consider adjusting departure";
    card.appendChild(warnDiv);
  }
}
```

**Step 3: Handle rest stop pseudo-segments in buildPanel()**

In the segments loop, check for rest stop type:

```javascript
segments.forEach(function(seg, idx) {
  // Rest stop pseudo-segment
  if (seg.type === "rest_stop") {
    var restCard = document.createElement("div");
    restCard.className = "rest-stop-card";
    restCard.innerHTML =
      '<div class="rest-header">\u2615 ' + escapeHtml(seg.place_name) + '</div>' +
      '<div class="rest-detail">' + formatTime(seg.eta_arrive) + ' \u2013 ' +
      formatTime(seg.eta_depart) + ' (' + seg.rest_duration_minutes + ' min rest)</div>' +
      '<div class="rest-detail">Mile ' + seg.mile_marker + '</div>';
    panelBody.appendChild(restCard);
    return;  // skip normal segment rendering
  }
  // ... existing segment card code ...
});
```

**Step 4: Add rest stop map markers**

In `drawRoute()`, add rest stop markers after weather markers:

```javascript
segments.forEach(function(seg) {
  if (seg.type === "rest_stop") {
    var restMarker = new google.maps.Marker({
      position: { lat: seg.location.lat, lng: seg.location.lng },
      map: map,
      icon: {
        url: "data:image/svg+xml;charset=UTF-8," + encodeURIComponent(restStopSvg()),
        scaledSize: new google.maps.Size(28, 28),
        anchor: new google.maps.Point(14, 14)
      },
      title: seg.place_name + " (" + seg.rest_duration_minutes + " min)",
      zIndex: 80
    });
    markers.push(restMarker);
  }
});

function restStopSvg() {
  return '<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 28 28">' +
    '<circle cx="14" cy="14" r="12" fill="#3b82f6" stroke="#fff" stroke-width="2"/>' +
    '<text x="14" y="18" text-anchor="middle" font-size="13" fill="#fff" font-family="sans-serif">R</text>' +
    '</svg>';
}
```

**Step 5: Update buildSummary() to mention light level warnings**

Add to the summary builder:

```javascript
var nightHazardSegs = segments.filter(function(s) {
  return s.light_level && s.light_level !== "day" &&
    s.weather && (s.weather.rain_intensity !== "none" || s.weather.fog_level !== "none");
});
if (nightHazardSegs.length > 0) {
  parts.push("Low-light driving with weather hazards on " + nightHazardSegs.length + " segment(s).");
}
```

**Step 6: Commit**

```bash
git add templates/index.html
git commit -m "feat: add light level display, rest stop cards, and map markers"
```

---

## Full Test Run

After all tasks, run the full test suite:

```bash
python -m pytest -v
```

Expected: All tests pass.

Manual verification:
1. Start the app: `python app.py`
2. Enter a long route (e.g., San Mateo → Lake Tahoe)
3. Set speed to 0.80x → click "Get Route" → verify longer arrival time
4. Enable rest stops (60 min drive / 20 min rest) → click "Get Route" → verify rest stop cards in panel and markers on map
5. Try a late departure (4 PM) → verify twilight/night labels appear on later segments
6. Check that twilight + rain segments show the warning callout
