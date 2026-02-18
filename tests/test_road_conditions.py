# tests/test_road_conditions.py
from road_conditions import match_rwis_to_waypoint, parse_chain_control, match_chain_control_to_instruction

SAMPLE_RWIS_STATION = {
    "location": {"latitude": 38.80, "longitude": -120.03},
    "airTemperature": {"value": 35, "unit": "F"},
    "surfaceTemperature": {"value": 32, "unit": "F"},
    "surfaceStatus": "Wet",
    "visibility": {"value": 0.5, "unit": "mi"},
    "windSpeed": {"value": 25, "unit": "mph"},
    "precipitationType": "Rain",
}

def test_match_rwis_to_waypoint_nearby():
    stations = [SAMPLE_RWIS_STATION]
    waypoint = (38.81, -120.04)  # very close
    result = match_rwis_to_waypoint(stations, waypoint, radius_miles=15)
    assert result is not None
    assert result["pavement_status"] == "Wet"
    assert result["visibility_miles"] == 0.5

def test_match_rwis_to_waypoint_too_far():
    stations = [SAMPLE_RWIS_STATION]
    waypoint = (37.0, -122.0)  # ~130 miles away
    result = match_rwis_to_waypoint(stations, waypoint, radius_miles=15)
    assert result is None

def test_parse_chain_control():
    sample = {
        "statusDate": "2026-02-21T06:00:00",
        "highway": "80",
        "direction": "E",
        "controlStatus": "R1",
        "beginPostmile": 30.0,
        "endPostmile": 60.0,
        "description": "Chains required on I-80 Eastbound",
    }
    result = parse_chain_control(sample)
    assert result["highway"] == "80"
    assert result["level"] == "R1"
    assert result["description"] == "Chains required on I-80 Eastbound"


def test_match_chain_control_matching():
    controls = [
        {"highway": "80", "direction": "E", "level": "R1", "description": "Chains on I-80 E"},
        {"highway": "50", "direction": "E", "level": "R2", "description": "Chains on US-50 E"},
    ]
    result = match_chain_control_to_instruction(controls, "Continue on I-80 East")
    assert result is not None
    assert result["highway"] == "80"
    assert result["level"] == "R1"


def test_match_chain_control_no_match():
    controls = [
        {"highway": "80", "direction": "E", "level": "R1", "description": "Chains on I-80 E"},
    ]
    result = match_chain_control_to_instruction(controls, "Turn left on Main St")
    assert result is None


def test_match_chain_control_most_restrictive():
    controls = [
        {"highway": "80", "direction": "E", "level": "R1", "description": "R1 on I-80 E"},
        {"highway": "80", "direction": "W", "level": "R3", "description": "R3 on I-80 W"},
    ]
    result = match_chain_control_to_instruction(controls, "Merge onto I-80")
    assert result is not None
    assert result["level"] == "R3"  # most restrictive
