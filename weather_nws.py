# weather_nws.py
import re
import aiohttp
from datetime import datetime, timezone
from config import NWS_USER_AGENT


def parse_hourly_forecast(period):
    """Parse a single NWS hourly forecast period into normalized dict."""
    wind_match = re.search(r"(\d+)", period.get("windSpeed", "0"))
    wind_speed = int(wind_match.group(1)) if wind_match else 0

    precip = period.get("probabilityOfPrecipitation", {})
    precip_pct = precip.get("value") if precip.get("value") is not None else 0

    return {
        "temperature_f": period.get("temperature"),
        "wind_speed_mph": wind_speed,
        "wind_direction": period.get("windDirection", ""),
        "condition_text": period.get("shortForecast", ""),
        "precipitation_probability": precip_pct,
    }


def find_forecast_for_time(periods, target_time):
    """Find the forecast period that contains the target time."""
    for period in periods:
        start = datetime.fromisoformat(period["startTime"])
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        end_str = period.get("endTime")
        if end_str:
            end = datetime.fromisoformat(end_str)
        else:
            from datetime import timedelta
            end = start + timedelta(hours=1)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)

        if start <= target_time < end:
            return parse_hourly_forecast(period)

    # Fallback: return closest period
    if periods:
        def _period_diff(p):
            t = datetime.fromisoformat(p["startTime"])
            if t.tzinfo is None and target_time.tzinfo is not None:
                t = t.replace(tzinfo=timezone.utc)
            return abs((t - target_time).total_seconds())

        closest = min(periods, key=_period_diff)
        return parse_hourly_forecast(closest)
    return None


from utils import cached_weather_fetcher

@cached_weather_fetcher(ttl_seconds=3600, max_concurrent=5, round_digits=2)
async def fetch_nws_forecast(lat, lon, session=None):
    """Fetch hourly forecast from NWS for a lat/lon point.
    Two-step: /points -> /gridpoints forecast/hourly
    Returns list of parsed forecast periods.
    """
    headers = {"User-Agent": NWS_USER_AGENT, "Accept": "application/geo+json"}
    own_session = session is None
    if own_session:
        session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))

    try:
        points_url = f"https://api.weather.gov/points/{lat:.4f},{lon:.4f}"
        async with session.get(points_url, headers=headers) as resp:
            if resp.status != 200:
                return None
            points_data = await resp.json()

        forecast_url = points_data["properties"]["forecastHourly"]

        async with session.get(forecast_url, headers=headers) as resp:
            if resp.status != 200:
                return None
            forecast_data = await resp.json()

        return forecast_data["properties"]["periods"]

    except Exception:
        return None
    finally:
        if own_session:
            await session.close()


@cached_weather_fetcher(ttl_seconds=3600, max_concurrent=5, round_digits=2)
async def fetch_nws_alerts(lat, lon, session=None):
    """Fetch active weather alerts near a point."""
    headers = {"User-Agent": NWS_USER_AGENT, "Accept": "application/geo+json"}
    own_session = session is None
    if own_session:
        session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))

    try:
        url = f"https://api.weather.gov/alerts/active?point={lat:.4f},{lon:.4f}"
        async with session.get(url, headers=headers) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()

        alerts = []
        for feature in data.get("features", []):
            props = feature["properties"]
            alerts.append({
                "type": props.get("event", ""),
                "headline": props.get("headline", ""),
                "severity": props.get("severity", "").lower(),
                "description": props.get("description", ""),
                "expires": props.get("expires"),
                "onset": props.get("onset"),
            })
        return alerts

    except Exception:
        return []
    finally:
        if own_session:
            await session.close()
