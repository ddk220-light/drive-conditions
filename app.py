# app.py
import asyncio
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from flask import Flask, request, jsonify, render_template

import config
from routing import fetch_route, decode_polyline, sample_waypoints, compute_etas, compute_adjusted_etas, build_station_aware_waypoints
from weather_nws import fetch_nws_forecast, fetch_nws_alerts, find_forecast_for_time
from weather_openmeteo import fetch_openmeteo, find_data_for_time as find_openmeteo_for_time
from weather_tomorrow import fetch_tomorrow, find_data_for_time as find_tomorrow_for_time
from road_conditions import fetch_chain_controls, fetch_rwis_stations, match_rwis_to_waypoint
from assembler import merge_weather, build_segments, compute_weather_slowdown, classify_light_level


def _wp_lat(wp):
    """Extract latitude from a waypoint (tuple or dict)."""
    return wp["lat"] if isinstance(wp, dict) else wp[0]


def _wp_lon(wp):
    """Extract longitude from a waypoint (tuple or dict)."""
    return wp["lon"] if isinstance(wp, dict) else wp[1]


def alert_active_at(alert, eta):
    """Return True if alert is still active at the given ETA."""
    expires_str = alert.get("expires")
    if not expires_str:
        return True
    expires = datetime.fromisoformat(expires_str)
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires > eta


def compute_slider_range(departure, now):
    """Compute hourly departure slots from max(now, departure-48h) to departure+48h."""
    range_start = max(now, departure - timedelta(hours=48))
    # Ceil to next hour
    if range_start.minute > 0 or range_start.second > 0:
        range_start = range_start.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    else:
        range_start = range_start.replace(minute=0, second=0, microsecond=0)

    range_end = departure + timedelta(hours=48)
    range_end = range_end.replace(minute=0, second=0, microsecond=0)

    slots = []
    current = range_start
    while current <= range_end:
        slots.append(current)
        current += timedelta(hours=1)
    return slots


app = Flask(__name__)


async def fetch_raw_weather(waypoints, rwis_stations=None):
    """Fetch raw weather data from all sources (no ETA lookup).

    Args:
        waypoints: list of (lat, lon) tuples or dicts with "lat"/"lon" keys.
        rwis_stations: optional pre-fetched RWIS station list. When provided,
            the function skips fetching RWIS data from the API.
    """
    import aiohttp

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
        lats = [_wp_lat(wp) for wp in waypoints]
        lons = [_wp_lon(wp) for wp in waypoints]
        openmeteo_task = fetch_openmeteo(lats, lons, session=session)

        nws_tasks = [fetch_nws_forecast(_wp_lat(wp), _wp_lon(wp), session=session) for wp in waypoints]
        nws_alert_tasks = [fetch_nws_alerts(_wp_lat(wp), _wp_lon(wp), session=session) for wp in waypoints]
        tomorrow_tasks = [fetch_tomorrow(_wp_lat(wp), _wp_lon(wp), session=session) for wp in waypoints]

        cc_task = fetch_chain_controls(session=session)

        # Only fetch RWIS from API if not provided externally
        if rwis_stations is None:
            rwis_task = fetch_rwis_stations(session=session)
        else:
            async def _return_stations():
                return rwis_stations
            rwis_task = _return_stations()

        results = await asyncio.gather(
            openmeteo_task,
            asyncio.gather(*nws_tasks),
            asyncio.gather(*nws_alert_tasks),
            asyncio.gather(*tomorrow_tasks),
            cc_task,
            rwis_task,
            return_exceptions=True,
        )

    openmeteo_results = results[0] if not isinstance(results[0], Exception) else [None] * len(waypoints)
    nws_results = results[1] if not isinstance(results[1], Exception) else [None] * len(waypoints)
    nws_alerts = results[2] if not isinstance(results[2], Exception) else [[] for _ in waypoints]
    tomorrow_results = results[3] if not isinstance(results[3], Exception) else [[] for _ in waypoints]
    chain_controls = results[4] if not isinstance(results[4], Exception) else []
    rwis_result = results[5] if not isinstance(results[5], Exception) else []

    # Track which sources actually returned data
    sources_set = set()
    if not isinstance(results[0], Exception) and any(r is not None for r in openmeteo_results):
        sources_set.add("Open-Meteo")
    if not isinstance(results[1], Exception) and any(r is not None for r in nws_results):
        sources_set.add("NWS")
    if not isinstance(results[3], Exception) and any(r for r in tomorrow_results):
        sources_set.add("Tomorrow.io")
    if not isinstance(results[4], Exception) and chain_controls:
        sources_set.add("Caltrans CWWP2")
    if not isinstance(results[5], Exception) and rwis_result:
        sources_set.add("Caltrans CWWP2")

    sources = sorted(sources_set)

    return {
        "openmeteo": openmeteo_results,
        "nws": nws_results,
        "nws_alerts": nws_alerts,
        "tomorrow": tomorrow_results,
        "chain_controls": chain_controls,
        "rwis_stations": rwis_result,
        "sources": sources,
    }


def resolve_weather_for_etas(raw, waypoints, etas):
    """Look up weather at specific ETAs from pre-fetched raw data."""
    openmeteo_results = raw["openmeteo"]
    nws_results = raw["nws"]
    nws_alerts = raw["nws_alerts"]
    tomorrow_results = raw["tomorrow"]
    chain_controls = raw["chain_controls"]
    rwis_stations = raw["rwis_stations"]
    sources = raw["sources"]

    weather_data = []
    road_data = []
    alerts_by_segment = []

    for i, (wp, eta) in enumerate(zip(waypoints, etas)):
        nws_parsed = None
        if nws_results[i]:
            nws_parsed = find_forecast_for_time(nws_results[i], eta)

        openmeteo_parsed = None
        if openmeteo_results and i < len(openmeteo_results) and openmeteo_results[i]:
            openmeteo_parsed = find_openmeteo_for_time(openmeteo_results[i], eta)

        tomorrow_parsed = None
        if tomorrow_results[i]:
            tomorrow_parsed = find_tomorrow_for_time(tomorrow_results[i], eta)

        merged = merge_weather(nws=nws_parsed, openmeteo=openmeteo_parsed, tomorrow=tomorrow_parsed)
        weather_data.append(merged)

        # RWIS matching: use tagged station directly when available,
        # otherwise fall back to nearest-station search
        if isinstance(wp, dict) and wp.get("type") == "rwis" and wp.get("station"):
            # Waypoint already tagged with its RWIS station -- match with
            # a large radius so the single-element list always matches.
            rwis_match = match_rwis_to_waypoint(
                [wp["station"]],
                (_wp_lat(wp), _wp_lon(wp)),
                radius_miles=9999,
            )
        else:
            wp_tuple = (_wp_lat(wp), _wp_lon(wp))
            rwis_match = match_rwis_to_waypoint(rwis_stations, wp_tuple)
        road_data.append(rwis_match)

        seg_alerts = nws_alerts[i] if i < len(nws_alerts) else []
        seg_alerts = [a for a in seg_alerts if alert_active_at(a, eta)]
        alerts_by_segment.append(seg_alerts)

    return weather_data, road_data, alerts_by_segment, chain_controls, sources


def build_slot_data(slot_departure, waypoints, route, raw_weather,
                    base_speed_factor=1.0, rest_stop_info=None, rest_duration_minutes=0):
    """Build segments + alerts for a single departure time using pre-fetched weather."""
    from weather_openmeteo import find_sun_times_for_date
    from rest_stops import apply_rest_stop_delays, insert_rest_stop_segments

    # 1. Initial ETAs with base speed
    initial_etas = compute_etas(
        waypoints, route["total_duration_seconds"], slot_departure)
    # Apply base speed: slower speed = longer trip
    if base_speed_factor < 1.0:
        scaled = route["total_duration_seconds"] / base_speed_factor
        initial_etas = compute_etas(waypoints, scaled, slot_departure)

    # 2. First weather resolve
    weather_data, road_data, alerts_by_segment, chain_controls, sources = \
        resolve_weather_for_etas(raw_weather, waypoints, initial_etas)

    # 3. Compute weather slowdowns per segment (N-1 slowdowns for N waypoints)
    openmeteo_results = raw_weather.get("openmeteo", [])
    slowdowns = []
    for i in range(len(weather_data) - 1):
        # Quick light level for slowdown calc
        om = openmeteo_results[i] if i < len(openmeteo_results) and openmeteo_results[i] else None
        sun = find_sun_times_for_date(om, initial_etas[i]) if om else None
        ll = classify_light_level(initial_etas[i], sun["sunrise"] if sun else None, sun["sunset"] if sun else None)
        slowdowns.append(compute_weather_slowdown(weather_data[i], ll))

    # 4. Adjusted ETAs
    adjusted_etas = compute_adjusted_etas(
        waypoints, route["total_duration_seconds"], slot_departure,
        base_speed_factor, slowdowns)

    # 5. Apply rest stop delays
    if rest_stop_info:
        rest_indices = [rs["after_segment_index"] for rs in rest_stop_info]
        final_etas = apply_rest_stop_delays(adjusted_etas, rest_indices, rest_duration_minutes)
    else:
        final_etas = adjusted_etas

    # 6. Second weather resolve with final ETAs
    weather_data, road_data, alerts_by_segment, chain_controls, sources = \
        resolve_weather_for_etas(raw_weather, waypoints, final_etas)

    # 7. Compute final light levels and sun times
    light_levels = []
    sun_times_list = []
    for i, eta in enumerate(final_etas):
        om = openmeteo_results[i] if i < len(openmeteo_results) and openmeteo_results[i] else None
        sun = find_sun_times_for_date(om, eta) if om else None
        sun_times_list.append(sun)
        if sun:
            light_levels.append(classify_light_level(eta, sun["sunrise"], sun["sunset"]))
        else:
            light_levels.append("day")

    # 8. Build segments
    segments = build_segments(
        waypoints, final_etas, route["steps"],
        weather_data, road_data, alerts_by_segment,
        chain_controls=chain_controls, light_levels=light_levels, sun_times=sun_times_list,
    )

    # 9. Insert rest stop pseudo-segments
    if rest_stop_info:
        segments = insert_rest_stop_segments(segments, rest_stop_info, rest_duration_minutes)

    # Deduplicate alerts
    all_alerts = []
    seen = set()
    for i, seg_alerts in enumerate(alerts_by_segment):
        for alert in seg_alerts:
            key = alert.get("headline", "")
            if key not in seen:
                seen.add(key)
                all_alerts.append({**alert, "affected_segments": [i]})
            else:
                for a in all_alerts:
                    if a.get("headline") == key:
                        a["affected_segments"].append(i)

    arrival = final_etas[-1]

    return {
        "segments": segments,
        "alerts": all_alerts,
        "departure": slot_departure.isoformat(),
        "arrival": arrival.isoformat(),
    }


async def fetch_all_weather(waypoints, etas):
    """Fetch weather from all sources and resolve for given ETAs."""
    raw = await fetch_raw_weather(waypoints)
    return resolve_weather_for_etas(raw, waypoints, etas)


@app.route("/api/route-weather")
def route_weather():
    origin = request.args.get("origin")
    destination = request.args.get("destination")
    departure_str = request.args.get("departure")

    if not origin or not destination or not departure_str:
        return jsonify({"error": "Missing required params: origin, destination, departure"}), 400

    if len(origin) > 500 or len(destination) > 500:
        return jsonify({"error": "origin/destination too long (max 500 chars)"}), 400

    try:
        departure = datetime.fromisoformat(departure_str)
        # If no timezone provided (e.g. from datetime-local input), assume Pacific
        if departure.tzinfo is None:
            departure = departure.replace(tzinfo=ZoneInfo("America/Los_Angeles"))
    except ValueError:
        return jsonify({"error": "Invalid departure format. Use ISO 8601."}), 400

    now = datetime.now(tz=timezone.utc)
    if departure < now - timedelta(minutes=5):
        return jsonify({"error": "Departure time must be in the future."}), 400

    speed_factor = max(0.5, min(1.0, float(request.args.get("speed_factor", "1.0"))))
    rest_enabled = request.args.get("rest_enabled", "false") == "true"
    rest_interval = max(30, min(180, int(request.args.get("rest_interval", "60"))))
    rest_duration = max(5, min(60, int(request.args.get("rest_duration", "20"))))

    async def do_work(speed_factor, rest_enabled, rest_interval, rest_duration):
        import aiohttp

        route = await fetch_route(origin, destination, departure.isoformat())
        points = decode_polyline(route["polyline"])

        # Fetch RWIS stations early so we can build station-aware waypoints
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            rwis_stations = await fetch_rwis_stations(session=session)

        waypoints = build_station_aware_waypoints(points, rwis_stations)

        raw_weather = await fetch_raw_weather(waypoints, rwis_stations=rwis_stations)

        # Compute rest stop locations once for selected departure
        rest_stop_info = None
        if rest_enabled:
            from rest_stops import compute_rest_stop_positions, fetch_rest_stop_places

            initial_etas = compute_etas(waypoints, route["total_duration_seconds"], departure)
            weather_data_init, _, _, _, _ = resolve_weather_for_etas(raw_weather, waypoints, initial_etas)
            slowdowns = [compute_weather_slowdown(weather_data_init[i])
                         for i in range(len(weather_data_init) - 1)]
            adjusted_etas = compute_adjusted_etas(
                waypoints, route["total_duration_seconds"], departure,
                speed_factor, slowdowns)
            positions = compute_rest_stop_positions(adjusted_etas, rest_interval)

            if positions:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                    rest_stop_info = await fetch_rest_stop_places(positions, waypoints, session)

        # Build selected slot
        selected = build_slot_data(departure, waypoints, route, raw_weather,
                                   speed_factor, rest_stop_info, rest_duration)

        # Build all slider slots
        now_local = datetime.now(tz=timezone.utc).astimezone(departure.tzinfo)
        slot_times = compute_slider_range(departure, now_local)
        slots = {}
        for slot_dep in slot_times:
            slots[slot_dep.isoformat()] = build_slot_data(
                slot_dep, waypoints, route, raw_weather,
                speed_factor, rest_stop_info, rest_duration)

        total_miles = round(route["total_distance_meters"] / 1609.344, 1)
        total_minutes = round(route["total_duration_seconds"] / 60)

        return {
            "route": {
                "summary": route["summary"],
                "total_distance_miles": total_miles,
                "total_duration_minutes": total_minutes,
                "departure": departure.isoformat(),
                "arrival": selected["arrival"],
                "polyline": route["polyline"],
            },
            "segments": selected["segments"],
            "alerts": selected["alerts"],
            "sources": raw_weather["sources"],
            "slots": slots,
            "slider_range": {
                "min": slot_times[0].isoformat(),
                "max": slot_times[-1].isoformat(),
                "step_hours": 1,
                "selected": departure.isoformat(),
            },
        }

    try:
        result = asyncio.run(do_work(speed_factor, rest_enabled, rest_interval, rest_duration))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(result)


@app.route("/")
def index():
    return render_template("index.html", google_api_key=config.GOOGLE_MAPS_JS_KEY)


if __name__ == "__main__":
    app.run(debug=True, port=5001)
