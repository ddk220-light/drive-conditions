from datetime import datetime, timedelta
from rest_stops import compute_rest_stop_positions, apply_rest_stop_delays


def test_rest_stops_short_trip():
    """Trip shorter than interval -> no rest stops."""
    etas = [
        datetime(2026, 2, 18, 8, 0),
        datetime(2026, 2, 18, 8, 30),
        datetime(2026, 2, 18, 9, 0),
    ]
    positions = compute_rest_stop_positions(etas, rest_interval_minutes=60)
    assert positions == []


def test_rest_stops_normal_trip():
    """3-hour trip with 60-min interval -> 2 stops."""
    base = datetime(2026, 2, 18, 8, 0)
    etas = [base + timedelta(minutes=i * 20) for i in range(10)]
    positions = compute_rest_stop_positions(etas, rest_interval_minutes=60)
    assert len(positions) == 2
    assert positions[0] == 3
    assert positions[1] == 6


def test_rest_stops_no_stop_at_destination():
    """Don't place a rest stop at the last waypoint."""
    base = datetime(2026, 2, 18, 8, 0)
    etas = [base, base + timedelta(minutes=60)]
    positions = compute_rest_stop_positions(etas, rest_interval_minutes=60)
    assert positions == []


def test_apply_rest_stop_delays():
    """Rest stops shift subsequent ETAs."""
    base = datetime(2026, 2, 18, 8, 0)
    etas = [base + timedelta(minutes=i * 30) for i in range(5)]
    result = apply_rest_stop_delays(etas, [2], rest_duration_minutes=20)
    assert result[0] == etas[0]
    assert result[1] == etas[1]
    assert result[2] == etas[2]
    assert result[3] == etas[3] + timedelta(minutes=20)
    assert result[4] == etas[4] + timedelta(minutes=20)


def test_apply_multiple_rest_stops():
    """Multiple rest stops accumulate delays."""
    base = datetime(2026, 2, 18, 8, 0)
    etas = [base + timedelta(minutes=i * 30) for i in range(7)]
    result = apply_rest_stop_delays(etas, [1, 4], rest_duration_minutes=20)
    assert result[0] == etas[0]
    assert result[1] == etas[1]
    assert result[2] == etas[2] + timedelta(minutes=20)
    assert result[4] == etas[4] + timedelta(minutes=20)
    assert result[5] == etas[5] + timedelta(minutes=40)
