# UX Improvements Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add external source links per segment, Google Places autocomplete on location inputs, and filter expired advisories by segment ETA.

**Architecture:** Three independent changes: (1) backend generates per-segment source URLs passed through the API, frontend renders them as small links; (2) Google Places Autocomplete widget attached to existing inputs; (3) backend extracts NWS alert `expires` field and filters alerts where `expires <= segment ETA`.

**Tech Stack:** Python/Flask backend, vanilla JS frontend, Google Maps JS API (Places library), NWS API.

---

### Task 1: Filter expired advisories — extract `expires` from NWS alerts

**Files:**
- Modify: `weather_nws.py:103-111`
- Test: `tests/test_weather_nws.py`

**Step 1: Write the failing test**

Add to `tests/test_weather_nws.py`:

```python
def test_fetch_nws_alerts_includes_expires_and_onset():
    """Alert dicts must include expires and onset fields from NWS properties."""
    from unittest.mock import AsyncMock, patch, MagicMock
    import asyncio

    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={
        "features": [{
            "properties": {
                "event": "Winter Storm Warning",
                "headline": "Winter Storm Warning issued February 21",
                "severity": "Severe",
                "description": "Heavy snow expected.",
                "expires": "2026-02-21T18:00:00-08:00",
                "onset": "2026-02-21T06:00:00-08:00",
            }
        }]
    })
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_response)

    from weather_nws import fetch_nws_alerts
    alerts = asyncio.run(fetch_nws_alerts(37.5, -122.1, session=mock_session))

    assert len(alerts) == 1
    assert alerts[0]["expires"] == "2026-02-21T18:00:00-08:00"
    assert alerts[0]["onset"] == "2026-02-21T06:00:00-08:00"


def test_fetch_nws_alerts_missing_expires_returns_none():
    """When NWS alert has no expires field, it should be None."""
    from unittest.mock import AsyncMock, MagicMock
    import asyncio

    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={
        "features": [{
            "properties": {
                "event": "Flood Watch",
                "headline": "Flood Watch",
                "severity": "Moderate",
                "description": "Possible flooding.",
            }
        }]
    })
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_response)

    from weather_nws import fetch_nws_alerts
    alerts = asyncio.run(fetch_nws_alerts(37.5, -122.1, session=mock_session))

    assert len(alerts) == 1
    assert alerts[0]["expires"] is None
    assert alerts[0]["onset"] is None
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/deepak/AI/drive-conditions && python -m pytest tests/test_weather_nws.py::test_fetch_nws_alerts_includes_expires_and_onset tests/test_weather_nws.py::test_fetch_nws_alerts_missing_expires_returns_none -v`
Expected: FAIL — `expires` key not present in alert dict

**Step 3: Write minimal implementation**

In `weather_nws.py`, change lines 106-111 from:

```python
            alerts.append({
                "type": props.get("event", ""),
                "headline": props.get("headline", ""),
                "severity": props.get("severity", "").lower(),
                "description": props.get("description", ""),
            })
```

To:

```python
            alerts.append({
                "type": props.get("event", ""),
                "headline": props.get("headline", ""),
                "severity": props.get("severity", "").lower(),
                "description": props.get("description", ""),
                "expires": props.get("expires"),
                "onset": props.get("onset"),
            })
```

**Step 4: Run tests to verify they pass**

Run: `cd /Users/deepak/AI/drive-conditions && python -m pytest tests/test_weather_nws.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add weather_nws.py tests/test_weather_nws.py
git commit -m "feat: extract expires/onset from NWS alerts"
```

---

### Task 2: Filter expired advisories — filter in app.py

**Files:**
- Modify: `app.py:87-88` (alerts_by_segment assignment)
- Modify: `app.py:129-141` (all_alerts aggregation)
- Test: `tests/test_app.py` (new file)

**Step 1: Write the failing test**

Create `tests/test_app.py`:

```python
from datetime import datetime, timezone, timedelta


def test_alert_active_at_no_expires():
    """Alert with no expires field is always considered active."""
    from app import alert_active_at
    alert = {"headline": "Test", "severity": "moderate"}
    eta = datetime(2026, 2, 21, 12, 0, tzinfo=timezone.utc)
    assert alert_active_at(alert, eta) is True


def test_alert_active_at_expires_after_eta():
    """Alert expiring after ETA is active."""
    from app import alert_active_at
    alert = {"headline": "Test", "expires": "2026-02-21T18:00:00-08:00"}
    eta = datetime(2026, 2, 21, 16, 0, tzinfo=timezone(timedelta(hours=-8)))
    assert alert_active_at(alert, eta) is True


def test_alert_active_at_expires_before_eta():
    """Alert expiring before ETA is NOT active."""
    from app import alert_active_at
    alert = {"headline": "Test", "expires": "2026-02-21T08:00:00-08:00"}
    eta = datetime(2026, 2, 21, 10, 0, tzinfo=timezone(timedelta(hours=-8)))
    assert alert_active_at(alert, eta) is False


def test_alert_active_at_expires_equal_to_eta():
    """Alert expiring exactly at ETA is NOT active (expires is not strictly greater)."""
    from app import alert_active_at
    alert = {"headline": "Test", "expires": "2026-02-21T10:00:00-08:00"}
    eta = datetime(2026, 2, 21, 10, 0, tzinfo=timezone(timedelta(hours=-8)))
    assert alert_active_at(alert, eta) is False
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/deepak/AI/drive-conditions && python -m pytest tests/test_app.py -v`
Expected: FAIL — `cannot import name 'alert_active_at' from 'app'`

**Step 3: Write minimal implementation**

Add the `alert_active_at` function to `app.py` (after the imports, before `fetch_all_weather`):

```python
def alert_active_at(alert, eta):
    """Return True if alert is still active at the given ETA."""
    expires_str = alert.get("expires")
    if not expires_str:
        return True
    expires = datetime.fromisoformat(expires_str)
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires > eta
```

Then update `app.py` line 87-88 to filter alerts per segment using ETAs:

Change:
```python
        seg_alerts = nws_alerts[i] if i < len(nws_alerts) else []
        alerts_by_segment.append(seg_alerts)
```

To:
```python
        seg_alerts = nws_alerts[i] if i < len(nws_alerts) else []
        seg_alerts = [a for a in seg_alerts if alert_active_at(a, eta)]
        alerts_by_segment.append(seg_alerts)
```

No changes needed to the `all_alerts` aggregation at lines 129-141 — since `alerts_by_segment` is already filtered, the aggregation loop only sees active alerts.

**Step 4: Run tests to verify they pass**

Run: `cd /Users/deepak/AI/drive-conditions && python -m pytest tests/test_app.py tests/test_weather_nws.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add app.py tests/test_app.py
git commit -m "feat: filter advisories that expire before segment ETA"
```

---

### Task 3: Source links — generate per-segment source URLs in assembler

**Files:**
- Modify: `assembler.py:158-221` (`build_segments` function)
- Test: `tests/test_assembler.py`

**Step 1: Write the failing test**

Add to `tests/test_assembler.py`:

```python
from assembler import build_segments


def test_build_segments_includes_source_links():
    """Each segment should have source_links with NWS and Open-Meteo at minimum."""
    waypoints = [(37.5, -122.1), (38.0, -122.5)]
    from datetime import datetime, timezone
    etas = [
        datetime(2026, 2, 21, 6, 0, tzinfo=timezone.utc),
        datetime(2026, 2, 21, 7, 0, tzinfo=timezone.utc),
    ]
    steps = []
    weather_data = [
        {"temperature_f": 50, "wind_speed_mph": 10, "wind_gusts_mph": 15,
         "precipitation_mm_hr": 0, "visibility_miles": 10, "road_risk_score": 2},
        {"temperature_f": 48, "wind_speed_mph": 12, "wind_gusts_mph": 18,
         "precipitation_mm_hr": 0, "visibility_miles": 8},
    ]
    road_data = [None, None]
    alerts_by_segment = [[], []]

    segments = build_segments(waypoints, etas, steps, weather_data, road_data, alerts_by_segment)

    assert "source_links" in segments[0]
    links = segments[0]["source_links"]
    assert "nws" in links
    assert "37.5" in links["nws"]
    assert "-122.1" in links["nws"]
    assert "open_meteo" in links
    assert "caltrans" not in links  # no chain control or pavement data


def test_build_segments_source_links_includes_tomorrow_when_risk_present():
    """Tomorrow.io link included when road_risk_score is present."""
    waypoints = [(37.5, -122.1)]
    from datetime import datetime, timezone
    etas = [datetime(2026, 2, 21, 6, 0, tzinfo=timezone.utc)]
    weather_data = [
        {"temperature_f": 50, "wind_speed_mph": 10, "wind_gusts_mph": 15,
         "precipitation_mm_hr": 0, "visibility_miles": 10,
         "road_risk_score": 3, "road_risk_label": "Moderate"},
    ]
    road_data = [None]
    alerts_by_segment = [[]]

    segments = build_segments(waypoints, etas, [], weather_data, road_data, alerts_by_segment)
    assert "tomorrow_io" in segments[0]["source_links"]


def test_build_segments_source_links_includes_caltrans_when_chain_control():
    """Caltrans link included when chain_control data exists."""
    waypoints = [(37.5, -122.1)]
    from datetime import datetime, timezone
    etas = [datetime(2026, 2, 21, 6, 0, tzinfo=timezone.utc)]
    weather_data = [
        {"temperature_f": 50, "wind_speed_mph": 10, "wind_gusts_mph": 15,
         "precipitation_mm_hr": 0, "visibility_miles": 10},
    ]
    road_data = [None]
    alerts_by_segment = [[]]
    chain_controls = [{"highway": "80", "level": "R2", "district": 3,
                       "description": "Chains required"}]

    segments = build_segments(
        waypoints, etas,
        [{"instruction": "Continue on I-80", "start_location": {"lat": 37.5, "lng": -122.1}}],
        weather_data, road_data, alerts_by_segment,
        chain_controls=chain_controls,
    )
    assert "caltrans" in segments[0]["source_links"]
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/deepak/AI/drive-conditions && python -m pytest tests/test_assembler.py::test_build_segments_includes_source_links tests/test_assembler.py::test_build_segments_source_links_includes_tomorrow_when_risk_present tests/test_assembler.py::test_build_segments_source_links_includes_caltrans_when_chain_control -v`
Expected: FAIL — `source_links` not in segment dict

**Step 3: Write minimal implementation**

In `assembler.py`, add a helper function before `build_segments`:

```python
def build_source_links(lat, lon, weather, road_conditions):
    """Build dict of external source URLs for a segment."""
    links = {
        "nws": f"https://forecast.weather.gov/MapClick.php?lat={lat}&lon={lon}",
        "open_meteo": f"https://open-meteo.com/en/docs#latitude={lat}&longitude={lon}",
    }
    if weather.get("road_risk_score") is not None:
        links["tomorrow_io"] = "https://www.tomorrow.io/weather/"
    if road_conditions and (road_conditions.get("chain_control") or road_conditions.get("pavement_status")):
        links["caltrans"] = "https://roads.dot.ca.gov/"
    return links
```

Then in `build_segments`, add `source_links` to the segment dict (after `severity_label`, before the closing `}`):

```python
            "source_links": build_source_links(
                round(wp[0], 5), round(wp[1], 5), weather, road_for_severity
            ),
```

**Step 4: Run tests to verify they pass**

Run: `cd /Users/deepak/AI/drive-conditions && python -m pytest tests/test_assembler.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add assembler.py tests/test_assembler.py
git commit -m "feat: generate per-segment source links in assembler"
```

---

### Task 4: Source links — render in frontend segment cards

**Files:**
- Modify: `templates/index.html:866-898` (segment card rendering, after alerts/chain control, before click handler)

**Step 1: Add CSS for source links row**

Add after the `.segment-alert.severe` rule (after line 303):

```css
.segment-sources {
  margin-top: 8px;
  padding-top: 6px;
  border-top: 1px solid #f1f5f9;
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.segment-sources a {
  font-size: 11px;
  color: #64748b;
  text-decoration: none;
  transition: color 0.15s;
}

.segment-sources a:hover {
  color: #3b82f6;
  text-decoration: underline;
}
```

**Step 2: Add source links rendering in buildPanel**

In the `buildPanel` function, after the chain control block (after line 884, before the click handler at line 887), add:

```javascript
      // Source links
      var sourceLinks = seg.source_links || {};
      var linkKeys = Object.keys(sourceLinks);
      if (linkKeys.length > 0) {
        var srcDiv = document.createElement("div");
        srcDiv.className = "segment-sources";
        var sourceLabels = {
          nws: "NWS Forecast",
          open_meteo: "Open-Meteo",
          tomorrow_io: "Tomorrow.io",
          caltrans: "Caltrans QuickMap"
        };
        linkKeys.forEach(function(key) {
          var a = document.createElement("a");
          a.href = sourceLinks[key];
          a.target = "_blank";
          a.rel = "noopener noreferrer";
          a.textContent = sourceLabels[key] || key;
          srcDiv.appendChild(a);
        });
        card.appendChild(srcDiv);
      }
```

**Step 3: Manual test**

Run: `cd /Users/deepak/AI/drive-conditions && python app.py`
Open browser, fetch a route, verify each segment card shows small source links at the bottom.

**Step 4: Commit**

```bash
git add templates/index.html
git commit -m "feat: render per-segment source links in frontend"
```

---

### Task 5: Google Places Autocomplete on location inputs

**Files:**
- Modify: `templates/index.html:1102-1107` (init section — add Places library loading and Autocomplete setup)

**Step 1: Update Maps API loader to include Places library**

In `templates/index.html`, the `initMap` is called after loading `maps` and `geometry` libraries (lines 1103-1107). Update the init block to also load `places` and attach Autocomplete:

Replace lines 1102-1107:
```javascript
  /* ── Init ──────────────────────────────────────────── */
  google.maps.importLibrary("maps").then(function() {
    google.maps.importLibrary("geometry").then(function() {
      initMap();
    });
  });
```

With:
```javascript
  /* ── Init ──────────────────────────────────────────── */
  Promise.all([
    google.maps.importLibrary("maps"),
    google.maps.importLibrary("geometry"),
    google.maps.importLibrary("places"),
  ]).then(function() {
    initMap();

    var autocompleteOptions = {
      componentRestrictions: { country: "us" },
      fields: ["formatted_address"],
    };

    new google.maps.places.Autocomplete(originEl, autocompleteOptions);
    new google.maps.places.Autocomplete(destEl, autocompleteOptions);
  });
```

**Step 2: Widen inputs to accommodate autocomplete dropdown**

The `.pac-container` (Google's autocomplete dropdown) is styled by Google and overlays the page. No CSS changes needed for the dropdown itself. However, ensure the input z-index doesn't conflict — the header already has `z-index: 10` which is fine.

**Step 3: Manual test**

Run: `cd /Users/deepak/AI/drive-conditions && python app.py`
Open browser, start typing in origin/destination fields, verify autocomplete dropdown appears with US address suggestions.

**Step 4: Commit**

```bash
git add templates/index.html
git commit -m "feat: add Google Places autocomplete to location inputs"
```

---

### Task 6: Run full test suite and verify

**Step 1: Run all tests**

Run: `cd /Users/deepak/AI/drive-conditions && python -m pytest tests/ -v`
Expected: ALL PASS

**Step 2: Manual smoke test**

Run: `cd /Users/deepak/AI/drive-conditions && python app.py`
Verify all three features:
1. Autocomplete dropdown appears when typing in origin/destination
2. Each segment card shows source links at bottom
3. (If NWS alerts are active) expired alerts do not appear for future segments

**Step 3: Final commit if any fixups needed**

---

### Summary of all file changes

| File | Change |
|------|--------|
| `weather_nws.py:106-111` | Add `expires` and `onset` to alert dict |
| `app.py:14-20` | Add `alert_active_at()` function |
| `app.py:87-88` | Filter `seg_alerts` using `alert_active_at` |
| `assembler.py:157` | Add `build_source_links()` function |
| `assembler.py:202-219` | Add `source_links` to segment dict |
| `templates/index.html` | CSS for `.segment-sources`, source links rendering in `buildPanel`, Places Autocomplete init |
| `tests/test_weather_nws.py` | Tests for `expires`/`onset` extraction |
| `tests/test_app.py` (new) | Tests for `alert_active_at` |
| `tests/test_assembler.py` | Tests for `source_links` in segments |
