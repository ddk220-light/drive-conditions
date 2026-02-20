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


from planner import compute_slider_range, fetch_raw_weather, resolve_weather_for_etas, build_slot_data

app = Flask(__name__)


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

        # Fetch RWIS stations and raw weather via a single session
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            rwis_stations = await fetch_rwis_stations(session=session)
            waypoints = build_station_aware_waypoints(points, rwis_stations)
            raw_weather = await fetch_raw_weather(waypoints, session, rwis_stations=rwis_stations)

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
