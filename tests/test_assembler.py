from assembler import merge_weather, compute_severity, classify_rain_intensity, classify_fog_level, classify_light_level, build_segments
from datetime import datetime, timezone, timedelta

def test_merge_weather_averages_temperature():
    nws = {"temperature_f": 48, "precipitation_probability": 20, "wind_speed_mph": 10, "condition_text": "Cloudy"}
    openmeteo = {"temperature_f": 49, "precipitation_mm_hr": 0.5, "wind_speed_mph": 12, "wind_gusts_mph": 20, "visibility_miles": 8.0, "snow_depth_in": 0, "freezing_level_ft": 5000, "wind_direction_deg": 225}
    tomorrow = {"temperature_f": 47, "precipitation_probability": 30, "precipitation_type": "rain", "wind_speed_mph": 11, "wind_gusts_mph": 18, "visibility_miles": 10.0, "road_risk_score": 2, "road_risk_label": "Low"}

    merged = merge_weather(nws=nws, openmeteo=openmeteo, tomorrow=tomorrow)
    assert merged["temperature_f"] == 48.0
    assert merged["wind_speed_mph"] == 12
    assert merged["precipitation_probability"] == 30
    assert merged["condition_text"] == "Cloudy"
    assert merged["road_risk_score"] == 2

def test_compute_severity_green():
    weather = {"visibility_miles": 10, "wind_speed_mph": 10, "wind_gusts_mph": 15, "precipitation_mm_hr": 0.0}
    score, label = compute_severity(weather, road_conditions=None, alerts=[])
    assert label == "green"
    assert score <= 3

def test_compute_severity_yellow():
    weather = {"visibility_miles": 3.0, "wind_speed_mph": 25, "wind_gusts_mph": 35, "precipitation_mm_hr": 1.5}
    score, label = compute_severity(weather, road_conditions=None, alerts=[])
    assert label == "yellow"

def test_compute_severity_red():
    weather = {"visibility_miles": 0.5, "wind_speed_mph": 40, "wind_gusts_mph": 55, "precipitation_mm_hr": 6.0}
    score, label = compute_severity(weather, road_conditions=None, alerts=[])
    assert label == "red"

def test_classify_rain_intensity():
    assert classify_rain_intensity(0.0) == "none"
    assert classify_rain_intensity(0.3) == "light"
    assert classify_rain_intensity(2.0) == "moderate"
    assert classify_rain_intensity(5.0) == "heavy"

def test_classify_fog_level():
    assert classify_fog_level(10.0) == "none"
    assert classify_fog_level(3.0) == "patchy"
    assert classify_fog_level(0.5) == "dense"


def test_build_segments_includes_source_links():
    """Each segment should have source_links with NWS and Open-Meteo at minimum."""
    waypoints = [(37.5, -122.1), (38.0, -122.5)]
    from datetime import datetime, timezone
    etas = [
        datetime(2026, 2, 21, 6, 0, tzinfo=timezone.utc),
        datetime(2026, 2, 21, 7, 0, tzinfo=timezone.utc),
    ]
    steps = []
    weather_data = [
        {"temperature_f": 50, "wind_speed_mph": 10, "wind_gusts_mph": 15,
         "precipitation_mm_hr": 0, "visibility_miles": 10, "road_risk_score": 2},
        {"temperature_f": 48, "wind_speed_mph": 12, "wind_gusts_mph": 18,
         "precipitation_mm_hr": 0, "visibility_miles": 8},
    ]
    road_data = [None, None]
    alerts_by_segment = [[], []]

    segments = build_segments(waypoints, etas, steps, weather_data, road_data, alerts_by_segment)

    assert "source_links" in segments[0]
    links = segments[0]["source_links"]
    assert "nws" in links
    assert "37.5" in links["nws"]
    assert "-122.1" in links["nws"]
    assert "open_meteo" in links
    assert "caltrans" not in links  # no chain control or pavement data


def test_build_segments_source_links_includes_tomorrow_when_risk_present():
    """Tomorrow.io link included when road_risk_score is present."""
    waypoints = [(37.5, -122.1)]
    from datetime import datetime, timezone
    etas = [datetime(2026, 2, 21, 6, 0, tzinfo=timezone.utc)]
    weather_data = [
        {"temperature_f": 50, "wind_speed_mph": 10, "wind_gusts_mph": 15,
         "precipitation_mm_hr": 0, "visibility_miles": 10,
         "road_risk_score": 3, "road_risk_label": "Moderate"},
    ]
    road_data = [None]
    alerts_by_segment = [[]]

    segments = build_segments(waypoints, etas, [], weather_data, road_data, alerts_by_segment)
    assert "tomorrow_io" in segments[0]["source_links"]


def test_build_segments_with_dict_waypoints_and_data_source():
    """build_segments should handle dict waypoints and include data_source field."""
    from datetime import datetime, timezone
    waypoints = [
        {"lat": 37.5, "lon": -122.1, "type": "fill", "station": None},
        {"lat": 38.0, "lon": -122.5, "type": "rwis", "station": {"location": {"locationName": "Echo Pass"}}},
    ]
    etas = [
        datetime(2026, 2, 21, 6, 0, tzinfo=timezone.utc),
        datetime(2026, 2, 21, 7, 0, tzinfo=timezone.utc),
    ]
    weather_data = [
        {"temperature_f": 50, "wind_speed_mph": 10, "wind_gusts_mph": 15,
         "precipitation_mm_hr": 0, "visibility_miles": 10},
        {"temperature_f": 48, "wind_speed_mph": 12, "wind_gusts_mph": 18,
         "precipitation_mm_hr": 0, "visibility_miles": 8},
    ]
    road_data = [None, None]
    alerts_by_segment = [[], []]
    segments = build_segments(waypoints, etas, [], weather_data, road_data, alerts_by_segment)
    assert segments[0]["data_source"] == "fill"
    assert segments[1]["data_source"] == "rwis"
    assert segments[1].get("station_name") == "Echo Pass"
    assert "station_name" not in segments[0]


def test_build_segments_source_links_includes_caltrans_when_chain_control():
    """Caltrans link included when chain_control data exists."""
    waypoints = [(37.5, -122.1)]
    from datetime import datetime, timezone
    etas = [datetime(2026, 2, 21, 6, 0, tzinfo=timezone.utc)]
    weather_data = [
        {"temperature_f": 50, "wind_speed_mph": 10, "wind_gusts_mph": 15,
         "precipitation_mm_hr": 0, "visibility_miles": 10},
    ]
    road_data = [None]
    alerts_by_segment = [[]]
    chain_controls = [{"highway": "80", "level": "R2", "district": 3,
                       "description": "Chains required"}]

    segments = build_segments(
        waypoints, etas,
        [{"instruction": "Continue on I-80", "start_location": {"lat": 37.5, "lng": -122.1}}],
        weather_data, road_data, alerts_by_segment,
        chain_controls=chain_controls,
    )
    assert "caltrans" in segments[0]["source_links"]


# ── classify_light_level tests ──────────────────────────────────────

def test_classify_light_level_day():
    """Noon is firmly daytime."""
    pst = timezone(timedelta(hours=-8))
    eta = datetime(2026, 2, 18, 12, 0, tzinfo=pst)
    sunrise = "2026-02-18T06:55"
    sunset = "2026-02-18T17:45"
    assert classify_light_level(eta, sunrise, sunset) == "day"


def test_classify_light_level_twilight_sunset():
    """15 minutes before sunset is twilight."""
    pst = timezone(timedelta(hours=-8))
    eta = datetime(2026, 2, 18, 17, 30, tzinfo=pst)
    sunrise = "2026-02-18T06:55"
    sunset = "2026-02-18T17:45"
    assert classify_light_level(eta, sunrise, sunset) == "twilight"


def test_classify_light_level_twilight_sunrise():
    """15 minutes before sunrise is twilight (within 30 min window)."""
    pst = timezone(timedelta(hours=-8))
    eta = datetime(2026, 2, 18, 6, 40, tzinfo=pst)
    sunrise = "2026-02-18T06:55"
    sunset = "2026-02-18T17:45"
    assert classify_light_level(eta, sunrise, sunset) == "twilight"


def test_classify_light_level_night():
    """8 PM is after sunset, so night."""
    pst = timezone(timedelta(hours=-8))
    eta = datetime(2026, 2, 18, 20, 0, tzinfo=pst)
    sunrise = "2026-02-18T06:55"
    sunset = "2026-02-18T17:45"
    assert classify_light_level(eta, sunrise, sunset) == "night"


def test_classify_light_level_no_data():
    """When sunrise/sunset are None, default to 'day'."""
    pst = timezone(timedelta(hours=-8))
    eta = datetime(2026, 2, 18, 20, 0, tzinfo=pst)
    assert classify_light_level(eta, None, None) == "day"
