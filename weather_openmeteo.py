# weather_openmeteo.py
import aiohttp
from datetime import datetime, timezone, timedelta
from utils import c_to_f, kmh_to_mph, m_to_miles, m_to_ft

OPENMETEO_URL = "https://api.open-meteo.com/v1/forecast"

HOURLY_VARS = (
    "temperature_2m,precipitation,snowfall,snow_depth,"
    "visibility,wind_speed_10m,wind_gusts_10m,wind_direction_10m,"
    "freezing_level_height,weather_code"
)

DAILY_VARS = "sunrise,sunset"


def parse_openmeteo_hourly(data, hour_index):
    """Parse Open-Meteo response at a specific hour index."""
    h = data["hourly"]
    temp_c = h["temperature_2m"][hour_index]
    return {
        "temperature_f": c_to_f(temp_c),
        "precipitation_mm_hr": h["precipitation"][hour_index],
        "snowfall_cm_hr": h["snowfall"][hour_index],
        "snow_depth_in": round(h["snow_depth"][hour_index] / 2.54, 1),
        "visibility_miles": m_to_miles(h["visibility"][hour_index]),
        "wind_speed_mph": kmh_to_mph(h["wind_speed_10m"][hour_index]),
        "wind_gusts_mph": kmh_to_mph(h["wind_gusts_10m"][hour_index]),
        "wind_direction_deg": h["wind_direction_10m"][hour_index],
        "freezing_level_ft": m_to_ft(h["freezing_level_height"][hour_index]),
        "weather_code": h["weather_code"][hour_index],
    }


def find_data_for_time(data, target_time):
    """Find the hourly slot closest to target_time and parse it."""
    times = data["hourly"]["time"]
    best_index = 0
    best_diff = float("inf")

    for i, t_str in enumerate(times):
        t = datetime.fromisoformat(t_str)
        if t.tzinfo is None and target_time.tzinfo is not None:
            t = t.replace(tzinfo=target_time.tzinfo)
        diff = abs((t - target_time).total_seconds())
        if diff < best_diff:
            best_diff = diff
            best_index = i

    return parse_openmeteo_hourly(data, best_index)


def find_sun_times_for_date(data, target_time):
    """Extract sunrise/sunset for the date matching target_time from Open-Meteo daily data.

    Returns {"sunrise": "...", "sunset": "..."} or None if no daily data.
    Falls back to first day if target date not found.
    """
    daily = data.get("daily")
    if not daily:
        return None

    dates = daily.get("time", [])
    sunrises = daily.get("sunrise", [])
    sunsets = daily.get("sunset", [])

    if not dates or not sunrises or not sunsets:
        return None

    target_date_str = target_time.strftime("%Y-%m-%d")

    for i, d in enumerate(dates):
        if d == target_date_str:
            return {"sunrise": sunrises[i], "sunset": sunsets[i]}

    # Fallback to first day
    return {"sunrise": sunrises[0], "sunset": sunsets[0]}


async def fetch_openmeteo(latitudes, longitudes, forecast_days=7, session=None):
    """Fetch Open-Meteo forecast for multiple coordinates.
    Returns: list of raw response dicts (one per coordinate).
    """
    own_session = session is None
    if own_session:
        session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))

    try:
        lat_str = ",".join(f"{lat:.4f}" for lat in latitudes)
        lon_str = ",".join(f"{lon:.4f}" for lon in longitudes)

        params = {
            "latitude": lat_str,
            "longitude": lon_str,
            "hourly": HOURLY_VARS,
            "daily": DAILY_VARS,
            "forecast_days": forecast_days,
            "temperature_unit": "celsius",
            "wind_speed_unit": "kmh",
            "timezone": "America/Los_Angeles",
        }

        async with session.get(OPENMETEO_URL, params=params) as resp:
            data = await resp.json()

        if isinstance(data, list):
            return data
        else:
            return [data]

    except Exception:
        return [None] * len(latitudes)
    finally:
        if own_session:
            await session.close()
