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


def compute_etas(waypoints, total_duration_seconds, departure):
    """Compute ETA at each waypoint assuming constant speed along the route."""
    if len(waypoints) <= 1:
        return [departure]

    distances = [0.0]
    for i in range(1, len(waypoints)):
        d = haversine_miles(waypoints[i-1][0], waypoints[i-1][1],
                           waypoints[i][0], waypoints[i][1])
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
