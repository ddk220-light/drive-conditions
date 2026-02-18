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
