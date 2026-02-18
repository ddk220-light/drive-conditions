# rest_stops.py
"""Rest stop computation and Google Places lookup."""

import aiohttp
from copy import deepcopy
from datetime import timedelta

from config import GOOGLE_API_KEY
from routing import _coords


def compute_rest_stop_positions(etas, rest_interval_minutes=60):
    """Walk segments and find waypoint indices where rest stops should be placed.

    When cumulative driving time since the last rest (or start) reaches
    rest_interval_minutes, the current waypoint is marked as a rest stop.
    Never places a rest stop at the last waypoint (destination).
    Resets cumulative time after each rest stop.

    Returns:
        List of waypoint indices (ints).
    """
    if len(etas) < 2:
        return []

    rest_interval = timedelta(minutes=rest_interval_minutes)
    positions = []
    last_rest_eta = etas[0]

    for i in range(1, len(etas)):
        cumulative_drive = etas[i] - last_rest_eta
        if cumulative_drive >= rest_interval:
            # Never place a rest stop at the last waypoint (destination)
            if i == len(etas) - 1:
                break
            positions.append(i)
            last_rest_eta = etas[i]

    return positions


def apply_rest_stop_delays(etas, rest_indices, rest_duration_minutes=20):
    """Shift ETAs for rest stops. Rest occurs AFTER arriving at the indexed waypoint.

    All subsequent ETAs are shifted by rest_duration_minutes per stop.
    Multiple rest stops accumulate delays.

    Returns:
        New list of ETAs (does not modify original).
    """
    delay = timedelta(minutes=0)
    rest_set = set(rest_indices)
    result = []

    for i, eta in enumerate(etas):
        result.append(eta + delay)
        if i in rest_set:
            delay += timedelta(minutes=rest_duration_minutes)

    return result


def insert_rest_stop_segments(segments, rest_stop_info, rest_duration_minutes):
    """Insert rest stop pseudo-segments into the segment list.

    Args:
        segments: List of segment dicts (will not be modified).
        rest_stop_info: List of dicts with keys:
            after_segment_index, place_name, location ({lat, lng}).
        rest_duration_minutes: Duration of each rest stop.

    Returns:
        New list of segments with rest stop pseudo-segments inserted.
    """
    result = list(segments)

    # Insert in reverse index order to avoid shifting issues
    sorted_info = sorted(rest_stop_info, key=lambda x: x["after_segment_index"], reverse=True)

    for info in sorted_info:
        idx = info["after_segment_index"]
        place_name = info.get("place_name")
        location = info["location"]

        # Get the segment we're inserting after for mile_marker and eta info
        ref_segment = result[idx] if idx < len(result) else result[-1]
        mile_marker = ref_segment.get("mile_marker", 0)
        eta_arrive = ref_segment.get("eta", None)

        if place_name is None:
            place_name = f"Rest stop (mile {mile_marker})"

        # Compute departure time from the rest stop
        eta_depart = None
        if eta_arrive is not None:
            from datetime import datetime
            if isinstance(eta_arrive, str):
                eta_arrive_dt = datetime.fromisoformat(eta_arrive)
            else:
                eta_arrive_dt = eta_arrive
            eta_depart = (eta_arrive_dt + timedelta(minutes=rest_duration_minutes)).isoformat()
            if isinstance(eta_arrive, str):
                pass  # keep as string
            else:
                eta_arrive = eta_arrive.isoformat()

        pseudo_segment = {
            "type": "rest_stop",
            "location": location,
            "place_name": place_name,
            "rest_duration_minutes": rest_duration_minutes,
            "eta_arrive": eta_arrive,
            "eta_depart": eta_depart,
            "mile_marker": mile_marker,
        }

        # Insert after the indexed segment
        result.insert(idx + 1, pseudo_segment)

    return result


async def fetch_rest_stop_places(positions, waypoints, session=None):
    """For each rest stop position, look up a nearby rest stop or gas station.

    Args:
        positions: List of waypoint indices where rest stops should be placed.
        waypoints: List of waypoints (dicts or tuples).
        session: Optional aiohttp.ClientSession.

    Returns:
        List of dicts: {after_segment_index, place_name, location: {lat, lng}}
    """
    own_session = session is None
    if own_session:
        session = aiohttp.ClientSession()

    results = []
    try:
        for pos in positions:
            wp = waypoints[pos]
            lat, lon = _coords(wp)

            place = await _search_nearby(session, lat, lon)

            if place:
                results.append({
                    "after_segment_index": pos,
                    "place_name": place["name"],
                    "location": place["location"],
                })
            else:
                # Fallback: use the waypoint's own coordinates
                results.append({
                    "after_segment_index": pos,
                    "place_name": None,
                    "location": {"lat": lat, "lng": lon},
                })
    finally:
        if own_session:
            await session.close()

    return results


async def _search_nearby(session, lat, lon):
    """Search Google Places Nearby for rest stops or gas stations.

    Args:
        session: aiohttp.ClientSession.
        lat: Latitude.
        lon: Longitude.

    Returns:
        Dict with {"name": str, "location": {"lat": float, "lng": float}}
        or None on error or no results.
    """
    url = "https://places.googleapis.com/v1/places:searchNearby"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_API_KEY,
        "X-Goog-FieldMask": "places.displayName,places.location",
    }
    body = {
        "includedTypes": ["rest_stop", "gas_station"],
        "maxResultCount": 1,
        "locationRestriction": {
            "circle": {
                "center": {
                    "latitude": lat,
                    "longitude": lon,
                },
                "radius": 8046.72,
            }
        },
    }

    try:
        async with session.post(url, json=body, headers=headers) as resp:
            data = await resp.json()

        places = data.get("places", [])
        if not places:
            return None

        place = places[0]
        display_name = place.get("displayName", {})
        name = display_name.get("text", "Rest Stop")
        location = place.get("location", {})

        return {
            "name": name,
            "location": {
                "lat": location.get("latitude", lat),
                "lng": location.get("longitude", lon),
            },
        }
    except Exception:
        return None
