# tests/test_utils.py
from utils import c_to_f, kmh_to_mph, km_to_miles, m_to_miles, m_to_ft


def test_c_to_f():
    assert c_to_f(0) == 32.0
    assert c_to_f(100) == 212.0
    assert c_to_f(-40) == -40.0


def test_kmh_to_mph():
    assert abs(kmh_to_mph(100) - 62.1) < 0.1


def test_km_to_miles():
    assert abs(km_to_miles(1.0) - 0.6) < 0.1
    assert abs(km_to_miles(16.0) - 9.9) < 0.1


def test_m_to_miles():
    assert abs(m_to_miles(1609.344) - 1.0) < 0.1


def test_m_to_ft():
    assert abs(m_to_ft(1000) - 3281) < 1
