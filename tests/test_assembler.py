from assembler import merge_weather, compute_severity, classify_rain_intensity, classify_fog_level

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
