# utils.py — shared unit conversion helpers


def c_to_f(c):
    return round(c * 9 / 5 + 32, 1)


def kmh_to_mph(kmh):
    return round(kmh * 0.621371, 1)


def km_to_miles(km):
    return round(km * 0.621371, 1)


def m_to_miles(m):
    return round(m / 1609.344, 1)


def m_to_ft(m):
    return round(m * 3.28084)
