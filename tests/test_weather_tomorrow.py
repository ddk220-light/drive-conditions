# tests/test_weather_tomorrow.py
from weather_tomorrow import parse_tomorrow_hourly, find_data_for_time
from datetime import datetime, timezone, timedelta

SAMPLE_INTERVAL = {
    "startTime": "2026-02-21T06:00:00-08:00",
    "values": {
        "temperature": 9.0,
        "precipitationProbability": 25,
        "precipitationType": 1,  # 1=rain
        "windSpeed": 15.0,
        "windGust": 28.0,
        "visibility": 12.0,
        "weatherCode": 1100,
    }
}

def test_parse_tomorrow_hourly():
    result = parse_tomorrow_hourly(SAMPLE_INTERVAL)
    assert abs(result["temperature_f"] - 48.2) < 0.5
    assert result["precipitation_probability"] == 25
    assert result["precipitation_type"] == "rain"
    assert abs(result["visibility_miles"] - 7.5) < 0.1  # 12 km → ~7.5 mi
    assert result["road_risk_score"] is None  # Not in basic response

def test_find_data_for_time():
    intervals = [
        {**SAMPLE_INTERVAL, "startTime": "2026-02-21T06:00:00-08:00"},
        {**SAMPLE_INTERVAL, "startTime": "2026-02-21T07:00:00-08:00",
         "values": {**SAMPLE_INTERVAL["values"], "temperature": 11.0}},
    ]
    pst = timezone(timedelta(hours=-8))
    target = datetime(2026, 2, 21, 6, 20, tzinfo=pst)
    result = find_data_for_time(intervals, target)
    assert abs(result["temperature_f"] - 48.2) < 0.5  # matches 6 AM
