# tests/test_weather_openmeteo.py
from weather_openmeteo import parse_openmeteo_hourly, find_data_for_time
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
