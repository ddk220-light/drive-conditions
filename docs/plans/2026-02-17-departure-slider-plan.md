# Departure Time Slider Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a departure time slider that lets users explore weather conditions at different departure times (2 days before to 2 days after, 1-hour steps) without re-fetching data.

**Architecture:** Backend fetches weather data once, computes all departure time slots server-side, returns them all in one response. Frontend displays a range slider and swaps displayed data instantly on slide.

**Tech Stack:** Python/Flask backend, vanilla JS frontend, existing weather APIs (NWS, Open-Meteo, Tomorrow.io)

---

### Task 1: Refactor `fetch_all_weather` to separate raw fetching from time lookup

Currently `fetch_all_weather()` in `app.py` does two things: (1) fetches raw data from APIs, and (2) looks up weather for specific ETAs. We need to split these so we can reuse the raw data across multiple departure slots.

**Files:**
- Modify: `app.py:30-104`
- Test: `tests/test_app.py`

**Step 1: Write the failing test**

Add to `tests/test_app.py`:

```python
def test_fetch_raw_weather_returns_raw_data(monkeypatch):
    """fetch_raw_weather should return raw API results without time lookups."""
    import app as app_module

    # Verify the function exists and is callable
    assert hasattr(app_module, 'fetch_raw_weather'), "fetch_raw_weather not defined"
    assert callable(app_module.fetch_raw_weather)
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/deepak/AI/drive-conditions && python -m pytest tests/test_app.py::test_fetch_raw_weather_returns_raw_data -v`
Expected: FAIL with `AssertionError: fetch_raw_weather not defined`

**Step 3: Implement the refactor**

In `app.py`, split `fetch_all_weather` into two functions:

1. `fetch_raw_weather(waypoints)` — fetches raw data from all sources, returns a dict:
   ```python
   async def fetch_raw_weather(waypoints):
       """Fetch raw weather data from all sources (no ETA lookup)."""
       # Same aiohttp session and gather logic as current fetch_all_weather
       # Returns:
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

2. `resolve_weather_for_etas(raw, waypoints, etas)` — given raw data and ETAs, does time lookup + merge:
   ```python
   def resolve_weather_for_etas(raw, waypoints, etas):
       """Look up weather at specific ETAs from pre-fetched raw data."""
       # Contains the per-waypoint loop from current fetch_all_weather (lines 80-101)
       # Returns: weather_data, road_data, alerts_by_segment, chain_controls, sources
       # (same shape as current fetch_all_weather return)
   ```

Keep `fetch_all_weather` as a thin wrapper that calls both (for backward compat with tests):
```python
async def fetch_all_weather(waypoints, etas):
    raw = await fetch_raw_weather(waypoints)
    return resolve_weather_for_etas(raw, waypoints, etas)
```

**Step 4: Run all existing tests to verify no regression**

Run: `cd /Users/deepak/AI/drive-conditions && python -m pytest tests/ -v`
Expected: All tests pass (existing behavior unchanged)

**Step 5: Run the new test**

Run: `cd /Users/deepak/AI/drive-conditions && python -m pytest tests/test_app.py::test_fetch_raw_weather_returns_raw_data -v`
Expected: PASS

**Step 6: Commit**

```bash
git add app.py tests/test_app.py
git commit -m "refactor: split fetch_all_weather into raw fetch + ETA resolution"
```

---

### Task 2: Add `compute_slider_range` utility function

**Files:**
- Modify: `app.py` (add new function)
- Test: `tests/test_app.py`

**Step 1: Write the failing test**

Add to `tests/test_app.py`:

```python
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

def test_compute_slider_range_basic():
    """Slider range spans 2 days before to 2 days after departure, 1-hour steps."""
    from app import compute_slider_range
    pac = ZoneInfo("America/Los_Angeles")
    departure = datetime(2026, 2, 20, 8, 0, tzinfo=pac)
    now = datetime(2026, 2, 18, 10, 0, tzinfo=pac)

    slots = compute_slider_range(departure, now)

    # Should start at max(now rounded up to hour, departure - 48h)
    # departure - 48h = Feb 18 08:00, now = Feb 18 10:00 → start = Feb 18 10:00 (ceiled to hour)
    assert slots[0] == datetime(2026, 2, 18, 10, 0, tzinfo=pac)
    # Should end at departure + 48h = Feb 22 08:00
    assert slots[-1] == datetime(2026, 2, 22, 8, 0, tzinfo=pac)
    # All 1-hour steps
    for i in range(1, len(slots)):
        assert slots[i] - slots[i-1] == timedelta(hours=1)


def test_compute_slider_range_clamps_to_now():
    """If departure - 48h is in the past, start from now."""
    from app import compute_slider_range
    pac = ZoneInfo("America/Los_Angeles")
    departure = datetime(2026, 2, 18, 8, 0, tzinfo=pac)
    now = datetime(2026, 2, 17, 14, 30, tzinfo=pac)

    slots = compute_slider_range(departure, now)

    # departure - 48h = Feb 16 08:00, but now is Feb 17 14:30 → clamp to Feb 17 15:00 (ceil)
    assert slots[0] == datetime(2026, 2, 17, 15, 0, tzinfo=pac)
    assert slots[-1] == datetime(2026, 2, 20, 8, 0, tzinfo=pac)
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/deepak/AI/drive-conditions && python -m pytest tests/test_app.py::test_compute_slider_range_basic tests/test_app.py::test_compute_slider_range_clamps_to_now -v`
Expected: FAIL — `ImportError: cannot import name 'compute_slider_range'`

**Step 3: Implement**

Add to `app.py`:

```python
def compute_slider_range(departure, now):
    """Compute hourly departure slots from max(now, departure-48h) to departure+48h."""
    range_start = max(now, departure - timedelta(hours=48))
    # Ceil to next hour
    if range_start.minute > 0 or range_start.second > 0:
        range_start = range_start.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    else:
        range_start = range_start.replace(minute=0, second=0, microsecond=0)

    range_end = departure + timedelta(hours=48)
    range_end = range_end.replace(minute=0, second=0, microsecond=0)

    slots = []
    current = range_start
    while current <= range_end:
        slots.append(current)
        current += timedelta(hours=1)
    return slots
```

**Step 4: Run tests**

Run: `cd /Users/deepak/AI/drive-conditions && python -m pytest tests/test_app.py -v`
Expected: All pass

**Step 5: Commit**

```bash
git add app.py tests/test_app.py
git commit -m "feat: add compute_slider_range for departure time slider"
```

---

### Task 3: Add `build_slot_data` function to assemble segments for one departure slot

This is the function that, given raw weather data and a departure time, produces the full segments + alerts for that slot.

**Files:**
- Modify: `app.py`
- Test: `tests/test_app.py`

**Step 1: Write the failing test**

```python
def test_build_slot_data_returns_segments_and_alerts():
    """build_slot_data should return dict with segments, alerts, departure, arrival."""
    from app import build_slot_data
    assert callable(build_slot_data)
```

**Step 2: Run test to verify failure**

Run: `cd /Users/deepak/AI/drive-conditions && python -m pytest tests/test_app.py::test_build_slot_data_returns_segments_and_alerts -v`
Expected: FAIL

**Step 3: Implement**

Add to `app.py`:

```python
def build_slot_data(slot_departure, waypoints, route, raw_weather):
    """Build segments + alerts for a single departure time using pre-fetched weather."""
    etas = compute_etas(waypoints, route["total_duration_seconds"], slot_departure)
    weather_data, road_data, alerts_by_segment, chain_controls, sources = resolve_weather_for_etas(
        raw_weather, waypoints, etas
    )
    segments = build_segments(
        waypoints, etas, route["steps"],
        weather_data, road_data, alerts_by_segment,
        chain_controls=chain_controls,
    )

    # Deduplicate alerts
    all_alerts = []
    seen = set()
    for i, seg_alerts in enumerate(alerts_by_segment):
        for alert in seg_alerts:
            key = alert.get("headline", "")
            if key not in seen:
                seen.add(key)
                all_alerts.append({**alert, "affected_segments": [i]})
            else:
                for a in all_alerts:
                    if a.get("headline") == key:
                        a["affected_segments"].append(i)

    arrival = slot_departure + timedelta(seconds=route["total_duration_seconds"])

    return {
        "segments": segments,
        "alerts": all_alerts,
        "departure": slot_departure.isoformat(),
        "arrival": arrival.isoformat(),
    }
```

**Step 4: Refactor `route_weather` to use `build_slot_data`**

The existing `do_work()` in `route_weather` should use `build_slot_data` for the selected departure, then also loop over all slider slots:

```python
async def do_work():
    route = await fetch_route(origin, destination, departure.isoformat())
    points = decode_polyline(route["polyline"])
    waypoints = sample_waypoints(points)

    raw_weather = await fetch_raw_weather(waypoints)

    # Selected departure data (backward compat)
    selected = build_slot_data(departure, waypoints, route, raw_weather)

    # Compute all slider slots
    now = datetime.now(tz=timezone.utc).astimezone(departure.tzinfo)
    slot_times = compute_slider_range(departure, now)
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

**Step 5: Run all tests**

Run: `cd /Users/deepak/AI/drive-conditions && python -m pytest tests/ -v`
Expected: All pass

**Step 6: Commit**

```bash
git add app.py tests/test_app.py
git commit -m "feat: build multi-slot departure data in route-weather response"
```

---

### Task 4: Remove the "departure must be in the future" validation

The slider can include departure times that are "now" (ceiled to the hour). The existing validation rejects any departure in the past. Since the slider range is already clamped to `now`, we just need to relax the departure validation to allow the current time.

**Files:**
- Modify: `app.py:127-129`
- Test: `tests/test_app.py`

**Step 1: Update validation**

Change the departure validation in `route_weather()` to only reject times more than 48 hours in the past (or remove the check entirely since `compute_slider_range` handles clamping). Actually, keep a reasonable guard:

```python
# Allow departure times up to 5 minutes in the past (clock skew tolerance)
# The slider range itself is clamped to "now" so past slots won't be generated
now = datetime.now(tz=timezone.utc)
if departure < now - timedelta(minutes=5):
    return jsonify({"error": "Departure time must be in the future."}), 400
```

This is already the current behavior — no change needed. The selected departure (center of slider) is still validated as future. The slider slots that are "near now" are fine because they're generated from `compute_slider_range` which clamps to `now`.

**Step 2: Verify existing tests still pass**

Run: `cd /Users/deepak/AI/drive-conditions && python -m pytest tests/ -v`
Expected: All pass

No commit needed — no changes.

---

### Task 5: Add slider HTML and CSS to frontend

**Files:**
- Modify: `templates/index.html`

**Step 1: Add slider HTML**

Add a slider container below the header, before the main content. Insert after the `.header` div (after line 480):

```html
<!-- ── Departure Slider ────────────────────────────────── -->
<div class="slider-bar" id="slider-bar" style="display:none;">
  <div class="slider-label" id="slider-label">Departure: --</div>
  <div class="slider-row">
    <span class="slider-bound" id="slider-min-label">--</span>
    <input type="range" id="departure-slider" min="0" max="96" value="48" step="1">
    <span class="slider-bound" id="slider-max-label">--</span>
  </div>
</div>
```

**Step 2: Add slider CSS**

Add before the `/* ── Main Layout */` section:

```css
/* ── Departure Slider Bar ───────────────────────────── */
.slider-bar {
  background: #1e293b;
  padding: 10px 24px 12px;
  border-top: 1px solid #334155;
}

.slider-label {
  color: #e2e8f0;
  font-size: 14px;
  font-weight: 600;
  text-align: center;
  margin-bottom: 6px;
}

.slider-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.slider-bound {
  color: #64748b;
  font-size: 11px;
  white-space: nowrap;
  min-width: 100px;
}

.slider-bound:last-child {
  text-align: right;
}

#departure-slider {
  flex: 1;
  -webkit-appearance: none;
  appearance: none;
  height: 6px;
  background: #334155;
  border-radius: 3px;
  outline: none;
  cursor: pointer;
}

#departure-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 18px;
  height: 18px;
  background: #3b82f6;
  border-radius: 50%;
  border: 2px solid #e2e8f0;
  cursor: pointer;
  transition: transform 0.1s;
}

#departure-slider::-webkit-slider-thumb:hover {
  transform: scale(1.2);
}

#departure-slider::-moz-range-thumb {
  width: 18px;
  height: 18px;
  background: #3b82f6;
  border-radius: 50%;
  border: 2px solid #e2e8f0;
  cursor: pointer;
}
```

**Step 3: Commit**

```bash
git add templates/index.html
git commit -m "feat: add departure time slider HTML and CSS"
```

---

### Task 6: Add slider JavaScript logic

**Files:**
- Modify: `templates/index.html` (script section)

**Step 1: Add DOM refs for slider elements**

After the existing DOM refs block (~line 530), add:

```javascript
const sliderBar     = document.getElementById("slider-bar");
const sliderEl      = document.getElementById("departure-slider");
const sliderLabel   = document.getElementById("slider-label");
const sliderMinLabel = document.getElementById("slider-min-label");
const sliderMaxLabel = document.getElementById("slider-max-label");
```

**Step 2: Add state variables for slot data**

After the map setup variables (~line 553), add:

```javascript
let currentSlots = null;      // { "iso": { segments, alerts, departure, arrival } }
let slotKeys = [];            // sorted array of ISO keys
let currentRouteData = null;  // full API response (for polyline, route metadata)
```

**Step 3: Add slider formatting helper**

Add near the other utility functions:

```javascript
function formatSliderTime(isoStr) {
  if (!isoStr) return "--";
  var d = new Date(isoStr);
  var days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  var months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return days[d.getDay()] + " " + months[d.getMonth()] + " " + d.getDate() + ", " +
    d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", hour12: true });
}
```

**Step 4: Add `initSlider` function**

```javascript
function initSlider(data) {
  currentSlots = data.slots;
  currentRouteData = data;
  slotKeys = Object.keys(currentSlots).sort();

  if (slotKeys.length === 0) {
    sliderBar.style.display = "none";
    return;
  }

  sliderEl.min = 0;
  sliderEl.max = slotKeys.length - 1;

  // Find the index of the selected departure
  var selectedKey = data.slider_range.selected;
  var selectedIdx = slotKeys.indexOf(selectedKey);
  if (selectedIdx < 0) {
    // Find closest
    selectedIdx = 0;
    var selectedDate = new Date(selectedKey).getTime();
    var bestDiff = Infinity;
    for (var i = 0; i < slotKeys.length; i++) {
      var diff = Math.abs(new Date(slotKeys[i]).getTime() - selectedDate);
      if (diff < bestDiff) {
        bestDiff = diff;
        selectedIdx = i;
      }
    }
  }

  sliderEl.value = selectedIdx;
  sliderMinLabel.textContent = formatSliderTime(slotKeys[0]);
  sliderMaxLabel.textContent = formatSliderTime(slotKeys[slotKeys.length - 1]);
  updateSliderLabel(selectedIdx);
  sliderBar.style.display = "block";
}
```

**Step 5: Add `updateSliderLabel` and `onSliderChange` functions**

```javascript
function updateSliderLabel(idx) {
  sliderLabel.textContent = "Departure: " + formatSliderTime(slotKeys[idx]);
}

function onSliderChange() {
  var idx = parseInt(sliderEl.value, 10);
  updateSliderLabel(idx);

  var key = slotKeys[idx];
  var slotData = currentSlots[key];
  if (!slotData) return;

  // Build a synthetic data object matching what drawRoute/buildPanel/buildSummary expect
  var displayData = {
    route: currentRouteData.route,
    segments: slotData.segments,
    alerts: slotData.alerts,
    sources: currentRouteData.sources,
  };

  // Update route departure/arrival in metadata
  displayData.route = Object.assign({}, currentRouteData.route, {
    departure: slotData.departure,
    arrival: slotData.arrival,
  });

  drawRoute(displayData);
  buildPanel(displayData);
  buildSummary(displayData);
}
```

**Step 6: Wire up slider event listener**

Add near the other event listeners:

```javascript
sliderEl.addEventListener("input", onSliderChange);
```

**Step 7: Update `fetchRoute` to init slider after successful response**

In the `.then(function(data) { ... })` block of `fetchRoute`, after the existing `buildSummary(data)` call, add:

```javascript
initSlider(data);
```

**Step 8: Test manually**

Run: `cd /Users/deepak/AI/drive-conditions && python app.py`
- Open browser to http://localhost:5001
- Enter origin/destination, click "Get Route"
- Verify slider appears below the header
- Slide left/right — map and panel should update

**Step 9: Commit**

```bash
git add templates/index.html
git commit -m "feat: wire up departure time slider with instant slot switching"
```

---

### Task 7: Optimize `drawRoute` to avoid re-decoding polyline on every slide

Currently `drawRoute` calls `google.maps.geometry.encoding.decodePath` every time. Since the polyline doesn't change across slots, decode it once and cache it.

**Files:**
- Modify: `templates/index.html`

**Step 1: Add cached path variable**

Near the map state variables:

```javascript
let cachedFullPath = null;
let cachedPolyline = null;
```

**Step 2: Modify `drawRoute` to use cache**

At the top of `drawRoute`, replace the decodePath call with:

```javascript
var encodedPath = data.route.polyline;
var fullPath;
if (cachedPolyline === encodedPath && cachedFullPath) {
  fullPath = cachedFullPath;
} else {
  fullPath = google.maps.geometry.encoding.decodePath(encodedPath);
  cachedFullPath = fullPath;
  cachedPolyline = encodedPath;
}
```

**Step 3: Skip `fitBounds` when sliding**

Add a parameter to `drawRoute` to skip bounds fitting on slider changes (so map doesn't jump):

Change signature to `function drawRoute(data, skipFitBounds)` and wrap the fitBounds call:

```javascript
if (!skipFitBounds) {
  var bounds = new google.maps.LatLngBounds();
  fullPath.forEach(function(p) { bounds.extend(p); });
  map.fitBounds(bounds, { top: 20, right: 20, bottom: 20, left: 20 });
}
```

Update `onSliderChange` to pass `true`:
```javascript
drawRoute(displayData, true);
```

The initial call in `fetchRoute` remains `drawRoute(data)` (no second arg = false = fit bounds).

**Step 4: Commit**

```bash
git add templates/index.html
git commit -m "perf: cache decoded polyline and skip fitBounds during slider changes"
```

---

### Task 8: End-to-end testing and polish

**Files:**
- Modify: `templates/index.html` (if needed)
- Modify: `app.py` (if needed)

**Step 1: Run all backend tests**

Run: `cd /Users/deepak/AI/drive-conditions && python -m pytest tests/ -v`
Expected: All pass

**Step 2: Manual end-to-end test**

Run the app and test:
1. Enter "San Mateo, CA" to "Mendocino, CA", tomorrow at 8AM
2. Click "Get Route" — verify route + slider appear
3. Slide to various times — verify:
   - Map colors change (different severity at different times)
   - Segment cards update (temperatures, conditions change)
   - Summary bar updates
   - No flickering or map jumping
4. Slide to the original position — verify it matches the initial view
5. Click "Get Route" again with different origin — verify slider resets

**Step 3: Fix any issues found**

Address any UI or data issues discovered during manual testing.

**Step 4: Final commit**

```bash
git add -A
git commit -m "feat: departure time slider for exploring weather at different times"
```
