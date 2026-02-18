# Trip Realism Design

**Goal:** Make trip forecasts more realistic and safety-aware by adding sunset/light level tracking, speed slowdown factors, and rest stops along the route.

## Feature 1: Sunset & Light Levels

**Data source:** Open-Meteo daily `sunrise`/`sunset` variables added to the existing API call. Zero extra HTTP requests.

**Light categories** at each segment based on ETA vs sunrise/sunset at that waypoint:
- **Day** — ETA is > 30 min after sunrise and > 30 min before sunset.
- **Twilight** — ETA is within 30 min of sunrise or sunset (civil twilight).
- **Night** — ETA is > 30 min after sunset or > 30 min before sunrise.

**Severity impact:** Light conditions alone don't increase severity. Combinations:
- Twilight + any weather hazard (rain/fog/wind): severity +1.
- Night + any weather hazard: severity +1.
- Night + heavy rain or dense fog: severity +2.

**Frontend:** Each segment card gets a light-level icon (sun/moon) and label. Dangerous combinations show a warning line: "Low visibility driving after sunset — consider adjusting departure."

**API response:** Each segment gains `"light_level": "day"|"twilight"|"night"`, `"sunrise": "HH:MM"`, `"sunset": "HH:MM"`.

## Feature 2: Speed Slowdown Factor

**Base speed slider:** Range 0.5x to 1.0x (step 0.05), default 1.0x. Represents the driver's general caution level.

**Weather-based slowdown factors** (automatic, per segment):

| Condition | Factor |
|---|---|
| Light rain | 0.90x |
| Moderate rain | 0.80x |
| Heavy rain | 0.70x |
| Snow (any) | 0.65x |
| Dense fog (vis < 1 mi) | 0.70x |
| Patchy fog (vis 1-5 mi) | 0.85x |
| Strong wind (> 35 mph) | 0.85x |
| Night + rain | additional 0.90x |

**Math:** `effective_speed = base_slider * weather_factor`. Factors compound (e.g., heavy rain at night: `base * 0.70 * 0.90`).

**Total trip duration** updates in the header and summary to reflect adjusted time.

**Frontend:** Speed slider in collapsible "Trip Settings" bar below the departure slider. Label shows current value: "Speed: 0.85x".

## Feature 3: Rest Stops

**Timing:** After every N minutes of driving (default 60 min), insert a rest stop of M minutes (default 20 min). Driving clock resets after each rest.

**Location:** Google Places Nearby Search API to find nearest rest area or gas station within ~5 mi of the computed polyline point. Fallback to raw polyline point if no result.

**Rest stop caching:** Locations computed once per route (based on distance along route). Only arrival/departure ETAs change with the departure slider. Avoids re-calling Places API per slider slot.

**API response:** Rest stop pseudo-segments:
```json
{
  "type": "rest_stop",
  "location": {"lat": 0, "lng": 0},
  "place_name": "Chevron Gas Station",
  "rest_duration_minutes": 20,
  "eta_arrive": "...",
  "eta_depart": "...",
  "mile_marker": 85.2
}
```

**Frontend panel:** Visually distinct cards — light blue background, rest/coffee icon, place name, "20 min stop" label. No weather data.

**Map markers:** Distinct icon (blue circle with "R") to differentiate from weather waypoints.

**UI controls** in "Trip Settings" bar:
- "Drive interval" — number input, 30-180 min, default 60, step 15.
- "Rest duration" — number input, 5-60 min, default 20, step 5.
- Toggle to enable/disable rest stops (default: off).

**Edge cases:**
- Trip shorter than drive interval: no rest stops.
- Places search returns nothing: use polyline point, label "Rest stop (mile X)".

## Pipeline Order

1. Fetch route, decode polyline, fetch RWIS, build station-aware waypoints.
2. Compute initial ETAs with `total_duration / base_speed_factor`.
3. Fetch raw weather for all waypoints (full hourly arrays — one API call per source).
4. **First resolve:** look up weather at initial ETAs, apply weather-based slowdowns, compute adjusted ETAs.
5. Determine rest stop positions from adjusted cumulative driving time.
6. Fetch rest stop places from Google Places API.
7. Insert rest stops into segment list, shift subsequent ETAs by rest durations — final ETAs.
8. **Second resolve:** `resolve_weather_for_etas()` again with post-rest-stop ETAs. Cheap — re-indexes into already-fetched raw hourly data, no new API calls.
9. Re-apply weather-based slowdowns with updated weather (minor ETA tweaks, single pass).
10. Compute light levels (sunrise/sunset) for final ETAs at each segment.
11. Apply light-level severity adjustments.
12. Build final response.

## Slider Interaction

All features are baked into slot precomputation. Different departure → different ETAs → different weather → different slowdowns → different rest stop timing → different light conditions. Rest stop *locations* (distance-based) are cached across slots; only their ETAs change.

## Settings Defaults

Speed 1.0x, rest stops off. First-time users see the same behavior as today. Settings persist in the browser session via controls, not saved across page loads.

## UI Layout

Collapsible "Trip Settings" bar below the existing departure slider:
- Speed slider (0.5x - 1.0x)
- Rest stops toggle + interval/duration inputs (shown when toggle is on)
