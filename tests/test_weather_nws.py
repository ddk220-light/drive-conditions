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

def test_find_forecast_fallback_naive_starttime():
    """Fallback path with naive startTime and aware target_time must not crash."""
    periods = [
        {**SAMPLE_PERIOD, "startTime": "2026-02-21T06:00:00"},  # naive
    ]
    target = datetime(2026, 2, 21, 14, 0, tzinfo=timezone.utc)  # aware
    result = find_forecast_for_time(periods, target)
    assert result is not None
    assert result["temperature_f"] == 48


def test_fetch_nws_alerts_includes_expires_and_onset():
    """Alert dicts must include expires and onset fields from NWS properties."""
    from unittest.mock import AsyncMock, MagicMock
    import asyncio

    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={
        "features": [{
            "properties": {
                "event": "Winter Storm Warning",
                "headline": "Winter Storm Warning issued February 21",
                "severity": "Severe",
                "description": "Heavy snow expected.",
                "expires": "2026-02-21T18:00:00-08:00",
                "onset": "2026-02-21T06:00:00-08:00",
            }
        }]
    })
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_response)

    from weather_nws import fetch_nws_alerts
    alerts = asyncio.run(fetch_nws_alerts(37.5, -122.1, session=mock_session))

    assert len(alerts) == 1
    assert alerts[0]["expires"] == "2026-02-21T18:00:00-08:00"
    assert alerts[0]["onset"] == "2026-02-21T06:00:00-08:00"


def test_fetch_nws_alerts_missing_expires_returns_none():
    """When NWS alert has no expires field, it should be None."""
    from unittest.mock import AsyncMock, MagicMock
    import asyncio

    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={
        "features": [{
            "properties": {
                "event": "Flood Watch",
                "headline": "Flood Watch",
                "severity": "Moderate",
                "description": "Possible flooding.",
            }
        }]
    })
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_response)

    from weather_nws import fetch_nws_alerts
    alerts = asyncio.run(fetch_nws_alerts(37.5, -122.1, session=mock_session))

    assert len(alerts) == 1
    assert alerts[0]["expires"] is None
    assert alerts[0]["onset"] is None
