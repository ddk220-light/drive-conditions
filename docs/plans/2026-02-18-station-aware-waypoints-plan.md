# Station-Aware Waypoints Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace fixed 15-mile interval waypoint sampling with RWIS station-aware placement that maximizes real ground-truth road condition data along the route.

**Architecture:** Fetch RWIS stations early (before waypoint selection). Match stations to the route polyline within 15 miles. Place waypoints at matched station locations, then fill gaps > 30 miles with 15-mile interval points. Each waypoint is tagged `"rwis"` or `"fill"` so downstream code and frontend can distinguish data quality.

**Tech Stack:** Python/Flask, existing Caltrans RWIS API, existing routing/weather modules

---

### Task 1: Add config constants and helper for polyline distance projection

**Files:**
- Modify: `config.py:12-13`
- Modify: `routing.py:37-69`
- Test: `tests/test_routing.py`

**Step 1: Write the failing tests**

Add to `tests/test_routing.py`:

```python
from routing import haversine_miles, find_closest_polyline_point


def test_find_closest_polyline_point_on_route():
    """A point near the middle of a polyline should return its along-route distance."""
    # Straight line from (37.0, -122.0) to (39.0, -122.0) ~138 miles
    points = [(37.0, -122.0), (37.5, -122.0), (38.0, -122.0), (38.5, -122.0), (39.0, -122.0)]
    # Station at (38.0, -121.95) — very close to polyline at (38.0, -122.0)
    dist_from_route, along_route_miles = find_closest_polyline_point(points, 38.0, -121.95)
    assert dist_from_route < 5.0  # within 5 miles of route
    # Along-route miles should be roughly half the total route
    total = sum(haversine_miles(points[i][0], points[i][1], points[i+1][0], points[i+1][1])
                for i in range(len(points) - 1))
    assert 0.4 * total < along_route_miles < 0.6 * total


def test_find_closest_polyline_point_far_away():
    """A point far from the polyline should return large distance."""
    points = [(37.0, -122.0), (38.0, -122.0), (39.0, -122.0)]
    dist_from_route, along_route_miles = find_closest_polyline_point(points, 35.0, -118.0)
    assert dist_from_route > 100  # far from route
```

**Step 2: Run tests to verify they fail**

Run: `venv/bin/pytest tests/test_routing.py::test_find_closest_polyline_point_on_route tests/test_routing.py::test_find_closest_polyline_point_far_away -v`
Expected: FAIL with `ImportError: cannot import name 'find_closest_polyline_point'`

**Step 3: Add config constants and implement the helper**

Add to `config.py` after line 13:

```python
RWIS_SNAP_RADIUS_MILES = 15
RWIS_MIN_STATION_SPACING_MILES = 5
GAP_FILL_THRESHOLD_MILES = 30
```

Add to `routing.py` after `haversine_miles` (after line 45):

```python
def find_closest_polyline_point(points, lat, lon):
    """Find the closest point on a polyline to a given lat/lon.

    Returns (distance_from_route_miles, along_route_miles).
    distance_from_route_miles: straight-line distance from (lat, lon) to nearest polyline point.
    along_route_miles: cumulative distance along the polyline to that nearest point.
    """
    best_dist = float("inf")
    best_along = 0.0
    cumulative = 0.0

    for i, pt in enumerate(points):
        if i > 0:
            cumulative += haversine_miles(points[i-1][0], points[i-1][1], pt[0], pt[1])
        d = haversine_miles(pt[0], pt[1], lat, lon)
        if d < best_dist:
            best_dist = d
            best_along = cumulative

    return best_dist, best_along
```

**Step 4: Run tests to verify they pass**

Run: `venv/bin/pytest tests/test_routing.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add config.py routing.py tests/test_routing.py
git commit -m "feat: add find_closest_polyline_point and station-aware config constants"
```

---

### Task 2: Implement `build_station_aware_waypoints`

**Files:**
- Modify: `routing.py`
- Test: `tests/test_routing.py`

**Step 1: Write the failing tests**

Add to `tests/test_routing.py`:

```python
from routing import build_station_aware_waypoints


def test_station_aware_waypoints_with_stations():
    """Stations near route become waypoints; origin and destination always included."""
    # Route: roughly 100-mile straight line
    points = [(37.0, -122.0), (37.5, -122.0), (38.0, -122.0), (38.5, -122.0), (39.0, -122.0)]
    stations = [
        {"location": {"latitude": 38.0, "longitude": -121.98, "locationName": "Mid Station"}},
    ]
    result = build_station_aware_waypoints(points, stations)
    assert len(result) >= 3  # origin + station + destination at minimum
    # First should be origin (fill), last should be destination (fill)
    assert result[0]["type"] == "fill"
    assert result[-1]["type"] == "fill"
    # Station should be in there
    rwis_wps = [w for w in result if w["type"] == "rwis"]
    assert len(rwis_wps) == 1
    assert rwis_wps[0]["station"]["location"]["locationName"] == "Mid Station"


def test_station_aware_waypoints_no_stations():
    """With no stations, should fall back to 15-mile interval fill waypoints."""
    points = [(37.0, -122.0), (37.5, -122.0), (38.0, -122.0), (38.5, -122.0), (39.0, -122.0)]
    result = build_station_aware_waypoints(points, [])
    assert len(result) >= 3
    assert all(w["type"] == "fill" for w in result)


def test_station_aware_waypoints_deduplicates_close_stations():
    """Stations < 5 miles apart: only keep first one."""
    points = [(37.0, -122.0), (38.0, -122.0), (39.0, -122.0)]
    stations = [
        {"location": {"latitude": 38.0, "longitude": -122.0, "locationName": "Station A"}},
        {"location": {"latitude": 38.02, "longitude": -122.0, "locationName": "Station B"}},  # ~1.4 miles from A
    ]
    result = build_station_aware_waypoints(points, stations)
    rwis_wps = [w for w in result if w["type"] == "rwis"]
    assert len(rwis_wps) == 1  # Station B skipped (too close to A)


def test_station_aware_waypoints_fills_gaps():
    """Gaps > 30 miles between stations get fill waypoints at 15-mile intervals."""
    # Route: ~138 miles. Stations only at start and end area.
    points = [(37.0, -122.0), (37.5, -122.0), (38.0, -122.0), (38.5, -122.0), (39.0, -122.0)]
    stations = [
        {"location": {"latitude": 37.05, "longitude": -122.0, "locationName": "Near Start"}},
    ]
    result = build_station_aware_waypoints(points, stations)
    # There should be fill waypoints covering the 100+ mile gap after the station
    fill_wps = [w for w in result if w["type"] == "fill"]
    assert len(fill_wps) >= 4  # origin + destination + at least 2 gap fills
```

**Step 2: Run tests to verify they fail**

Run: `venv/bin/pytest tests/test_routing.py::test_station_aware_waypoints_with_stations tests/test_routing.py::test_station_aware_waypoints_no_stations tests/test_routing.py::test_station_aware_waypoints_deduplicates_close_stations tests/test_routing.py::test_station_aware_waypoints_fills_gaps -v`
Expected: FAIL with `ImportError: cannot import name 'build_station_aware_waypoints'`

**Step 3: Implement `build_station_aware_waypoints`**

Add to `routing.py` after `sample_waypoints`:

```python
def build_station_aware_waypoints(points, rwis_stations,
                                   snap_radius=None, min_spacing=None,
                                   gap_threshold=None, fill_interval=None):
    """Build waypoints prioritizing RWIS station locations along the route.

    Args:
        points: Decoded polyline points [(lat, lon), ...].
        rwis_stations: List of RWIS station dicts with location.latitude/longitude.
        snap_radius: Max miles from route to consider a station (default RWIS_SNAP_RADIUS_MILES).
        min_spacing: Min miles between adjacent stations (default RWIS_MIN_STATION_SPACING_MILES).
        gap_threshold: Miles beyond which to insert fill waypoints (default GAP_FILL_THRESHOLD_MILES).
        fill_interval: Miles between fill waypoints in gaps (default WAYPOINT_INTERVAL_MILES).

    Returns:
        List of dicts: {"lat": float, "lon": float, "type": "rwis"|"fill",
                        "station": <station dict>|None, "along_route_miles": float}
    """
    from config import (RWIS_SNAP_RADIUS_MILES, RWIS_MIN_STATION_SPACING_MILES,
                        GAP_FILL_THRESHOLD_MILES, WAYPOINT_INTERVAL_MILES)
    if snap_radius is None:
        snap_radius = RWIS_SNAP_RADIUS_MILES
    if min_spacing is None:
        min_spacing = RWIS_MIN_STATION_SPACING_MILES
    if gap_threshold is None:
        gap_threshold = GAP_FILL_THRESHOLD_MILES
    if fill_interval is None:
        fill_interval = WAYPOINT_INTERVAL_MILES

    if len(points) <= 1:
        return [{"lat": points[0][0], "lon": points[0][1], "type": "fill",
                 "station": None, "along_route_miles": 0.0}]

    # Compute total route length
    cumulative_dists = [0.0]
    for i in range(1, len(points)):
        d = haversine_miles(points[i-1][0], points[i-1][1], points[i][0], points[i][1])
        cumulative_dists.append(cumulative_dists[-1] + d)
    total_route_miles = cumulative_dists[-1]

    # Match stations to route
    candidates = []
    for station in rwis_stations:
        loc = station.get("location", {})
        slat = loc.get("latitude")
        slon = loc.get("longitude")
        if slat is None or slon is None:
            continue
        dist_from_route, along_miles = find_closest_polyline_point(points, slat, slon)
        if dist_from_route <= snap_radius:
            candidates.append({
                "station": station,
                "lat": slat,
                "lon": slon,
                "along_route_miles": along_miles,
                "dist_from_route": dist_from_route,
            })

    # Sort by along-route position
    candidates.sort(key=lambda c: c["along_route_miles"])

    # Deduplicate: skip stations too close to previous
    station_waypoints = []
    for c in candidates:
        if station_waypoints:
            prev = station_waypoints[-1]
            if abs(c["along_route_miles"] - prev["along_route_miles"]) < min_spacing:
                continue
        station_waypoints.append(c)

    # Build final waypoint list with origin, stations, destination, and gap fills
    result = []

    # Origin
    origin = {"lat": points[0][0], "lon": points[0][1], "type": "fill",
              "station": None, "along_route_miles": 0.0}
    result.append(origin)

    # Insert station waypoints
    for sw in station_waypoints:
        result.append({
            "lat": sw["lat"], "lon": sw["lon"], "type": "rwis",
            "station": sw["station"], "along_route_miles": sw["along_route_miles"],
        })

    # Destination
    dest = {"lat": points[-1][0], "lon": points[-1][1], "type": "fill",
            "station": None, "along_route_miles": total_route_miles}
    result.append(dest)

    # Sort everything by along_route_miles
    result.sort(key=lambda w: w["along_route_miles"])

    # Fill gaps
    filled = []
    for i, wp in enumerate(result):
        filled.append(wp)
        if i < len(result) - 1:
            gap = result[i+1]["along_route_miles"] - wp["along_route_miles"]
            if gap > gap_threshold:
                # Insert fill waypoints at fill_interval spacing
                num_fills = int(gap / fill_interval)
                for f in range(1, num_fills + 1):
                    target_miles = wp["along_route_miles"] + f * fill_interval
                    if target_miles >= result[i+1]["along_route_miles"]:
                        break
                    # Find the polyline point closest to target_miles
                    fill_pt = _interpolate_along_route(points, cumulative_dists, target_miles)
                    filled.append({
                        "lat": fill_pt[0], "lon": fill_pt[1], "type": "fill",
                        "station": None, "along_route_miles": target_miles,
                    })

    # Re-sort after filling
    filled.sort(key=lambda w: w["along_route_miles"])
    return filled


def _interpolate_along_route(points, cumulative_dists, target_miles):
    """Find the polyline point at a given distance along the route."""
    for i in range(1, len(points)):
        if cumulative_dists[i] >= target_miles:
            return points[i]
    return points[-1]
```

**Step 4: Run tests to verify they pass**

Run: `venv/bin/pytest tests/test_routing.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add routing.py tests/test_routing.py
git commit -m "feat: add build_station_aware_waypoints with gap filling"
```

---

### Task 3: Refactor `fetch_raw_weather` to accept external RWIS stations

**Files:**
- Modify: `app.py:50-106`
- Test: `tests/test_app.py`

**Step 1: Write the failing test**

Add to `tests/test_app.py`:

```python
def test_fetch_raw_weather_accepts_rwis_stations_param():
    """fetch_raw_weather should accept an optional rwis_stations parameter."""
    import inspect
    from app import fetch_raw_weather
    sig = inspect.signature(fetch_raw_weather)
    assert "rwis_stations" in sig.parameters, "fetch_raw_weather should accept rwis_stations param"
```

**Step 2: Run test to verify it fails**

Run: `venv/bin/pytest tests/test_app.py::test_fetch_raw_weather_accepts_rwis_stations_param -v`
Expected: FAIL with `AssertionError: fetch_raw_weather should accept rwis_stations param`

**Step 3: Refactor `fetch_raw_weather`**

In `app.py`, change the signature and body of `fetch_raw_weather` (lines 50-106):

```python
async def fetch_raw_weather(waypoints, rwis_stations=None):
    """Fetch raw weather data from all sources (no ETA lookup).

    Args:
        waypoints: List of waypoint dicts with 'lat' and 'lon' keys,
                   or tuples of (lat, lon).
        rwis_stations: Pre-fetched RWIS stations. If None, fetches them.
    """
    import aiohttp

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
        # Extract lat/lon from waypoints (support both dict and tuple formats)
        if waypoints and isinstance(waypoints[0], dict):
            lats = [wp["lat"] for wp in waypoints]
            lons = [wp["lon"] for wp in waypoints]
            wp_tuples = [(wp["lat"], wp["lon"]) for wp in waypoints]
        else:
            lats = [wp[0] for wp in waypoints]
            lons = [wp[1] for wp in waypoints]
            wp_tuples = list(waypoints)

        openmeteo_task = fetch_openmeteo(lats, lons, session=session)

        nws_tasks = [fetch_nws_forecast(lat, lon, session=session) for lat, lon in wp_tuples]
        nws_alert_tasks = [fetch_nws_alerts(lat, lon, session=session) for lat, lon in wp_tuples]
        tomorrow_tasks = [fetch_tomorrow(lat, lon, session=session) for lat, lon in wp_tuples]

        cc_task = fetch_chain_controls(session=session)

        # Only fetch RWIS if not provided
        if rwis_stations is None:
            rwis_task = fetch_rwis_stations(session=session)
            results = await asyncio.gather(
                openmeteo_task,
                asyncio.gather(*nws_tasks),
                asyncio.gather(*nws_alert_tasks),
                asyncio.gather(*tomorrow_tasks),
                cc_task,
                rwis_task,
                return_exceptions=True,
            )
            rwis_stations = results[5] if not isinstance(results[5], Exception) else []
        else:
            results = await asyncio.gather(
                openmeteo_task,
                asyncio.gather(*nws_tasks),
                asyncio.gather(*nws_alert_tasks),
                asyncio.gather(*tomorrow_tasks),
                cc_task,
                return_exceptions=True,
            )

    openmeteo_results = results[0] if not isinstance(results[0], Exception) else [None] * len(waypoints)
    nws_results = results[1] if not isinstance(results[1], Exception) else [None] * len(waypoints)
    nws_alerts = results[2] if not isinstance(results[2], Exception) else [[] for _ in waypoints]
    tomorrow_results = results[3] if not isinstance(results[3], Exception) else [[] for _ in waypoints]
    chain_controls = results[4] if not isinstance(results[4], Exception) else []

    # Track which sources actually returned data
    sources_set = set()
    if not isinstance(results[0], Exception) and any(r is not None for r in openmeteo_results):
        sources_set.add("Open-Meteo")
    if not isinstance(results[1], Exception) and any(r is not None for r in nws_results):
        sources_set.add("NWS")
    if not isinstance(results[3], Exception) and any(r for r in tomorrow_results):
        sources_set.add("Tomorrow.io")
    if not isinstance(results[4], Exception) and chain_controls:
        sources_set.add("Caltrans CWWP2")
    if rwis_stations:
        sources_set.add("Caltrans CWWP2")

    sources = sorted(sources_set)

    return {
        "openmeteo": openmeteo_results,
        "nws": nws_results,
        "nws_alerts": nws_alerts,
        "tomorrow": tomorrow_results,
        "chain_controls": chain_controls,
        "rwis_stations": rwis_stations,
        "sources": sources,
    }
```

**Step 4: Run all tests to verify nothing broke**

Run: `venv/bin/pytest tests/ -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add app.py tests/test_app.py
git commit -m "refactor: fetch_raw_weather accepts pre-fetched RWIS stations"
```

---

### Task 4: Update `resolve_weather_for_etas` to use station-tagged waypoints

**Files:**
- Modify: `app.py:109-146`
- Test: `tests/test_app.py`

**Step 1: Write the failing test**

Add to `tests/test_app.py`:

```python
def test_resolve_weather_uses_station_tag():
    """When a waypoint has type='rwis' and a station ref, resolve should use it directly."""
    from app import resolve_weather_for_etas
    from datetime import datetime, timezone

    station = {
        "location": {"latitude": 38.0, "longitude": -122.0, "locationName": "Test Station"},
        "surfaceStatus": "Wet",
        "surfaceTemperature": {"value": 32},
        "airTemperature": {"value": 35},
        "visibility": {"value": 0.5},
        "windSpeed": {"value": 20},
        "precipitationType": "Rain",
    }

    waypoints = [
        {"lat": 38.0, "lon": -122.0, "type": "rwis", "station": station},
    ]

    raw = {
        "openmeteo": [None],
        "nws": [None],
        "nws_alerts": [[]],
        "tomorrow": [[]],
        "chain_controls": [],
        "rwis_stations": [station],
        "sources": [],
    }

    etas = [datetime(2026, 2, 21, 8, 0, tzinfo=timezone.utc)]
    weather_data, road_data, alerts_by_segment, cc, sources = resolve_weather_for_etas(raw, waypoints, etas)
    assert road_data[0] is not None
    assert road_data[0]["pavement_status"] == "Wet"
```

**Step 2: Run test to verify it fails**

Run: `venv/bin/pytest tests/test_app.py::test_resolve_weather_uses_station_tag -v`
Expected: FAIL (either KeyError on dict waypoint access, or station not matched)

**Step 3: Update `resolve_weather_for_etas`**

In `app.py`, modify `resolve_weather_for_etas` (lines 109-146):

```python
def resolve_weather_for_etas(raw, waypoints, etas):
    """Look up weather at specific ETAs from pre-fetched raw data."""
    openmeteo_results = raw["openmeteo"]
    nws_results = raw["nws"]
    nws_alerts = raw["nws_alerts"]
    tomorrow_results = raw["tomorrow"]
    chain_controls = raw["chain_controls"]
    rwis_stations = raw["rwis_stations"]
    sources = raw["sources"]

    weather_data = []
    road_data = []
    alerts_by_segment = []

    for i, (wp, eta) in enumerate(zip(waypoints, etas)):
        # Extract lat/lon from waypoint (support dict or tuple)
        if isinstance(wp, dict):
            wp_tuple = (wp["lat"], wp["lon"])
        else:
            wp_tuple = wp

        nws_parsed = None
        if nws_results[i]:
            nws_parsed = find_forecast_for_time(nws_results[i], eta)

        openmeteo_parsed = None
        if openmeteo_results and i < len(openmeteo_results) and openmeteo_results[i]:
            openmeteo_parsed = find_openmeteo_for_time(openmeteo_results[i], eta)

        tomorrow_parsed = None
        if tomorrow_results[i]:
            tomorrow_parsed = find_tomorrow_for_time(tomorrow_results[i], eta)

        merged = merge_weather(nws=nws_parsed, openmeteo=openmeteo_parsed, tomorrow=tomorrow_parsed)
        weather_data.append(merged)

        # RWIS: use station ref directly if tagged, else search
        if isinstance(wp, dict) and wp.get("type") == "rwis" and wp.get("station"):
            rwis_match = match_rwis_to_waypoint([wp["station"]], wp_tuple, radius_miles=50)
        else:
            rwis_match = match_rwis_to_waypoint(rwis_stations, wp_tuple)
        road_data.append(rwis_match)

        seg_alerts = nws_alerts[i] if i < len(nws_alerts) else []
        seg_alerts = [a for a in seg_alerts if alert_active_at(a, eta)]
        alerts_by_segment.append(seg_alerts)

    return weather_data, road_data, alerts_by_segment, chain_controls, sources
```

**Step 4: Run all tests**

Run: `venv/bin/pytest tests/ -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add app.py tests/test_app.py
git commit -m "feat: resolve_weather_for_etas supports station-tagged waypoints"
```

---

### Task 5: Wire up the pipeline in `do_work()`

**Files:**
- Modify: `app.py:215-254`
- Test: `tests/test_app.py`

**Step 1: Write the failing test**

Add to `tests/test_app.py`:

```python
def test_do_work_imports_build_station_aware_waypoints():
    """The app module should import build_station_aware_waypoints."""
    import app as app_module
    source = open(app_module.__file__).read()
    assert "build_station_aware_waypoints" in source, \
        "app.py should use build_station_aware_waypoints"
```

**Step 2: Run test to verify it fails**

Run: `venv/bin/pytest tests/test_app.py::test_do_work_imports_build_station_aware_waypoints -v`
Expected: FAIL

**Step 3: Update `do_work()` and imports**

In `app.py` line 8, update the import:

```python
from routing import fetch_route, decode_polyline, sample_waypoints, compute_etas, build_station_aware_waypoints
```

In `app.py`, replace `do_work()` (lines 215-254):

```python
    async def do_work():
        import aiohttp

        route = await fetch_route(origin, destination, departure.isoformat())
        points = decode_polyline(route["polyline"])

        # Fetch RWIS stations early for station-aware waypoint selection
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            rwis_stations = await fetch_rwis_stations(session=session)

        # Build station-aware waypoints
        waypoints = build_station_aware_waypoints(points, rwis_stations)

        # Fetch weather for the station-aware waypoints, passing pre-fetched RWIS
        raw_weather = await fetch_raw_weather(waypoints, rwis_stations=rwis_stations)

        # Selected departure data
        selected = build_slot_data(departure, waypoints, route, raw_weather)

        # Compute all slider slots
        now_local = datetime.now(tz=timezone.utc).astimezone(departure.tzinfo)
        slot_times = compute_slider_range(departure, now_local)
        slots = {}
        for slot_dep in slot_times:
            slots[slot_dep.isoformat()] = build_slot_data(slot_dep, waypoints, route, raw_weather)

        total_miles = round(route["total_distance_meters"] / 1609.344, 1)
        total_minutes = round(route["total_duration_seconds"] / 60)

        return {
            "route": {
                "summary": route["summary"],
                "total_distance_miles": total_miles,
                "total_duration_minutes": total_minutes,
                "departure": departure.isoformat(),
                "arrival": selected["arrival"],
                "polyline": route["polyline"],
            },
            "segments": selected["segments"],
            "alerts": selected["alerts"],
            "sources": raw_weather["sources"],
            "slots": slots,
            "slider_range": {
                "min": slot_times[0].isoformat(),
                "max": slot_times[-1].isoformat(),
                "step_hours": 1,
                "selected": departure.isoformat(),
            },
        }
```

**Step 4: Update `compute_etas` to handle dict waypoints**

In `routing.py`, update `compute_etas` (lines 72-93) to support both dict and tuple waypoints:

```python
def compute_etas(waypoints, total_duration_seconds, departure):
    """Compute ETA at each waypoint assuming constant speed along the route."""
    if len(waypoints) <= 1:
        return [departure]

    def _coords(wp):
        if isinstance(wp, dict):
            return wp["lat"], wp["lon"]
        return wp[0], wp[1]

    distances = [0.0]
    for i in range(1, len(waypoints)):
        lat1, lon1 = _coords(waypoints[i-1])
        lat2, lon2 = _coords(waypoints[i])
        d = haversine_miles(lat1, lon1, lat2, lon2)
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
```

**Step 5: Update `build_segments` in `assembler.py` to handle dict waypoints and add `data_source`/`station_name`**

In `assembler.py`, update `build_segments` (lines 171-237):

In the loop at line 177, add coordinate extraction and data_source/station_name to the segment dict:

```python
def build_segments(waypoints, etas, route_steps, weather_data, road_data, alerts_by_segment,
                   chain_controls=None):
    """Assemble the final segments list for the API response."""
    segments = []
    cumulative_miles = 0.0

    for i, (wp, eta) in enumerate(zip(waypoints, etas)):
        # Support both dict and tuple waypoints
        if isinstance(wp, dict):
            wp_lat, wp_lon = wp["lat"], wp["lon"]
            data_source = wp.get("type", "fill")
            station_obj = wp.get("station")
            station_name = None
            if station_obj:
                station_name = station_obj.get("location", {}).get("locationName")
        else:
            wp_lat, wp_lon = wp[0], wp[1]
            data_source = "fill"
            station_name = None

        if i > 0:
            if isinstance(waypoints[i-1], dict):
                prev_lat, prev_lon = waypoints[i-1]["lat"], waypoints[i-1]["lon"]
            else:
                prev_lat, prev_lon = waypoints[i-1][0], waypoints[i-1][1]
            cumulative_miles += haversine_miles(prev_lat, prev_lon, wp_lat, wp_lon)

        weather = weather_data[i] if i < len(weather_data) else {}
        road = road_data[i] if i < len(road_data) else None
        seg_alerts = alerts_by_segment[i] if i < len(alerts_by_segment) else []

        # Find matching turn instruction
        instruction = ""
        if route_steps:
            best_step = None
            best_dist = float("inf")
            for step in route_steps:
                sloc = step.get("start_location", {})
                slat = sloc.get("latitude") or sloc.get("lat", 0)
                slng = sloc.get("longitude") or sloc.get("lng", 0)
                d = haversine_miles(wp_lat, wp_lon, slat, slng)
                if d < best_dist:
                    best_dist = d
                    best_step = step
            if best_step:
                instruction = best_step.get("instruction", "")

        # Match chain controls to this segment's instruction
        cc_match = match_chain_control_to_instruction(chain_controls, instruction)

        # Build road_conditions for severity: merge RWIS data + chain control
        road_for_severity = dict(road) if road else {}
        if cc_match:
            road_for_severity["chain_control"] = cc_match

        severity_score, severity_label = compute_severity(
            weather, road_for_severity or None, seg_alerts
        )

        segment = {
            "index": i,
            "location": {
                "lat": round(wp_lat, 5),
                "lng": round(wp_lon, 5),
            },
            "mile_marker": round(cumulative_miles, 1),
            "eta": eta.isoformat(),
            "turn_instruction": instruction,
            "weather": weather,
            "road_conditions": {
                "chain_control": cc_match,
                "pavement_status": (road or {}).get("pavement_status"),
                "alerts": seg_alerts,
            },
            "severity_score": severity_score,
            "severity_label": severity_label,
            "data_source": data_source,
            "source_links": build_source_links(
                round(wp_lat, 5), round(wp_lon, 5), weather, road_for_severity
            ),
        }
        if station_name:
            segment["station_name"] = station_name

        segments.append(segment)

    return segments
```

**Step 4 (continued): Run all tests**

Run: `venv/bin/pytest tests/ -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add app.py routing.py assembler.py tests/test_app.py
git commit -m "feat: wire station-aware waypoints into pipeline"
```

---

### Task 6: Add `data_source` and `station_name` to frontend segment cards

**Files:**
- Modify: `templates/index.html` (segment card rendering in `buildPanel`)

**Step 1: Add station name badge to segment header**

In `templates/index.html`, in the `buildPanel` function, after the mile marker span (around line 934), add:

```javascript
      // Station badge (RWIS data source indicator)
      if (seg.station_name) {
        var stationSpan = document.createElement("span");
        stationSpan.className = "station-badge";
        stationSpan.textContent = seg.station_name + " RWIS";
        header.appendChild(stationSpan);
      }
```

**Step 2: Add CSS for station badge**

In the `<style>` section of `index.html`, add:

```css
.station-badge {
  background: #e8f5e9;
  color: #2e7d32;
  font-size: .7rem;
  padding: 1px 6px;
  border-radius: 8px;
  font-weight: 600;
  margin-left: auto;
}
```

**Step 3: Verify manually**

Run: `venv/bin/python3 app.py`
Open http://127.0.0.1:5001. Enter a mountain route (e.g. San Mateo to Tahoe). Segments near mountain passes should show station name badges.

**Step 4: Commit**

```bash
git add templates/index.html
git commit -m "feat: show RWIS station name badge on segment cards"
```

---

### Task 7: Run full test suite and manual E2E verification

**Step 1: Run all unit tests**

Run: `venv/bin/pytest tests/ -v`
Expected: ALL PASS

**Step 2: Manual E2E test**

Start the app: `venv/bin/python3 app.py`

Test routes:
1. **Mountain route** (San Mateo, CA → South Lake Tahoe, CA): Should show RWIS station waypoints on mountain passes with station name badges. Gap-fill waypoints in valley sections.
2. **Flat route** (San Francisco, CA → San Jose, CA): No RWIS stations expected. All segments should be gap-fill (identical to old behavior).
3. **Coastal route** (San Francisco, CA → Mendocino, CA): Mix of station and fill waypoints depending on RWIS coverage along CA-1/US-101.

Verify:
- Slider still works (instant slot switching)
- Map markers appear at waypoint locations
- Station segments show the green badge
- Fill segments look like they did before (no badge)
- Severity scoring still works correctly

**Step 3: Commit any fixes if needed**
