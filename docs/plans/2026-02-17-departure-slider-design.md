# Departure Time Slider Design

## Overview

Add a slider control that lets users explore different departure times and see how weather conditions change along the route. The slider spans from 2 days before to 2 days after the selected departure time (clamped to "now" on the low end), in 1-hour steps.

## Key Decisions

- **Weather only updates** — route/polyline stays the same when sliding; only ETAs and weather lookups change
- **1-hour step granularity** — matches hourly resolution of all 3 weather APIs
- **Slider sits below the datetime-local input** — appears after first route fetch
- **Single API call** — backend fetches weather data once, then computes all slots server-side
- **All slots returned upfront** — slider movement is instant on the frontend (no API calls)

## Backend Changes

### Refactor: Extract segment-building from weather data

Currently `fetch_all_weather()` does both fetching and time-lookup in one pass. Refactor into:

1. `fetch_all_weather_raw(waypoints)` — fetches raw forecast data from all 3 sources + road conditions (no ETA dependency)
2. `build_weather_for_etas(raw_data, waypoints, etas)` — given raw forecast arrays and a set of ETAs, does the time-lookup, merge, and severity scoring

### New: Multi-slot computation

After fetching route and raw weather data:

1. Compute slider range: `max(now, departure - 48h)` to `departure + 48h`
2. Generate hourly departure slots within that range
3. For each slot: `compute_etas()` → `build_weather_for_etas()` → `build_segments()`
4. Package into response

### Response shape

```json
{
  "route": { "...same as before..." },
  "segments": [ "...segments for selected departure (backward compat)..." ],
  "alerts": [ "...same..." ],
  "sources": ["..."],
  "slots": {
    "2026-02-15T08:00:00-08:00": {
      "segments": [...],
      "alerts": [...],
      "departure": "...",
      "arrival": "..."
    }
  },
  "slider_range": {
    "min": "2026-02-15T08:00:00-08:00",
    "max": "2026-02-19T08:00:00-08:00",
    "step_hours": 1,
    "selected": "2026-02-17T08:00:00-08:00"
  }
}
```

## Frontend Changes

### Slider control

- HTML `<input type="range">` below the departure input
- Hidden initially, shown after first successful route fetch
- Min/max labels show dates/times at each end
- Prominent label above shows currently selected time (e.g., "Tue Feb 17, 8:00 AM")
- Snaps to 1-hour steps

### On slide interaction

- Look up slot data from the pre-loaded `slots` object (instant)
- Re-render: segment cards, polyline colors, weather markers, info windows, summary bar
- Update departure/arrival times in route header

### Interaction with datetime-local input

- datetime-local stays as initial selector + "Get Route" trigger
- Slider appears after first fetch, centered on selected time
- Changing datetime-local + clicking "Get Route" re-fetches everything with new center

## Performance Considerations

- ~96 slots max (48h before + 48h after at 1-hour steps) × ~10 segments = ~960 segment objects
- Each segment is ~20 fields → estimated response ~300-500KB JSON (acceptable)
- All weather API calls unchanged (single fetch per source)
- Slider interaction is pure frontend (no network latency)
