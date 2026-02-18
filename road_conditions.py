# road_conditions.py
import aiohttp
from routing import haversine_miles
from config import (
    CALTRANS_DISTRICTS, CALTRANS_RWIS_DISTRICTS,
    CALTRANS_CC_URL, CALTRANS_RWIS_URL, RWIS_MATCH_RADIUS_MILES,
)


def parse_chain_control(entry):
    """Parse a single chain control entry."""
    return {
        "highway": entry.get("highway", ""),
        "direction": entry.get("direction", ""),
        "level": entry.get("controlStatus", ""),
        "begin_postmile": entry.get("beginPostmile"),
        "end_postmile": entry.get("endPostmile"),
        "description": entry.get("description", ""),
    }


def match_rwis_to_waypoint(stations, waypoint, radius_miles=None):
    """Find the nearest RWIS station to a waypoint within radius."""
    if radius_miles is None:
        radius_miles = RWIS_MATCH_RADIUS_MILES

    best = None
    best_dist = float("inf")

    for station in stations:
        loc = station.get("location", {})
        slat = loc.get("latitude")
        slon = loc.get("longitude")
        if slat is None or slon is None:
            continue

        dist = haversine_miles(waypoint[0], waypoint[1], slat, slon)
        if dist < best_dist and dist <= radius_miles:
            best_dist = dist
            best = station

    if best is None:
        return None

    vis = best.get("visibility", {})
    vis_val = vis.get("value") if isinstance(vis, dict) else None
    wind = best.get("windSpeed", {})
    wind_val = wind.get("value") if isinstance(wind, dict) else None

    return {
        "pavement_status": best.get("surfaceStatus"),
        "pavement_temp_f": (best.get("surfaceTemperature", {}) or {}).get("value"),
        "air_temp_f": (best.get("airTemperature", {}) or {}).get("value"),
        "visibility_miles": vis_val,
        "wind_speed_mph": wind_val,
        "precipitation_type": best.get("precipitationType"),
        "distance_miles": round(best_dist, 1),
    }


async def fetch_chain_controls(session=None):
    """Fetch chain control data from all Caltrans districts."""
    own_session = session is None
    if own_session:
        session = aiohttp.ClientSession()

    try:
        all_controls = []
        for district in CALTRANS_DISTRICTS:
            url = CALTRANS_CC_URL.format(district=district)
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        entries = data if isinstance(data, list) else data.get("data", [])
                        for entry in entries:
                            parsed = parse_chain_control(entry)
                            if parsed["level"]:
                                all_controls.append(parsed)
            except Exception:
                continue

        return all_controls

    finally:
        if own_session:
            await session.close()


async def fetch_rwis_stations(session=None):
    """Fetch RWIS pavement sensor data from Caltrans districts."""
    own_session = session is None
    if own_session:
        session = aiohttp.ClientSession()

    try:
        all_stations = []
        for district in CALTRANS_RWIS_DISTRICTS:
            url = CALTRANS_RWIS_URL.format(district=district)
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        stations = data if isinstance(data, list) else data.get("data", [])
                        all_stations.extend(stations)
            except Exception:
                continue

        return all_stations

    finally:
        if own_session:
            await session.close()
