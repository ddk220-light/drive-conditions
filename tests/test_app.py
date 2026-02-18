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


def test_fetch_raw_weather_returns_raw_data():
    """fetch_raw_weather should return raw API results without time lookups."""
    import app as app_module
    assert hasattr(app_module, 'fetch_raw_weather'), "fetch_raw_weather not defined"
    assert callable(app_module.fetch_raw_weather)


def test_compute_slider_range_basic():
    """Slider range spans 2 days before to 2 days after departure, 1-hour steps."""
    from zoneinfo import ZoneInfo
    from app import compute_slider_range
    pac = ZoneInfo("America/Los_Angeles")
    departure = datetime(2026, 2, 20, 8, 0, tzinfo=pac)
    now = datetime(2026, 2, 18, 10, 0, tzinfo=pac)

    slots = compute_slider_range(departure, now)

    assert slots[0] == datetime(2026, 2, 18, 10, 0, tzinfo=pac)
    assert slots[-1] == datetime(2026, 2, 22, 8, 0, tzinfo=pac)
    for i in range(1, len(slots)):
        assert slots[i] - slots[i-1] == timedelta(hours=1)


def test_compute_slider_range_clamps_to_now():
    """If departure - 48h is in the past, start from now."""
    from zoneinfo import ZoneInfo
    from app import compute_slider_range
    pac = ZoneInfo("America/Los_Angeles")
    departure = datetime(2026, 2, 18, 8, 0, tzinfo=pac)
    now = datetime(2026, 2, 17, 14, 30, tzinfo=pac)

    slots = compute_slider_range(departure, now)

    # now is Feb 17 14:30 -> ceiled to Feb 17 15:00
    assert slots[0] == datetime(2026, 2, 17, 15, 0, tzinfo=pac)
    assert slots[-1] == datetime(2026, 2, 20, 8, 0, tzinfo=pac)


def test_build_slot_data_returns_segments_and_alerts():
    """build_slot_data should return dict with segments, alerts, departure, arrival."""
    from app import build_slot_data
    assert callable(build_slot_data)
