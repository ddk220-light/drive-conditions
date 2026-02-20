# weather_tomorrow.py
import aiohttp
from datetime import datetime, timezone, timedelta
from config import TOMORROW_API_KEY
from utils import c_to_f, kmh_to_mph, km_to_miles, cached_weather_fetcher

TOMORROW_URL = "https://api.tomorrow.io/v4/timelines"

PRECIP_TYPE_MAP = {0: "none", 1: "rain", 2: "snow", 3: "freezing_rain", 4: "sleet"}

WEATHER_CODE_MAP = {
    1000: "Clear", 1100: "Mostly Clear", 1101: "Partly Cloudy",
    1102: "Mostly Cloudy", 1001: "Cloudy", 2000: "Fog", 2100: "Light Fog",
    4000: "Drizzle", 4001: "Rain", 4200: "Light Rain", 4201: "Heavy Rain",
    5000: "Snow", 5001: "Flurries", 5100: "Light Snow", 5101: "Heavy Snow",
    6000: "Freezing Drizzle", 6001: "Freezing Rain", 6200: "Light Freezing Rain",
    6201: "Heavy Freezing Rain", 7000: "Ice Pellets", 7101: "Heavy Ice Pellets",
    7102: "Light Ice Pellets", 8000: "Thunderstorm",
}


def parse_tomorrow_hourly(interval):
    """Parse a single Tomorrow.io timeline interval."""
    v = interval["values"]
    temp_c = v.get("temperature", 0)
    precip_type_code = v.get("precipitationType", 0)

    return {
        "temperature_f": c_to_f(temp_c),
        "precipitation_probability": v.get("precipitationProbability", 0),
        "precipitation_type": PRECIP_TYPE_MAP.get(precip_type_code, "unknown"),
        "wind_speed_mph": kmh_to_mph(v.get("windSpeed", 0)),
        "wind_gusts_mph": kmh_to_mph(v.get("windGust", 0)),
        "visibility_miles": km_to_miles(v.get("visibility", 16)),
        "weather_code": v.get("weatherCode"),
        "weather_text": WEATHER_CODE_MAP.get(v.get("weatherCode"), "Unknown"),
        "road_risk_score": v.get("roadRisk"),
        "road_risk_label": v.get("roadRiskLabel"),
    }


def find_data_for_time(intervals, target_time):
    """Find the interval closest to target_time."""
    best = None
    best_diff = float("inf")

    for interval in intervals:
        t = datetime.fromisoformat(interval["startTime"])
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        diff = abs((t - target_time).total_seconds())
        if diff < best_diff:
            best_diff = diff
            best = interval

    if best:
        return parse_tomorrow_hourly(best)
    return None


@cached_weather_fetcher(ttl_seconds=3600, max_concurrent=3, round_digits=2)
async def fetch_tomorrow(lat, lon, session=None):
    """Fetch hourly forecast from Tomorrow.io for a single point.
    Returns list of interval dicts.
    """
    own_session = session is None
    if own_session:
        session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))

    try:
        params = {
            "location": f"{lat:.4f},{lon:.4f}",
            "fields": (
                "temperature,precipitationProbability,precipitationType,"
                "windSpeed,windGust,visibility,weatherCode"
            ),
            "timesteps": "1h",
            "units": "metric",
            "apikey": TOMORROW_API_KEY,
        }

        async with session.get(TOMORROW_URL, params=params) as resp:
            data = await resp.json()

        timelines = data.get("data", {}).get("timelines", [])
        if timelines:
            return timelines[0].get("intervals", [])
        return []

    except Exception:
        return []
    finally:
        if own_session:
            await session.close()
