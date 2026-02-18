# tests/test_weather_nws.py
from weather_nws import parse_hourly_forecast, find_forecast_for_time
from datetime import datetime, timezone, timedelta

SAMPLE_PERIOD = {
    "startTime": "2026-02-21T06:00:00-08:00",
    "endTime": "2026-02-21T07:00:00-08:00",
    "temperature": 48,
    "temperatureUnit": "F",
    "windSpeed": "10 mph",
    "windDirection": "SW",
    "shortForecast": "Partly Cloudy",
    "probabilityOfPrecipitation": {"value": 20},
    "relativeHumidity": {"value": 75},
}

def test_parse_hourly_forecast():
    result = parse_hourly_forecast(SAMPLE_PERIOD)
    assert result["temperature_f"] == 48
    assert result["wind_speed_mph"] == 10
    assert result["condition_text"] == "Partly Cloudy"
    assert result["precipitation_probability"] == 20

def test_find_forecast_for_time():
    periods = [
        {**SAMPLE_PERIOD, "startTime": "2026-02-21T06:00:00-08:00"},
        {**SAMPLE_PERIOD, "startTime": "2026-02-21T07:00:00-08:00",
         "temperature": 50, "shortForecast": "Cloudy"},
    ]
    target = datetime(2026, 2, 21, 6, 30,
                      tzinfo=timezone(timedelta(hours=-8)))
    result = find_forecast_for_time(periods, target)
    assert result["temperature_f"] == 48  # matches 6 AM period
