# Station-Aware Waypoints Design

**Goal:** Replace fixed 15-mile interval waypoint sampling with RWIS station-aware placement that maximizes real ground-truth road condition data along the route.

**Scope:** California only. Caltrans RWIS stations as the primary station source. NWS observation stations deferred to a future iteration.

## Decisions

- **Approach:** RWIS-first snapping. Place waypoints at RWIS station locations along the route, fill gaps with distance-based sampling.
- **Snap radius:** 15 miles from route polyline (matches existing `RWIS_MATCH_RADIUS_MILES`).
- **Gap threshold:** 30 miles. Any stretch longer than 30 miles without an RWIS station gets 15-mile interval fill waypoints.
- **Minimum station spacing:** 5 miles. Skip RWIS stations that are < 5 miles from an already-selected station to prevent clustering.

## Waypoint Selection Algorithm

New `build_station_aware_waypoints()` function replaces the current `sample_waypoints()` call:

**Inputs:** decoded polyline points, list of RWIS stations (already fetched).

**Steps:**
1. For each RWIS station, find the closest point on the route polyline. If distance <= 15 miles, mark it as "on-route" and record its position along the route (cumulative miles from origin).
2. Sort on-route stations by along-route position.
3. Deduplicate: skip stations < 5 miles from the previously selected station.
4. Always include origin (mile 0) and destination (last mile) as fill waypoints.
5. Walk from origin to destination. Between each pair of adjacent waypoints (station or origin/destination), if the gap > 30 miles, insert fill waypoints at 15-mile intervals.
6. Each waypoint carries a type tag: `"rwis"` (with station reference) or `"fill"`.

"Distance along route" is measured by walking the polyline with haversine, not straight-line.

## Data Fetching Changes

**Current flow:** fetch route → sample waypoints at 15mi → fetch weather + RWIS in parallel → match RWIS to waypoints after the fact.

**New flow:**
1. Fetch route → decode polyline.
2. Fetch RWIS stations (moves earlier — now a prerequisite for waypoint selection).
3. `build_station_aware_waypoints(polyline_points, rwis_stations)` → station-aware waypoint list.
4. Fetch weather (NWS, Open-Meteo, Tomorrow.io) for the final waypoint list in parallel.
5. Chain controls remain fetched in parallel with weather (matched by highway name, not location).

`fetch_raw_weather()` receives already-fetched RWIS stations as a parameter instead of fetching them internally.

For station-tagged waypoints, the RWIS match in `resolve_weather_for_etas()` is trivial — the station reference is already attached. Fill waypoints still do nearest-station search (likely returns None).

## Segment Display

Each segment in the API response gains:
- `data_source`: `"rwis"` or `"model"` — indicates whether the waypoint is at an RWIS station or a gap-fill point.
- `station_name`: e.g. "Echo Pass" — present only when `data_source` is `"rwis"`.

Frontend: add a small label showing station name on RWIS segments. Model segments look like today's segments (no change).

Map markers: no change to placement logic. Some routes will have clusters near mountain passes rather than even spacing.

## Edge Cases

- **No RWIS stations near route:** Pure gap-fill at 15-mile intervals. Identical to today.
- **Dense RWIS stations:** 5-mile minimum spacing cap prevents excessive waypoints.
- **RWIS API down:** `fetch_rwis_stations()` returns `[]`. Falls back to gap-fill. No degradation.
- **Station far from route but within 15mi:** Accepted. Gridded weather forecasts vary smoothly over that distance.
- **Slider interaction:** No change. Station-aware waypoints computed once per route. Departure slider resolves weather at different ETAs for the same waypoint list.
