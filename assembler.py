# assembler.py
from datetime import datetime
from routing import haversine_miles
from road_conditions import match_chain_control_to_instruction


def classify_rain_intensity(mm_hr):
    if mm_hr is None or mm_hr < 0.1:
        return "none"
    elif mm_hr < 0.5:
        return "light"
    elif mm_hr < 4.0:
        return "moderate"
    else:
        return "heavy"


def classify_fog_level(visibility_miles):
    if visibility_miles is None or visibility_miles > 5.0:
        return "none"
    elif visibility_miles > 1.0:
        return "patchy"
    else:
        return "dense"


def merge_weather(nws=None, openmeteo=None, tomorrow=None):
    """Merge weather data from up to 3 sources using design merge rules."""
    result = {}

    # Temperature: average of Open-Meteo and Tomorrow.io
    temps = []
    if openmeteo and openmeteo.get("temperature_f") is not None:
        temps.append(openmeteo["temperature_f"])
    if tomorrow and tomorrow.get("temperature_f") is not None:
        temps.append(tomorrow["temperature_f"])
    if nws and nws.get("temperature_f") is not None and not temps:
        temps.append(nws["temperature_f"])
    result["temperature_f"] = round(sum(temps) / len(temps), 1) if temps else None

    # Wind speed/gusts: max of all (conservative)
    winds = [s.get("wind_speed_mph", 0) for s in [nws, openmeteo, tomorrow] if s]
    result["wind_speed_mph"] = max(winds) if winds else 0
    gusts = [s.get("wind_gusts_mph", 0) for s in [openmeteo, tomorrow] if s and s.get("wind_gusts_mph")]
    result["wind_gusts_mph"] = max(gusts) if gusts else result["wind_speed_mph"]

    # Wind direction: from Open-Meteo
    result["wind_direction_deg"] = (openmeteo or {}).get("wind_direction_deg")

    # Precip probability: max (conservative)
    probs = [s.get("precipitation_probability", 0) for s in [nws, tomorrow] if s]
    result["precipitation_probability"] = max(probs) if probs else 0

    # Precip type: Tomorrow.io preferred
    result["precipitation_type"] = (tomorrow or {}).get("precipitation_type", "none")

    # Precip mm/hr: Open-Meteo
    result["precipitation_mm_hr"] = (openmeteo or {}).get("precipitation_mm_hr", 0)
    result["rain_intensity"] = classify_rain_intensity(result["precipitation_mm_hr"])

    # Visibility: min (conservative)
    vis = [s.get("visibility_miles") for s in [openmeteo, tomorrow] if s and s.get("visibility_miles") is not None]
    result["visibility_miles"] = min(vis) if vis else None
    result["fog_level"] = classify_fog_level(result["visibility_miles"])

    # Snow: Open-Meteo
    result["snow_depth_in"] = (openmeteo or {}).get("snow_depth_in", 0)
    result["freezing_level_ft"] = (openmeteo or {}).get("freezing_level_ft")

    # Condition text: NWS
    result["condition_text"] = (nws or {}).get("condition_text", (tomorrow or {}).get("weather_text", ""))

    # Road risk: Tomorrow.io
    result["road_risk_score"] = (tomorrow or {}).get("road_risk_score")
    result["road_risk_label"] = (tomorrow or {}).get("road_risk_label")

    return result


def compute_severity(weather, road_conditions=None, alerts=None):
    """Compute severity score (0-10) and label (green/yellow/red)."""
    score = 0
    alerts = alerts or []

    vis = weather.get("visibility_miles")
    wind = weather.get("wind_speed_mph", 0)
    gusts = weather.get("wind_gusts_mph", 0)
    precip = weather.get("precipitation_mm_hr", 0)

    # Visibility scoring
    if vis is not None:
        if vis < 0.25:
            score += 4
        elif vis < 1.0:
            score += 3
        elif vis < 3.0:
            score += 2
        elif vis < 5.0:
            score += 1

    # Wind scoring
    effective_wind = max(wind, gusts * 0.7) if gusts else wind
    if effective_wind > 45:
        score += 3
    elif effective_wind > 35:
        score += 2.5
    elif effective_wind >= 25:
        score += 1.5
    elif effective_wind > 20:
        score += 1

    # Precipitation scoring
    if precip > 8.0:
        score += 3
    elif precip > 4.0:
        score += 2.5
    elif precip > 2.0:
        score += 1.5
    elif precip > 0.5:
        score += 1

    # Road conditions
    if road_conditions:
        chain = road_conditions.get("chain_control")
        if chain:
            level = chain.get("level", "")
            if level == "R3":
                score += 3
            elif level == "R2":
                score += 2
            elif level == "R1":
                score += 1

        pavement = road_conditions.get("pavement_status", "")
        if pavement and pavement.lower() in ("ice", "snow"):
            score += 2
        elif pavement and pavement.lower() == "wet":
            score += 0.5

    # Alerts
    for alert in alerts:
        sev = alert.get("severity", "")
        if sev in ("extreme", "severe"):
            score += 2
        elif sev == "moderate":
            score += 1

    score = min(10, round(score))

    if score <= 3:
        return score, "green"
    elif score <= 6:
        return score, "yellow"
    else:
        return score, "red"


def build_source_links(lat, lon, weather, road_conditions):
    """Build dict of external source URLs for a segment."""
    links = {
        "nws": f"https://forecast.weather.gov/MapClick.php?lat={lat}&lon={lon}",
        "open_meteo": f"https://open-meteo.com/en/docs#latitude={lat}&longitude={lon}",
    }
    if weather.get("road_risk_score") is not None:
        links["tomorrow_io"] = "https://www.tomorrow.io/weather/"
    if road_conditions and (road_conditions.get("chain_control") or road_conditions.get("pavement_status")):
        links["caltrans"] = "https://roads.dot.ca.gov/"
    return links


def build_segments(waypoints, etas, route_steps, weather_data, road_data, alerts_by_segment,
                   chain_controls=None):
    """Assemble the final segments list for the API response."""
    segments = []
    cumulative_miles = 0.0

    for i, (wp, eta) in enumerate(zip(waypoints, etas)):
        if i > 0:
            cumulative_miles += haversine_miles(
                waypoints[i-1][0], waypoints[i-1][1], wp[0], wp[1]
            )

        weather = weather_data[i] if i < len(weather_data) else {}
        road = road_data[i] if i < len(road_data) else None
        seg_alerts = alerts_by_segment[i] if i < len(alerts_by_segment) else []

        # Find matching turn instruction
        instruction = ""
        if route_steps:
            best_step = None
            best_dist = float("inf")
            for step in route_steps:
                sloc = step.get("start_location", {})
                slat = sloc.get("latitude") or sloc.get("lat", 0)
                slng = sloc.get("longitude") or sloc.get("lng", 0)
                d = haversine_miles(wp[0], wp[1], slat, slng)
                if d < best_dist:
                    best_dist = d
                    best_step = step
            if best_step:
                instruction = best_step.get("instruction", "")

        # Match chain controls to this segment's instruction
        cc_match = match_chain_control_to_instruction(chain_controls, instruction)

        # Build road_conditions for severity: merge RWIS data + chain control
        road_for_severity = dict(road) if road else {}
        if cc_match:
            road_for_severity["chain_control"] = cc_match

        severity_score, severity_label = compute_severity(
            weather, road_for_severity or None, seg_alerts
        )

        segments.append({
            "index": i,
            "location": {
                "lat": round(wp[0], 5),
                "lng": round(wp[1], 5),
            },
            "mile_marker": round(cumulative_miles, 1),
            "eta": eta.isoformat(),
            "turn_instruction": instruction,
            "weather": weather,
            "road_conditions": {
                "chain_control": cc_match,
                "pavement_status": (road or {}).get("pavement_status"),
                "alerts": seg_alerts,
            },
            "severity_score": severity_score,
            "severity_label": severity_label,
            "source_links": build_source_links(
                round(wp[0], 5), round(wp[1], 5), weather, road_for_severity
            ),
        })

    return segments
