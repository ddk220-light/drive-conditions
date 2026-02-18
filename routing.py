import math
import aiohttp
from datetime import datetime, timedelta
from config import GOOGLE_API_KEY, WAYPOINT_INTERVAL_MILES

try:
    import polyline as polyline_lib
    def decode_polyline(encoded):
        return polyline_lib.decode(encoded)
except ImportError:
    def decode_polyline(encoded):
        """Fallback pure-Python polyline decoder."""
        points = []
        index = 0
        lat = 0
        lng = 0
        while index < len(encoded):
            for var in ('lat', 'lng'):
                shift = 0
                result = 0
                while True:
                    b = ord(encoded[index]) - 63
                    index += 1
                    result |= (b & 0x1F) << shift
                    shift += 5
                    if b < 0x20:
                        break
                dlat_or_dlng = ~(result >> 1) if (result & 1) else (result >> 1)
                if var == 'lat':
                    lat += dlat_or_dlng
                else:
                    lng += dlat_or_dlng
            points.append((lat / 1e5, lng / 1e5))
        return points


def haversine_miles(lat1, lon1, lat2, lon2):
    """Distance between two lat/lon points in miles."""
    R = 3958.8
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def find_closest_polyline_point(points, lat, lon):
    """Find the closest point on a polyline to a given lat/lon.

    Returns (distance_from_route_miles, along_route_miles).
    distance_from_route_miles: straight-line distance from (lat, lon) to nearest polyline point.
    along_route_miles: cumulative distance along the polyline to that nearest point.
    """
    best_dist = float("inf")
    best_along = 0.0
    cumulative = 0.0

    for i, pt in enumerate(points):
        if i > 0:
            cumulative += haversine_miles(points[i-1][0], points[i-1][1], pt[0], pt[1])
        d = haversine_miles(pt[0], pt[1], lat, lon)
        if d < best_dist:
            best_dist = d
            best_along = cumulative

    return best_dist, best_along


def sample_waypoints(points, interval_miles=None):
    """Sample waypoints from a decoded polyline at regular distance intervals."""
    if interval_miles is None:
        interval_miles = WAYPOINT_INTERVAL_MILES
    if len(points) <= 2:
        return list(points)

    sampled = [points[0]]
    accumulated = 0.0

    for i in range(1, len(points)):
        d = haversine_miles(points[i-1][0], points[i-1][1],
                           points[i][0], points[i][1])
        accumulated += d
        if accumulated >= interval_miles:
            sampled.append(points[i])
            accumulated = 0.0

    if sampled[-1] != points[-1]:
        sampled.append(points[-1])

    return sampled


def build_station_aware_waypoints(points, rwis_stations,
                                   snap_radius=None, min_spacing=None,
                                   gap_threshold=None, fill_interval=None):
    """Build waypoints prioritizing RWIS station locations along the route.

    Args:
        points: Decoded polyline points [(lat, lon), ...].
        rwis_stations: List of RWIS station dicts with location.latitude/longitude.
        snap_radius: Max miles from route to consider a station (default RWIS_SNAP_RADIUS_MILES).
        min_spacing: Min miles between adjacent stations (default RWIS_MIN_STATION_SPACING_MILES).
        gap_threshold: Miles beyond which to insert fill waypoints (default GAP_FILL_THRESHOLD_MILES).
        fill_interval: Miles between fill waypoints in gaps (default WAYPOINT_INTERVAL_MILES).

    Returns:
        List of dicts: {"lat": float, "lon": float, "type": "rwis"|"fill",
                        "station": <station dict>|None, "along_route_miles": float}
    """
    from config import (RWIS_SNAP_RADIUS_MILES, RWIS_MIN_STATION_SPACING_MILES,
                        GAP_FILL_THRESHOLD_MILES, WAYPOINT_INTERVAL_MILES)
    if snap_radius is None:
        snap_radius = RWIS_SNAP_RADIUS_MILES
    if min_spacing is None:
        min_spacing = RWIS_MIN_STATION_SPACING_MILES
    if gap_threshold is None:
        gap_threshold = GAP_FILL_THRESHOLD_MILES
    if fill_interval is None:
        fill_interval = WAYPOINT_INTERVAL_MILES

    if len(points) <= 1:
        return [{"lat": points[0][0], "lon": points[0][1], "type": "fill",
                 "station": None, "along_route_miles": 0.0}]

    # Compute total route length
    cumulative_dists = [0.0]
    for i in range(1, len(points)):
        d = haversine_miles(points[i-1][0], points[i-1][1], points[i][0], points[i][1])
        cumulative_dists.append(cumulative_dists[-1] + d)
    total_route_miles = cumulative_dists[-1]

    # Match stations to route
    candidates = []
    for station in rwis_stations:
        loc = station.get("location", {})
        slat = loc.get("latitude")
        slon = loc.get("longitude")
        if slat is None or slon is None:
            continue
        dist_from_route, along_miles = find_closest_polyline_point(points, slat, slon)
        if dist_from_route <= snap_radius:
            candidates.append({
                "station": station,
                "lat": slat,
                "lon": slon,
                "along_route_miles": along_miles,
                "dist_from_route": dist_from_route,
            })

    # Sort by along-route position
    candidates.sort(key=lambda c: c["along_route_miles"])

    # Deduplicate: skip stations too close to previous
    station_waypoints = []
    for c in candidates:
        if station_waypoints:
            prev = station_waypoints[-1]
            if abs(c["along_route_miles"] - prev["along_route_miles"]) < min_spacing:
                continue
        station_waypoints.append(c)

    # Build final waypoint list with origin, stations, destination, and gap fills
    result = []

    # Origin
    origin = {"lat": points[0][0], "lon": points[0][1], "type": "fill",
              "station": None, "along_route_miles": 0.0}
    result.append(origin)

    # Insert station waypoints
    for sw in station_waypoints:
        result.append({
            "lat": sw["lat"], "lon": sw["lon"], "type": "rwis",
            "station": sw["station"], "along_route_miles": sw["along_route_miles"],
        })

    # Destination
    dest = {"lat": points[-1][0], "lon": points[-1][1], "type": "fill",
            "station": None, "along_route_miles": total_route_miles}
    result.append(dest)

    # Sort everything by along_route_miles
    result.sort(key=lambda w: w["along_route_miles"])

    # Fill gaps
    filled = []
    for i, wp in enumerate(result):
        filled.append(wp)
        if i < len(result) - 1:
            gap = result[i+1]["along_route_miles"] - wp["along_route_miles"]
            if gap > gap_threshold:
                # Insert fill waypoints at fill_interval spacing
                num_fills = int(gap / fill_interval)
                for f in range(1, num_fills + 1):
                    target_miles = wp["along_route_miles"] + f * fill_interval
                    if target_miles >= result[i+1]["along_route_miles"]:
                        break
                    # Find the polyline point closest to target_miles
                    fill_pt = _interpolate_along_route(points, cumulative_dists, target_miles)
                    filled.append({
                        "lat": fill_pt[0], "lon": fill_pt[1], "type": "fill",
                        "station": None, "along_route_miles": target_miles,
                    })

    # Re-sort after filling
    filled.sort(key=lambda w: w["along_route_miles"])
    return filled


def _interpolate_along_route(points, cumulative_dists, target_miles):
    """Find the polyline point at a given distance along the route."""
    for i in range(1, len(points)):
        if cumulative_dists[i] >= target_miles:
            return points[i]
    return points[-1]


def _coords(wp):
    """Extract (lat, lon) from a waypoint dict or tuple."""
    if isinstance(wp, dict):
        return wp["lat"], wp["lon"]
    return wp[0], wp[1]


def compute_etas(waypoints, total_duration_seconds, departure):
    """Compute ETA at each waypoint assuming constant speed along the route."""
    if len(waypoints) <= 1:
        return [departure]

    distances = [0.0]
    for i in range(1, len(waypoints)):
        lat1, lon1 = _coords(waypoints[i-1])
        lat2, lon2 = _coords(waypoints[i])
        d = haversine_miles(lat1, lon1, lat2, lon2)
        distances.append(distances[-1] + d)

    total_distance = distances[-1]
    if total_distance == 0:
        return [departure] * len(waypoints)

    etas = []
    for d in distances:
        fraction = d / total_distance
        eta = departure + timedelta(seconds=total_duration_seconds * fraction)
        etas.append(eta)

    return etas


def compute_adjusted_etas(waypoints, total_duration_seconds, departure,
                          base_speed_factor=1.0, segment_slowdowns=None):
    """Compute ETAs with per-segment weather slowdowns.

    Args:
        waypoints: List of (lat, lon) tuples or dicts with lat/lon keys.
        total_duration_seconds: Base trip duration in seconds.
        departure: datetime of departure.
        base_speed_factor: Global speed multiplier (e.g. 0.5 = half speed).
        segment_slowdowns: Optional list of per-segment factors. segment_slowdowns[i]
            applies to travel from waypoints[i] to waypoints[i+1]. A value of 0.7
            means 70% of normal speed (segment takes 1/0.7 longer).

    Returns:
        List of datetime ETAs, one per waypoint.
    """
    if len(waypoints) <= 1:
        return [departure]

    # Step 1: Compute segment distances using haversine
    seg_distances = []
    for i in range(1, len(waypoints)):
        lat1, lon1 = _coords(waypoints[i - 1])
        lat2, lon2 = _coords(waypoints[i])
        seg_distances.append(haversine_miles(lat1, lon1, lat2, lon2))

    total_distance = sum(seg_distances)
    if total_distance == 0:
        return [departure] * len(waypoints)

    # Step 2: Compute base_time per segment proportional to distance
    base_times = [(d / total_distance) * total_duration_seconds for d in seg_distances]

    # Step 3: Compute adjusted_time per segment
    adjusted_times = []
    for i, bt in enumerate(base_times):
        seg_slow = segment_slowdowns[i] if segment_slowdowns is not None and i < len(segment_slowdowns) else 1.0
        effective = base_speed_factor * seg_slow
        effective = max(effective, 0.1)  # floor at 0.1 to prevent division by zero
        adjusted_times.append(bt / effective)

    # Step 4: Build ETAs from cumulative adjusted times
    etas = [departure]
    cumulative = 0.0
    for at in adjusted_times:
        cumulative += at
        etas.append(departure + timedelta(seconds=cumulative))

    return etas


async def fetch_route(origin, destination, departure_time):
    """Fetch route from Google Routes API."""
    url = "https://routes.googleapis.com/directions/v2:computeRoutes"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_API_KEY,
        "X-Goog-FieldMask": (
            "routes.polyline.encodedPolyline,"
            "routes.legs.steps.navigationInstruction,"
            "routes.legs.steps.localizedValues,"
            "routes.legs.steps.startLocation,"
            "routes.legs.steps.endLocation,"
            "routes.legs.duration,"
            "routes.legs.distanceMeters,"
            "routes.description"
        ),
    }
    body = {
        "origin": {"address": origin},
        "destination": {"address": destination},
        "travelMode": "DRIVE",
        "departureTime": departure_time,
        "routingPreference": "TRAFFIC_AWARE",
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=body, headers=headers) as resp:
            data = await resp.json()

    if "error" in data:
        msg = data["error"].get("message", str(data["error"]))
        raise ValueError(f"Routing API error: {msg}")
    if "routes" not in data or not data["routes"]:
        raise ValueError("No route found between those locations.")

    route = data["routes"][0]
    legs = route.get("legs", [])

    steps = []
    for leg in legs:
        for step in leg.get("steps", []):
            nav = step.get("navigationInstruction", {})
            steps.append({
                "instruction": nav.get("instructions", ""),
                "maneuver": nav.get("maneuver", ""),
                "start_location": step.get("startLocation", {}).get("latLng", {}),
                "end_location": step.get("endLocation", {}).get("latLng", {}),
            })

    total_duration_seconds = sum(
        int(leg["duration"].rstrip("s")) for leg in legs if "duration" in leg
    )
    total_distance_meters = sum(
        leg.get("distanceMeters", 0) for leg in legs
    )

    return {
        "polyline": route.get("polyline", {}).get("encodedPolyline", ""),
        "steps": steps,
        "total_distance_meters": total_distance_meters,
        "total_duration_seconds": total_duration_seconds,
        "summary": route.get("description", ""),
    }
