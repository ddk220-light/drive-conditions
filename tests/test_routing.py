import math
from routing import decode_polyline, sample_waypoints, compute_etas, compute_adjusted_etas, haversine_miles, find_closest_polyline_point, build_station_aware_waypoints
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
    assert etas[0] < etas[1] < etas[2]


def test_compute_etas_with_dict_waypoints():
    """compute_etas should handle dict waypoints with lat/lon keys."""
    waypoints = [
        {"lat": 37.77, "lon": -122.42, "type": "fill", "station": None},
        {"lat": 38.00, "lon": -122.00, "type": "rwis", "station": {}},
        {"lat": 38.58, "lon": -121.49, "type": "fill", "station": None},
    ]
    total_duration_seconds = 5400  # 90 minutes
    departure = datetime(2026, 2, 21, 6, 0, tzinfo=timezone(timedelta(hours=-8)))

    etas = compute_etas(waypoints, total_duration_seconds, departure)
    assert len(etas) == 3
    assert etas[0] == departure
    assert etas[-1] == departure + timedelta(seconds=5400)
    assert etas[0] < etas[1] < etas[2]


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
    # Route: ~138 miles. Stations only at start area.
    points = [(37.0, -122.0), (37.5, -122.0), (38.0, -122.0), (38.5, -122.0), (39.0, -122.0)]
    stations = [
        {"location": {"latitude": 37.05, "longitude": -122.0, "locationName": "Near Start"}},
    ]
    result = build_station_aware_waypoints(points, stations)
    # There should be fill waypoints covering the 100+ mile gap after the station
    fill_wps = [w for w in result if w["type"] == "fill"]
    assert len(fill_wps) >= 4  # origin + destination + at least 2 gap fills


def test_adjusted_etas_no_slowdown():
    """With factor 1.0 and no segment slowdowns, matches compute_etas."""
    waypoints = [(37.0, -122.0), (37.1, -122.1), (37.2, -122.2)]
    departure = datetime(2026, 2, 18, 8, 0)
    duration = 3600
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
    assert abs(total_adjusted - 7200) < 1


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
