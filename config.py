import os
from dotenv import load_dotenv

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
TOMORROW_API_KEY = os.getenv("TOMORROW_API_KEY")

NWS_USER_AGENT = "drive-conditions/1.0 (contact@example.com)"

WAYPOINT_INTERVAL_MILES = 15
RWIS_MATCH_RADIUS_MILES = 15

CALTRANS_DISTRICTS = [1, 2, 3, 6, 7, 8, 9, 10, 11]
CALTRANS_RWIS_DISTRICTS = [2, 3, 6, 8, 9, 10]

CALTRANS_CC_URL = "https://cwwp2.dot.ca.gov/data/d{district}/cc/ccStatusD{district}.json"
CALTRANS_RWIS_URL = "https://cwwp2.dot.ca.gov/data/d{district}/rwis/rwisStatusD{district}.json"
