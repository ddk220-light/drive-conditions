# Test Coverage Analysis

## Current State

**Overall coverage: 73% (1529 statements, 406 missed)**
**Tests: 75 collected, 69 passing, 6 failing**

### Per-Module Coverage

| Module | Stmts | Miss | Coverage | Key Gaps |
|--------|-------|------|----------|----------|
| config.py | 19 | 0 | **100%** | — |
| utils.py | 45 | 2 | **96%** | Cache TTL eviction, double-check locking |
| assembler.py | 210 | 15 | **93%** | Some edge cases in severity + segment building |
| routing.py | 196 | 55 | **72%** | `fetch_route()`, fallback decoder, `_interpolate_along_route()` |
| weather_openmeteo.py | 54 | 17 | **69%** | `fetch_openmeteo()` async fetcher |
| weather_tomorrow.py | 43 | 17 | **60%** | `fetch_tomorrow()` async fetcher |
| weather_nws.py | 77 | 37 | **52%** | `fetch_nws_forecast()`, `fetch_nws_alerts()` async fetchers |
| road_conditions.py | 93 | 45 | **52%** | All 4 async fetch functions |
| rest_stops.py | 86 | 56 | **35%** | `insert_rest_stop_segments()`, `fetch_rest_stop_places()`, `_search_nearby()` |
| planner.py | 142 | 94 | **34%** | `fetch_raw_weather()`, `build_slot_data()`, most of `resolve_weather_for_etas()` |
| app.py | 73 | 55 | **25%** | Entire `route_weather()` endpoint, `index()` |

---

## Failing Tests (6)

### 1. `test_app.py` — 4 tests import `alert_active_at` from wrong module (lines 6, 14, 22, 30)

`alert_active_at` was moved from `app.py` to `planner.py`, but the tests still import from `app`. Fix: change the import to `from planner import alert_active_at`.

### 2. `test_assembler.py::test_compute_severity_yellow` (line 25)

The test expects `visibility_miles=3.0, wind_speed_mph=25, wind_gusts_mph=35, precipitation_mm_hr=1.5` to produce `"yellow"`, but the actual severity thresholds in `config.py` produce a score ≤ 3 (`"green"`). This is because:
- Visibility 3.0 → scores 1 (threshold is `< 5.0`)
- Wind effective = max(25, 35×0.7=24.5) = 25 → scores 1.5 (threshold is `> 25`, but 25 is not `> 25`)
- Precipitation 1.5 → scores 1 (threshold is `> 0.5`)
- Total = 1 + 0 + 1 = 2 → `"green"`

The wind threshold check is `>` (strict), so exactly 25 mph doesn't hit the `> 25` bracket. Fix: adjust the test input (e.g., wind_speed_mph=26) or reconsider the threshold.

### 3. `test_weather_nws.py::test_fetch_nws_alerts_missing_expires_returns_none` (line 106)

The test provides an alert with no `"expires"` key, but the NWS parser at `weather_nws.py:115` uses `props.get("expires")` which will fall through to whatever mock data is being provided. The test expectation or mock data needs to be aligned.

---

## Proposed Improvements (by priority)

### Priority 1: Fix the 6 failing tests

These are bugs in the test suite itself—they should be fixed before adding new tests.

- **Fix `test_app.py` imports**: Change `from app import alert_active_at` → `from planner import alert_active_at`
- **Fix `test_compute_severity_yellow`**: Adjust inputs so the score falls in the 4–6 range (e.g., `wind_speed_mph=30, visibility_miles=2.0`)
- **Fix `test_fetch_nws_alerts_missing_expires_returns_none`**: Align mock data with assertion

### Priority 2: Test async HTTP fetcher functions (biggest coverage gap)

Every module's async fetch function is currently untested. These represent the biggest untested surface area and the most likely source of production bugs (network errors, malformed responses, timeouts).

**Modules to add mocked async tests for:**

| Function | File:Line | What to test |
|----------|-----------|-------------|
| `fetch_nws_forecast()` | `weather_nws.py:59` | Successful 2-step fetch, non-200 status on points lookup, non-200 on forecast, network exception, session ownership |
| `fetch_nws_alerts()` | `weather_nws.py:93` | Successful fetch with multiple alerts, empty features list, non-200, exception |
| `fetch_openmeteo()` | `weather_openmeteo.py:80` | Successful single-coord fetch, multi-coord batch, exception fallback returning `[None]*len` |
| `fetch_tomorrow()` | `weather_tomorrow.py:62` | Successful fetch, empty timelines, exception |
| `fetch_chain_controls()` | `road_conditions.py:110` | Successful multi-district fetch, partial failures (some districts error), all districts error |
| `fetch_rwis_stations()` | `road_conditions.py:145` | Successful fetch, partial failures |
| `_fetch_cc_district()` | `road_conditions.py:96` | 200 with list response, 200 with dict `{data: [...]}` response, non-200, exception |
| `_fetch_rwis_district()` | `road_conditions.py:132` | Same patterns as `_fetch_cc_district` |
| `fetch_route()` | `routing.py:302` | Successful route, API error in response, no routes found, network exception |
| `fetch_rest_stop_places()` | `rest_stops.py:123` | Successful lookup, fallback when no place found, session ownership |
| `_search_nearby()` | `rest_stops.py:166` | Successful search, empty results, exception |

**Recommended approach:** Use `aiohttp` mocking via `aioresponses` library or `unittest.mock.AsyncMock` to simulate HTTP responses without hitting real APIs.

### Priority 3: Test `planner.py` orchestration logic

`planner.py` is at 34% coverage and contains the core data pipeline. Key functions to test:

- **`fetch_raw_weather()`** (`planner.py:53`): This is the central async orchestrator that calls all weather APIs in parallel and handles failures gracefully. Test with mocked API calls to verify:
  - Correct distribution of Tomorrow.io spatial sampling (≤5 waypoints vs >5)
  - Exception handling when individual sources fail (results should degrade gracefully)
  - Source tracking (`sources_set`) logic
  - RWIS station passthrough vs fresh fetch

- **`build_slot_data()`** (`planner.py:180`): End-to-end segment assembly pipeline. Test with pre-built raw weather data to verify:
  - Two-pass weather resolution (initial ETAs → slowdowns → adjusted ETAs → final weather)
  - Rest stop delay integration
  - Alert deduplication logic (lines 238-250)
  - Light level computation per segment

- **`resolve_weather_for_etas()`** (`planner.py:144`): Currently only tested for the RWIS station path. Add tests for:
  - Standard waypoint (non-RWIS) path
  - Mixed RWIS and fill waypoints
  - Missing/None data in various raw weather fields

### Priority 4: Test `rest_stops.py` pure logic functions

`insert_rest_stop_segments()` (`rest_stops.py:63`) is completely untested pure logic:

- Inserting a single rest stop pseudo-segment
- Inserting multiple rest stops (reverse-index insertion correctness)
- Rest stop with `place_name=None` (generates fallback name)
- ETA computation for rest stop arrive/depart times
- String vs datetime `eta_arrive` handling

### Priority 5: Test the Flask API endpoint

`app.py:route_weather()` at 25% coverage is the application's only API endpoint. Test with Flask's test client:

- **Input validation**: Missing params → 400, origin/destination too long → 400, invalid departure format → 400, past departure → 400
- **Parameter parsing**: `speed_factor` clamping (0.5–1.0), `rest_enabled`, `rest_interval` clamping (30–180), `rest_duration` clamping (5–60)
- **Timezone handling**: Naive departure → assumes Pacific, aware departure → used as-is
- **Error propagation**: `ValueError` from routing → 400 response
- **Success path**: Full end-to-end with mocked dependencies

### Priority 6: Edge cases in well-covered modules

**assembler.py** (93% but some branches uncovered):
- `compute_severity()` with road conditions containing chain controls (R1/R2/R3 levels) — lines 198-207
- `compute_severity()` with road conditions containing ice/snow pavement status — lines 209-213
- `compute_severity()` with alert severity "extreme"/"severe" vs "moderate" — lines 216-221
- `merge_weather()` with only NWS temperature (no Open-Meteo or Tomorrow.io) — line 124
- `merge_weather()` with all `None` sources

**routing.py** (72%):
- `_interpolate_along_route()` (`routing.py:211`) — untested helper
- `_coords()` (`routing.py:219`) — untested helper (though used transitively)
- `compute_etas()` with single waypoint — line 228-229
- `compute_etas()` with zero total distance — line 239-240
- `compute_adjusted_etas()` with zero total distance — line 278-279
- Fallback polyline decoder (lines 11-34) — only used if `polyline` package missing

**utils.py** (96%):
- `AsyncCache.get()` TTL expiration path — line 19
- `cached_weather_fetcher` double-check locking (cache hit inside semaphore) — line 46

### Priority 7: Test infrastructure improvements

- **Add `conftest.py`**: Shared fixtures for common test data (waypoints, weather dicts, mock sessions)
- **Add `pytest.ini` or `pyproject.toml`**: Configure test paths, markers, and coverage settings
- **Add CI/CD**: GitHub Actions workflow to run tests on every push/PR
- **Add `aioresponses` to dev dependencies**: For mocking async HTTP calls
- **Consider property-based testing**: For `haversine_miles()`, unit conversions, and severity scoring (use `hypothesis`)

---

## Summary

The codebase's pure-logic functions (parsing, scoring, classification) are well-tested. The primary gaps are:

1. **Async HTTP fetchers** — every module's network layer is untested (biggest risk)
2. **Orchestration logic in `planner.py`** — the core pipeline that ties everything together
3. **Flask API endpoint** — no integration tests for request validation or the full request lifecycle
4. **6 failing tests** — broken imports and threshold mismatches that need immediate fixes
5. **`rest_stops.py` segment insertion** — pure logic that's easy to test but completely untested
