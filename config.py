import os
from dotenv import load_dotenv

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_MAPS_JS_KEY = os.getenv("GOOGLE_MAPS_JS_KEY", GOOGLE_API_KEY)
TOMORROW_API_KEY = os.getenv("TOMORROW_API_KEY")

NWS_USER_AGENT = "drive-conditions/1.0 (contact@example.com)"

WAYPOINT_INTERVAL_MILES = 15
RWIS_MATCH_RADIUS_MILES = 15
RWIS_SNAP_RADIUS_MILES = 15
RWIS_MIN_STATION_SPACING_MILES = 5
GAP_FILL_THRESHOLD_MILES = 30

CALTRANS_DISTRICTS = [1, 2, 3, 6, 7, 8, 9, 10, 11]
CALTRANS_RWIS_DISTRICTS = [2, 3, 6, 8, 9, 10]

CALTRANS_CC_URL = "https://cwwp2.dot.ca.gov/data/d{district}/cc/ccStatusD{district}.json"
CALTRANS_RWIS_URL = "https://cwwp2.dot.ca.gov/data/d{district}/rwis/rwisStatusD{district}.json"

# Severity scoring thresholds

# Visibility: (miles_less_than, score_penalty)
SEVERITY_VISIBILITY = [
    (0.25, 4),
    (1.0, 3),
    (3.0, 2),
    (5.0, 1),
]

# Wind: (mph_greater_than, score_penalty)
SEVERITY_WIND = [
    (45, 3),
    (35, 2.5),
    (25, 1.5),
    (20, 1),
]

# Precipitation: (mm_hr_greater_than, score_penalty)
SEVERITY_PRECIP = [
    (8.0, 3),
    (4.0, 2.5),
    (2.0, 1.5),
    (0.5, 1),
]
