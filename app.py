# app.py
import asyncio
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from flask import Flask, request, jsonify, render_template

import config
from routing import fetch_route, decode_polyline, sample_waypoints, compute_etas
from weather_nws import fetch_nws_forecast, fetch_nws_alerts, find_forecast_for_time
from weather_openmeteo import fetch_openmeteo, find_data_for_time as find_openmeteo_for_time
from weather_tomorrow import fetch_tomorrow, find_data_for_time as find_tomorrow_for_time
from road_conditions import fetch_chain_controls, fetch_rwis_stations, match_rwis_to_waypoint
from assembler import merge_weather, build_segments


def alert_active_at(alert, eta):
    """Return True if alert is still active at the given ETA."""
    expires_str = alert.get("expires")
    if not expires_str:
        return True
    expires = datetime.fromisoformat(expires_str)
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires > eta


app = Flask(__name__)


async def fetch_all_weather(waypoints, etas):
    """Fetch weather from all 3 sources for all waypoints in parallel."""
    import aiohttp

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
        lats = [wp[0] for wp in waypoints]
        lons = [wp[1] for wp in waypoints]
        openmeteo_task = fetch_openmeteo(lats, lons, session=session)

        nws_tasks = [fetch_nws_forecast(wp[0], wp[1], session=session) for wp in waypoints]
        nws_alert_tasks = [fetch_nws_alerts(wp[0], wp[1], session=session) for wp in waypoints]
        tomorrow_tasks = [fetch_tomorrow(wp[0], wp[1], session=session) for wp in waypoints]

        cc_task = fetch_chain_controls(session=session)
        rwis_task = fetch_rwis_stations(session=session)

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
    rwis_stations = results[5] if not isinstance(results[5], Exception) else []

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
    if not isinstance(results[5], Exception) and rwis_stations:
        sources_set.add("Caltrans CWWP2")

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

        rwis_match = match_rwis_to_waypoint(rwis_stations, wp)
        road_data.append(rwis_match)

        seg_alerts = nws_alerts[i] if i < len(nws_alerts) else []
        seg_alerts = [a for a in seg_alerts if alert_active_at(a, eta)]
        alerts_by_segment.append(seg_alerts)

    sources = sorted(sources_set)
    return weather_data, road_data, alerts_by_segment, chain_controls, sources


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

    async def do_work():
        route = await fetch_route(origin, destination, departure.isoformat())

        points = decode_polyline(route["polyline"])
        waypoints = sample_waypoints(points)
        etas = compute_etas(waypoints, route["total_duration_seconds"], departure)

        weather_data, road_data, alerts_by_segment, chain_controls, sources = await fetch_all_weather(waypoints, etas)

        segments = build_segments(
            waypoints, etas, route["steps"],
            weather_data, road_data, alerts_by_segment,
            chain_controls=chain_controls,
        )

        all_alerts = []
        seen = set()
        for i, seg_alerts in enumerate(alerts_by_segment):
            for alert in seg_alerts:
                key = alert.get("headline", "")
                if key not in seen:
                    seen.add(key)
                    alert_with_segments = {**alert, "affected_segments": [i]}
                    all_alerts.append(alert_with_segments)
                else:
                    for a in all_alerts:
                        if a.get("headline") == key:
                            a["affected_segments"].append(i)

        total_miles = round(route["total_distance_meters"] / 1609.344, 1)
        total_minutes = round(route["total_duration_seconds"] / 60)
        arrival = departure + timedelta(seconds=route["total_duration_seconds"])

        return {
            "route": {
                "summary": route["summary"],
                "total_distance_miles": total_miles,
                "total_duration_minutes": total_minutes,
                "departure": departure.isoformat(),
                "arrival": arrival.isoformat(),
                "polyline": route["polyline"],
            },
            "segments": segments,
            "alerts": all_alerts,
            "sources": sources,
        }

    try:
        result = asyncio.run(do_work())
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(result)


@app.route("/")
def index():
    return render_template("index.html", google_api_key=config.GOOGLE_MAPS_JS_KEY)


if __name__ == "__main__":
    app.run(debug=True, port=5001)
