# tests/test_weather_openmeteo.py
from weather_openmeteo import parse_openmeteo_hourly, find_data_for_time, find_sun_times_for_date
from datetime import datetime, timezone, timedelta

SAMPLE_RESPONSE = {
    "hourly": {
        "time": ["2026-02-21T06:00", "2026-02-21T07:00", "2026-02-21T08:00"],
        "temperature_2m": [8.5, 9.2, 10.1],
        "precipitation": [0.0, 0.5, 2.1],
        "snowfall": [0.0, 0.0, 0.0],
        "snow_depth": [0.0, 0.0, 0.0],
        "visibility": [16000, 8000, 3000],
        "wind_speed_10m": [12.0, 18.5, 25.0],
        "wind_gusts_10m": [20.0, 30.0, 45.0],
        "wind_direction_10m": [225, 230, 240],
        "freezing_level_height": [1600, 1500, 1400],
        "weather_code": [1, 61, 63],
    },
    "hourly_units": {
        "temperature_2m": "°C",
    }
}

def test_parse_openmeteo_hourly():
    result = parse_openmeteo_hourly(SAMPLE_RESPONSE, hour_index=1)
    assert abs(result["temperature_f"] - 48.56) < 0.1  # 9.2°C -> F
    assert result["precipitation_mm_hr"] == 0.5
    assert result["wind_speed_mph"] > 11  # 18.5 km/h -> mph
    assert result["visibility_miles"] <= 5.0  # 8000m -> miles

def test_find_data_for_time():
    pst = timezone(timedelta(hours=-8))
    target = datetime(2026, 2, 21, 7, 30, tzinfo=pst)
    result = find_data_for_time(SAMPLE_RESPONSE, target)
    # Should match the 07:00 slot (index 1)
    assert result["precipitation_mm_hr"] == 0.5


# ── find_sun_times_for_date tests ───────────────────────────────────

SAMPLE_WITH_DAILY = {
    **SAMPLE_RESPONSE,
    "daily": {
        "time": ["2026-02-20", "2026-02-21", "2026-02-22"],
        "sunrise": ["2026-02-20T06:50", "2026-02-21T06:49", "2026-02-22T06:48"],
        "sunset": ["2026-02-20T17:42", "2026-02-21T17:43", "2026-02-22T17:44"],
    },
}


def test_find_sun_times_for_date():
    """Should extract sunrise/sunset for the matching date."""
    pst = timezone(timedelta(hours=-8))
    target = datetime(2026, 2, 21, 12, 0, tzinfo=pst)
    result = find_sun_times_for_date(SAMPLE_WITH_DAILY, target)
    assert result is not None
    assert result["sunrise"] == "2026-02-21T06:49"
    assert result["sunset"] == "2026-02-21T17:43"


def test_find_sun_times_for_date_fallback_first_day():
    """When the target date is not in daily data, fall back to first day."""
    pst = timezone(timedelta(hours=-8))
    target = datetime(2026, 3, 1, 12, 0, tzinfo=pst)
    result = find_sun_times_for_date(SAMPLE_WITH_DAILY, target)
    assert result is not None
    assert result["sunrise"] == "2026-02-20T06:50"
    assert result["sunset"] == "2026-02-20T17:42"


def test_find_sun_times_no_daily():
    """When there is no daily data, return None."""
    result = find_sun_times_for_date(SAMPLE_RESPONSE, datetime(2026, 2, 21, 12, 0))
    assert result is None
