# UX Improvements Design: Source Links, Autocomplete, Advisory Filtering

Date: 2026-02-17

## Overview

Three improvements to the drive conditions app:
1. External source links per segment
2. Google Places autocomplete on location inputs
3. Filter advisories that expire before the driver arrives

## 1. External Source Links Per Segment

### Goal
Each segment card shows clickable links to the original data sources so users can drill into the raw forecast/road data.

### Backend Changes (assembler.py)
Add a `source_links` dict to each segment object. Only include sources that contributed data to that segment:

```python
"source_links": {
    "nws": "https://forecast.weather.gov/MapClick.php?lat={lat}&lon={lon}",
    "open_meteo": "https://open-meteo.com/en/docs#latitude={lat}&longitude={lon}",
    "tomorrow_io": "https://www.tomorrow.io/weather/",
    "caltrans": "https://roads.dot.ca.gov/"  # only when chain_control or rwis data present
}
```

Rules for inclusion:
- NWS: always included (forecasts always fetched)
- Open-Meteo: always included (always fetched)
- Tomorrow.io: included when road risk data is present (requires API key)
- Caltrans: included only when `chain_control` or `pavement_status` data exists for the segment

### Frontend Changes (index.html)
Add a small row at the bottom of each segment card with source icons/labels. Each is an external link (`target="_blank"`). Style as subtle, small text — not prominent but discoverable.

## 2. Google Places Autocomplete

### Goal
Origin and destination inputs show a dropdown of address suggestions as the user types, matching Google Maps behavior.

### Implementation
Use `google.maps.places.Autocomplete` widget attached to both `#origin` and `#destination` inputs.

Configuration:
- `componentRestrictions: {country: 'us'}` — bias to US addresses
- `fields: ['formatted_address']` — only fetch what we need
- Listen for `place_changed` event to update input value

### Google Maps API Loading
The Maps JS API is already loaded. Need to add the `places` library to the loader:
- Current: `libraries=marker` in the API script tag or loader
- Updated: `libraries=marker,places`

### No backend changes needed.

## 3. Filter Expired Advisories by Segment ETA

### Goal
Don't show advisory warnings that will have expired by the time the driver reaches that segment.

### Backend Changes

**weather_nws.py** — Extract timing fields from NWS alert properties:
```python
alerts.append({
    "type": props.get("event", ""),
    "headline": props.get("headline", ""),
    "severity": props.get("severity", "").lower(),
    "description": props.get("description", ""),
    "expires": props.get("expires"),   # ISO 8601 string or None
    "onset": props.get("onset"),       # ISO 8601 string or None
})
```

**app.py** — During alert aggregation per segment, filter out alerts where `expires` is known and is before the segment's ETA:
```python
from datetime import datetime, timezone

def alert_active_at(alert, eta):
    """Return True if alert is still active at the given ETA."""
    expires_str = alert.get("expires")
    if not expires_str:
        return True  # no expiry info, assume active
    expires = datetime.fromisoformat(expires_str)
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires > eta
```

Apply this filter when assigning alerts to segments, and when building the top-level `alerts` list (only include an alert if it's active for at least one of its affected segments).

### Frontend: No changes needed — filtered alerts simply won't appear in the response.
