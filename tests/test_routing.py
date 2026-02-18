import math
from routing import decode_polyline, sample_waypoints, compute_etas
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
