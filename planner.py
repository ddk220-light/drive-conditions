# planner.py
import asyncio
from datetime import datetime, timezone, timedelta

from routing import compute_etas, compute_adjusted_etas
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


async def fetch_raw_weather(waypoints, session, rwis_stations=None):
    """Fetch raw weather data from all sources (no ETA lookup).

    Args:
        waypoints: list of (lat, lon) tuples or dicts with "lat"/"lon" keys.
        session: aiohttp.ClientSession
        rwis_stations: optional pre-fetched RWIS station list.
    """
    lats = [_wp_lat(wp) for wp in waypoints]
    lons = [_wp_lon(wp) for wp in waypoints]
    
    # Open-Meteo handles multiple coordinates in one batch request
    openmeteo_task = fetch_openmeteo(lats, lons, session=session)

    nws_tasks = [fetch_nws_forecast(*wp_tuple, session=session) for wp_tuple in zip(lats, lons)]
    nws_alert_tasks = [fetch_nws_alerts(*wp_tuple, session=session) for wp_tuple in zip(lats, lons)]

    # Tomorrow.io Spatial Sampling: limit to max 5 calls per route
    tomorrow_indices = []
    if len(waypoints) <= 5:
        tomorrow_indices = list(range(len(waypoints)))
    else:
        step = (len(waypoints) - 1) / 4.0
        tomorrow_indices = [int(round(i * step)) for i in range(5)]
    
    tomorrow_tasks_sampled = [
        fetch_tomorrow(lats[idx], lons[idx], session=session)
        for idx in tomorrow_indices
    ]

    cc_task = fetch_chain_controls(session=session)

    if rwis_stations is None:
        rwis_task = fetch_rwis_stations(session=session)
    else:
        async def _return_stations(): return rwis_stations
        rwis_task = _return_stations()

    results = await asyncio.gather(
        openmeteo_task,
        asyncio.gather(*nws_tasks, return_exceptions=True),
        asyncio.gather(*nws_alert_tasks, return_exceptions=True),
        asyncio.gather(*tomorrow_tasks_sampled, return_exceptions=True),
        cc_task,
        rwis_task,
        return_exceptions=True,
    )

    openmeteo_results = results[0] if not isinstance(results[0], Exception) else [None] * len(waypoints)
    nws_results = results[1] if not isinstance(results[1], Exception) else [None] * len(waypoints)
    nws_alerts = results[2] if not isinstance(results[2], Exception) else [[] for _ in waypoints]
    sampled_tomorrow = results[3] if not isinstance(results[3], Exception) else [[] for _ in tomorrow_indices]
    chain_controls = results[4] if not isinstance(results[4], Exception) else []
    rwis_result = results[5] if not isinstance(results[5], Exception) else []

    # Distribute sampled tomorrow.io results to all waypoints
    tomorrow_results = []
    for i in range(len(waypoints)):
        best_idx = min(tomorrow_indices, key=lambda idx: abs(idx - i))
        res_idx = tomorrow_indices.index(best_idx)
        res = sampled_tomorrow[res_idx]
        tomorrow_results.append(res if not isinstance(res, Exception) else [])

    # Clean NWS exceptions
    nws_results = [r if not isinstance(r, Exception) else None for r in nws_results]
    nws_alerts = [r if not isinstance(r, Exception) else [] for r in nws_alerts]

    # Track which sources actually returned data
    sources_set = set()
    if openmeteo_results and any(r is not None for r in openmeteo_results):
        sources_set.add("Open-Meteo")
    if nws_results and any(r is not None for r in nws_results):
        sources_set.add("NWS")
    if sampled_tomorrow and any(r and not isinstance(r, Exception) for r in sampled_tomorrow):
        sources_set.add("Tomorrow.io")
    if chain_controls:
        sources_set.add("Caltrans CWWP2")
    if rwis_result:
        sources_set.add("Caltrans CWWP2")

    return {
        "openmeteo": openmeteo_results,
        "nws": nws_results,
        "nws_alerts": nws_alerts,
        "tomorrow": tomorrow_results,
        "chain_controls": chain_controls,
        "rwis_stations": rwis_result,
        "sources": sorted(sources_set),
    }


def resolve_weather_for_etas(raw, waypoints, etas):
    """Look up weather at specific ETAs from pre-fetched raw data."""
    weather_data = []
    road_data = []
    alerts_by_segment = []

    for i, (wp, eta) in enumerate(zip(waypoints, etas)):
        nws_parsed = None
        if raw["nws"][i]:
            nws_parsed = find_forecast_for_time(raw["nws"][i], eta)

        openmeteo_parsed = None
        if raw["openmeteo"] and i < len(raw["openmeteo"]) and raw["openmeteo"][i]:
            openmeteo_parsed = find_openmeteo_for_time(raw["openmeteo"][i], eta)

        tomorrow_parsed = None
        if raw["tomorrow"][i]:
            tomorrow_parsed = find_tomorrow_for_time(raw["tomorrow"][i], eta)

        merged = merge_weather(nws=nws_parsed, openmeteo=openmeteo_parsed, tomorrow=tomorrow_parsed)
        weather_data.append(merged)

        # RWIS matching
        if isinstance(wp, dict) and wp.get("type") == "rwis" and wp.get("station"):
            rwis_match = match_rwis_to_waypoint([wp["station"]], (_wp_lat(wp), _wp_lon(wp)), radius_miles=9999)
        else:
            rwis_match = match_rwis_to_waypoint(raw["rwis_stations"], (_wp_lat(wp), _wp_lon(wp)))
        road_data.append(rwis_match)

        seg_alerts = raw["nws_alerts"][i] if i < len(raw["nws_alerts"]) else []
        seg_alerts = [a for a in seg_alerts if alert_active_at(a, eta)]
        alerts_by_segment.append(seg_alerts)

    return weather_data, road_data, alerts_by_segment, raw["chain_controls"], raw["sources"]


def build_slot_data(slot_departure, waypoints, route, raw_weather,
                    base_speed_factor=1.0, rest_stop_info=None, rest_duration_minutes=0):
    """Build segments + alerts for a single departure time using pre-fetched weather."""
    from weather_openmeteo import find_sun_times_for_date
    from rest_stops import apply_rest_stop_delays, insert_rest_stop_segments

    # 1. Initial ETAs with base speed
    scaled = route["total_duration_seconds"] / base_speed_factor
    initial_etas = compute_etas(waypoints, scaled, slot_departure)

    # 2. First weather resolve
    weather_data, road_data, alerts_by_segment, chain_controls, sources = \
        resolve_weather_for_etas(raw_weather, waypoints, initial_etas)

    # 3. Compute weather slowdowns
    openmeteo_results = raw_weather.get("openmeteo", [])
    slowdowns = []
    for i in range(len(weather_data) - 1):
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
        light_levels.append(classify_light_level(eta, sun["sunrise"] if sun else None, sun["sunset"] if sun else None))

    # 8. Build segments
    segments = build_segments(
        waypoints, final_etas, route["steps"],
        weather_data, road_data, alerts_by_segment,
        chain_controls=chain_controls, light_levels=light_levels, sun_times=sun_times_list,
    )

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

    return {
        "segments": segments,
        "alerts": all_alerts,
        "departure": slot_departure.isoformat(),
        "arrival": final_etas[-1].isoformat(),
    }
