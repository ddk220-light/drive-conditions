# road_conditions.py
import re
import asyncio
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


_CC_LEVEL_RANK = {"R1": 1, "R2": 2, "R3": 3}


def match_chain_control_to_instruction(chain_controls, instruction_text):
    """Match chain controls to a turn instruction by highway name.

    Looks for patterns like I-80, US-50, SR-88, CA-89, Hwy 50, etc. in the
    instruction text and returns the most restrictive matching control, or None.
    """
    if not chain_controls or not instruction_text:
        return None

    # Extract highway numbers from instruction text
    # Matches: I-80, US-50, SR-88, CA-89, Hwy 50, Highway 50, Route 80
    hw_pattern = re.compile(
        r"(?:I-|US-|SR-|CA-|Hwy\s*|Highway\s*|Route\s*)(\d+)", re.IGNORECASE
    )
    instruction_highways = set(hw_pattern.findall(instruction_text))
    if not instruction_highways:
        return None

    best = None
    best_rank = 0
    for cc in chain_controls:
        if cc["highway"] in instruction_highways:
            rank = _CC_LEVEL_RANK.get(cc["level"], 0)
            if rank > best_rank:
                best_rank = rank
                best = cc

    return best


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


async def _fetch_cc_district(session, district):
    """Fetch chain control data for a single district."""
    url = CALTRANS_CC_URL.format(district=district)
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                data = await resp.json()
                entries = data if isinstance(data, list) else data.get("data", [])
                return [parse_chain_control(e) for e in entries if parse_chain_control(e)["level"]]
    except Exception:
        pass
    return []


async def fetch_chain_controls(session=None):
    """Fetch chain control data from all Caltrans districts in parallel."""
    own_session = session is None
    if own_session:
        session = aiohttp.ClientSession()

    try:
        results = await asyncio.gather(
            *[_fetch_cc_district(session, d) for d in CALTRANS_DISTRICTS],
            return_exceptions=True,
        )
        all_controls = []
        for r in results:
            if isinstance(r, list):
                all_controls.extend(r)
        return all_controls

    finally:
        if own_session:
            await session.close()


async def _fetch_rwis_district(session, district):
    """Fetch RWIS data for a single district."""
    url = CALTRANS_RWIS_URL.format(district=district)
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data if isinstance(data, list) else data.get("data", [])
    except Exception:
        pass
    return []


async def fetch_rwis_stations(session=None):
    """Fetch RWIS pavement sensor data from Caltrans districts in parallel."""
    own_session = session is None
    if own_session:
        session = aiohttp.ClientSession()

    try:
        results = await asyncio.gather(
            *[_fetch_rwis_district(session, d) for d in CALTRANS_RWIS_DISTRICTS],
            return_exceptions=True,
        )
        all_stations = []
        for r in results:
            if isinstance(r, list):
                all_stations.extend(r)
        return all_stations

    finally:
        if own_session:
            await session.close()
