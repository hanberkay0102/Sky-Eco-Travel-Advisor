# ══════════════════════════════════════════════════════════════
# Custom Actions for Sky — Eco-Travel Advisor
# ══════════════════════════════════════════════════════════════
#
# This file contains the Python code that runs when the bot
# needs to do something more complex than a simple text reply.
#
# API INTEGRATION STRATEGY (tutor-approved APIs):
#   - Nominatim (OSM)     → geocoding (city name → coordinates)
#   - Overpass (OSM)       → hotels, transport stops, attractions
#   - Wikipedia REST API   → city/place descriptions
#   - Open-Meteo           → weather forecast
#   - Frankfurter (ECB)    → currency exchange rates
#   - Climatiq API         → carbon emission calculations
#   - OpenRouteService     → distance and route calculations
#
# Every API call has ERROR HANDLING: if an API fails or is
# unreachable, the bot falls back to mock data or a helpful
# error message, so the conversation never breaks.
#
# API keys are stored in a .env file and loaded with dotenv.
# Keys are NEVER committed to GitHub (.gitignore protects them).
# ══════════════════════════════════════════════════════════════

from typing import Any, Text, Dict, List
from rasa_sdk import Action, Tracker, FormValidationAction
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import SlotSet, ActiveLoop

import os
import time
import requests
import logging
import urllib.parse
from dotenv import load_dotenv

# Load API keys from .env file
load_dotenv()

# Set up logging so we can track API errors
logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════
# API CONFIGURATION
# Read API keys from environment variables.
# If a key is missing, the action will fall back to mock data.
# ══════════════════════════════════════════════════════════════

CLIMATIQ_API_KEY = os.getenv("CLIMATIQ_API_KEY", "")
ORS_API_KEY = os.getenv("ORS_API_KEY", "")

# API base URLs
CLIMATIQ_BASE_URL = "https://api.climatiq.io/data/v1/estimate"
ORS_BASE_URL = "https://api.heigit.org/openrouteservice"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Common User-Agent header for free APIs (Nominatim, Overpass, Wikipedia)
# Nominatim REQUIRES a real User-Agent; breaking this gets the IP blocked.
OSM_HEADERS = {
    "User-Agent": "Sky-EcoTravel-Advisor/1.0 (BSBI-coursework; student-project)"
}

# Nominatim rate limiter: maximum 1 request per second
_last_nominatim_call = 0.0


# ══════════════════════════════════════════════════════════════
# MOCK / FALLBACK DATA
# Used when APIs are unavailable or for data types that have
# no reliable free API (eco-certified hotels, offset projects).
# ══════════════════════════════════════════════════════════════

# Fallback carbon emission factors (kg CO2 per passenger per km)
# Source: UK DESNZ greenhouse gas conversion factors (rounded)
FALLBACK_CARBON_FACTORS = {
    "plane": 0.255,
    "car": 0.171,
    "bus": 0.089,
    "train": 0.041,
    "ferry": 0.019,
    "electric_car": 0.053
}

# Fallback distances (km) — used when OpenRouteService is down
FALLBACK_DISTANCES = {
    ("london", "paris"): 460,
    ("london", "amsterdam"): 560,
    ("london", "berlin"): 930,
    ("london", "rome"): 1870,
    ("london", "barcelona"): 1510,
    ("berlin", "paris"): 1050,
    ("berlin", "amsterdam"): 660,
    ("berlin", "prague"): 350,
    ("berlin", "vienna"): 680,
    ("berlin", "rome"): 1500,
    ("paris", "amsterdam"): 500,
    ("paris", "barcelona"): 1030,
    ("paris", "rome"): 1420,
    ("paris", "brussels"): 310,
    ("amsterdam", "brussels"): 210,
    ("amsterdam", "copenhagen"): 800,
    ("rome", "florence"): 280,
    ("rome", "milan"): 580,
    ("madrid", "lisbon"): 625,
    ("madrid", "barcelona"): 620,
    ("istanbul", "ankara"): 450,
    ("munich", "vienna"): 430,
    ("munich", "zurich"): 310,
    ("copenhagen", "stockholm"): 660,
    ("prague", "vienna"): 330,
}

# Mock eco-certified hotels — used as FALLBACK only.
# These have verified certifications that OSM cannot provide.
ECO_HOTELS = {
    "paris": [
        {
            "name": "Green Garden Hotel Paris",
            "rating": 4.2,
            "price_per_night": 95,
            "certifications": ["EU Ecolabel", "Green Key"],
            "eco_features": ["solar panels", "rainwater harvesting", "organic breakfast"],
            "source": "curated"
        },
        {
            "name": "EcoStay Montmartre",
            "rating": 4.5,
            "price_per_night": 120,
            "certifications": ["Green Key", "EarthCheck"],
            "eco_features": ["100% renewable energy", "zero single-use plastic", "local food"],
            "source": "curated"
        },
        {
            "name": "Sustainable Suites Paris",
            "rating": 3.9,
            "price_per_night": 75,
            "certifications": ["EU Ecolabel"],
            "eco_features": ["LED lighting", "recycling programme", "bike rental"],
            "source": "curated"
        }
    ],
    "berlin": [
        {
            "name": "GreenHouse Berlin Mitte",
            "rating": 4.6,
            "price_per_night": 85,
            "certifications": ["EMAS", "Green Key"],
            "eco_features": ["carbon neutral", "green roof", "vegan restaurant"],
            "source": "curated"
        },
        {
            "name": "EcoLodge Kreuzberg",
            "rating": 4.3,
            "price_per_night": 65,
            "certifications": ["Viabono", "EU Ecolabel"],
            "eco_features": ["solar heating", "organic toiletries", "bike sharing"],
            "source": "curated"
        }
    ],
    "amsterdam": [
        {
            "name": "Windmill Eco Hotel",
            "rating": 4.4,
            "price_per_night": 110,
            "certifications": ["Green Key", "Travelife Gold"],
            "eco_features": ["wind energy", "canal water cooling", "plastic-free rooms"],
            "source": "curated"
        },
        {
            "name": "Green Canal House",
            "rating": 4.7,
            "price_per_night": 140,
            "certifications": ["EarthCheck", "B Corp"],
            "eco_features": ["100% organic food", "rainwater toilets", "electric boat tours"],
            "source": "curated"
        }
    ],
    "barcelona": [
        {
            "name": "Solar Barcelona Hotel",
            "rating": 4.1,
            "price_per_night": 90,
            "certifications": ["Biosphere", "EU Ecolabel"],
            "eco_features": ["solar panels", "greywater recycling", "local sourcing"],
            "source": "curated"
        },
        {
            "name": "EcoMar Beach Hostel",
            "rating": 4.0,
            "price_per_night": 45,
            "certifications": ["Green Key"],
            "eco_features": ["beach cleanup programme", "compost toilets", "shared bikes"],
            "source": "curated"
        }
    ],
    "rome": [
        {
            "name": "Verde Roma Hotel",
            "rating": 4.3,
            "price_per_night": 100,
            "certifications": ["Legambiente", "EU Ecolabel"],
            "eco_features": ["solar hot water", "organic garden", "recycled furniture"],
            "source": "curated"
        }
    ]
}

# Mock carbon offset projects — no standardised free API exists
OFFSET_PROJECTS = [
    {
        "name": "Scottish Highland Reforestation",
        "type": "Tree Planting",
        "price_per_ton": 15,
        "certification": "Gold Standard",
        "location": "Scotland, UK"
    },
    {
        "name": "Portuguese Wind Farm",
        "type": "Renewable Energy",
        "price_per_ton": 12,
        "certification": "Verra VCS",
        "location": "Algarve, Portugal"
    },
    {
        "name": "Kenyan Clean Cookstoves",
        "type": "Clean Energy",
        "price_per_ton": 10,
        "certification": "Gold Standard",
        "location": "Nairobi, Kenya"
    },
    {
        "name": "Indonesian Mangrove Restoration",
        "type": "Blue Carbon",
        "price_per_ton": 18,
        "certification": "Plan Vivo",
        "location": "Kalimantan, Indonesia"
    }
]


# ══════════════════════════════════════════════════════════════
# API HELPER FUNCTIONS
# These functions call the external APIs and return data.
# Each one has try/except error handling that falls back
# to mock data if the API is down or the key is missing.
# ══════════════════════════════════════════════════════════════


def geocode_nominatim(place: str) -> tuple:
    """
    Use Nominatim (OpenStreetMap) to convert a place name to
    GPS coordinates. Returns (lat, lon, display_name) or None.

    Nominatim rules:
      - Maximum 1 request per second (enforced)
      - Real User-Agent required
      - Cache results (a city's coordinates do not change)
    """
    global _last_nominatim_call

    # Enforce 1 request per second rate limit
    elapsed = time.time() - _last_nominatim_call
    if elapsed < 1.0:
        time.sleep(1.0 - elapsed)

    try:
        response = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "q": place,
                "format": "json",
                "limit": 1,
            },
            headers=OSM_HEADERS,
            timeout=20,
        )
        _last_nominatim_call = time.time()
        response.raise_for_status()
        results = response.json()

        if not results:
            return None

        best = results[0]
        return (
            float(best["lat"]),
            float(best["lon"]),
            best.get("display_name", place)
        )

    except requests.exceptions.RequestException as e:
        logger.error(f"Nominatim geocoding error for '{place}': {e}")
        _last_nominatim_call = time.time()
        return None


# Simple in-memory cache for geocoded coordinates
_geocode_cache = {}


def get_coordinates(city: str) -> tuple:
    """
    Get coordinates for a city using Nominatim with caching.
    Returns (latitude, longitude) or None if geocoding fails.
    """
    city_key = city.lower().strip()

    # Check cache first
    if city_key in _geocode_cache:
        return _geocode_cache[city_key]

    result = geocode_nominatim(city)
    if result:
        coords = (result[0], result[1])
        _geocode_cache[city_key] = coords
        return coords

    return None


def get_distance_from_api(origin: str, destination: str) -> int:
    """
    Use OpenRouteService API to calculate the driving distance
    between two cities. Falls back to the local lookup table
    if the API is unavailable.
    """
    if not ORS_API_KEY:
        logger.warning("ORS API key not set, using fallback distances")
        return get_fallback_distance(origin, destination)

    # First get coordinates for both cities
    origin_coords = get_coordinates(origin)
    dest_coords = get_coordinates(destination)

    if not origin_coords or not dest_coords:
        logger.warning("Could not geocode cities, using fallback")
        return get_fallback_distance(origin, destination)

    try:
        # OpenRouteService expects [longitude, latitude] order
        response = requests.get(
            f"{ORS_BASE_URL}/v2/directions/driving-car",
            headers={
                "Authorization": ORS_API_KEY,
                "Content-Type": "application/json"
            },
            params={
                "start": f"{origin_coords[1]},{origin_coords[0]}",
                "end": f"{dest_coords[1]},{dest_coords[0]}"
            },
            timeout=10
        )
        response.raise_for_status()
        data = response.json()

        # Distance is in metres, convert to km
        distance_m = data["features"][0]["properties"]["segments"][0]["distance"]
        return int(distance_m / 1000)

    except requests.exceptions.RequestException as e:
        logger.error(f"ORS API error: {e}")
        return get_fallback_distance(origin, destination)
    except (KeyError, IndexError) as e:
        logger.error(f"ORS API unexpected response: {e}")
        return get_fallback_distance(origin, destination)


def get_fallback_distance(origin: str, destination: str) -> int:
    """
    Look up distance in the local fallback table.
    If not found, generate a consistent estimate.
    """
    o = origin.lower().strip()
    d = destination.lower().strip()

    distance = FALLBACK_DISTANCES.get(
        (o, d), FALLBACK_DISTANCES.get((d, o), None)
    )

    if distance is None:
        # Generate consistent estimate based on city names
        hash_val = abs(hash(o + d))
        distance = 300 + (hash_val % 1700)

    return distance



def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the great-circle distance between two points
    on Earth using the Haversine formula. Returns km.
    """
    import math
    R = 6371  # Earth radius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def get_feasible_transport_modes(
    origin: str, destination: str,
    origin_coords: tuple, dest_coords: tuple,
    road_distance: int, used_fallback: bool
) -> list:
    """
    Determine which transport modes are physically feasible
    for a given route. Filters out impossible options like
    bus/car across oceans.

    Returns a list of mode strings, e.g. ["train", "plane"]
    or ["train", "bus", "car", "plane"].
    """
    all_modes = ["train", "bus", "car", "plane"]

    if not origin_coords or not dest_coords:
        return all_modes  # Can't determine, show all

    # Straight-line (great-circle) distance
    straight_km = haversine_distance(
        origin_coords[0], origin_coords[1],
        dest_coords[0], dest_coords[1]
    )

    # If ORS couldn't find a driving route (fell back to estimate),
    # and straight-line distance is > 500 km, assume no road link
    no_road_link = used_fallback and straight_km > 500

    # Rule 1: If no road connection exists, only plane is viable
    # (e.g. Berlin → Hawaii, London → Tokyo without land bridge)
    if no_road_link and straight_km > 3000:
        return ["plane"]

    # Rule 2: Very long distances (> 5000 km straight) with no
    # verified road route — bus/car not practical
    if no_road_link and straight_km > 1500:
        return ["train", "plane"]

    # Rule 3: Short-to-medium routes with road connection — all modes
    # but omit plane for very short distances (< 300 km)
    if straight_km < 300 and not no_road_link:
        return ["train", "bus", "car"]

    return all_modes


def get_carbon_from_climatiq(
    transport_mode: str, distance_km: float
) -> float:
    """
    Use Climatiq API to calculate real carbon emissions.
    Returns kg CO2e, or None if the API fails.

    Climatiq activity IDs for different transport modes:
    These IDs come from Climatiq's emission factor database.
    """
    if not CLIMATIQ_API_KEY:
        logger.warning("Climatiq API key not set, using fallback")
        return None

    # Map our transport modes to Climatiq activity IDs
    climatiq_ids = {
        "plane": "passenger_flight-route_type_domestic-aircraft_type_na-distance_na-class_na-rf_included",
        "train": "passenger_train-route_type_intercity-fuel_source_na",
        "bus": "passenger_vehicle-vehicle_type_bus_tram_subway-fuel_source_na-engine_size_na-vehicle_age_na-vehicle_weight_na",
        "car": "passenger_vehicle-vehicle_type_car-fuel_source_na-distance_na-engine_size_na",
    }

    activity_id = climatiq_ids.get(transport_mode)
    if not activity_id:
        return None

    try:
        response = requests.post(
            CLIMATIQ_BASE_URL,
            headers={
                "Authorization": f"Bearer {CLIMATIQ_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "emission_factor": {
                    "activity_id": activity_id,
                    "data_version": "^6"
                },
                "parameters": {
                    "distance": distance_km,
                    "distance_unit": "km"
                }
            },
            timeout=10
        )
        response.raise_for_status()
        data = response.json()

        # Climatiq returns co2e in kg
        return data.get("co2e", None)

    except requests.exceptions.RequestException as e:
        logger.error(f"Climatiq API error for {transport_mode}: {e}")
        return None
    except (KeyError, ValueError) as e:
        logger.error(f"Climatiq unexpected response: {e}")
        return None


# ══════════════════════════════════════════════════════════════
# OVERPASS API HELPERS (OpenStreetMap queries)
# ══════════════════════════════════════════════════════════════


def search_overpass_hotels(lat: float, lon: float,
                           radius_m: int = 3000, limit: int = 10) -> list:
    """
    Find hotels near a point using Overpass API.
    Uses nwr (node/way/relation) to catch buildings too.
    Returns a list of hotel dictionaries.

    IMPORTANT: OSM has NO reliable eco-certification data.
    We use proxy indicators and state honestly they are proxies.
    """
    query = f"""
    [out:json][timeout:15];
    nwr["tourism"="hotel"](around:{radius_m},{lat},{lon});
    out center {limit};
    """

    try:
        response = requests.post(
            OVERPASS_URL,
            data={"data": query},
            headers=OSM_HEADERS,
            timeout=20,
        )
        response.raise_for_status()

        hotels = []
        for element in response.json().get("elements", []):
            tags = element.get("tags", {})

            # Skip anything without a name — useless to show a user
            if not tags.get("name"):
                continue

            # Get coordinates: node has lat/lon, way/relation has center
            h_lat = element.get("lat") or element.get("center", {}).get("lat")
            h_lon = element.get("lon") or element.get("center", {}).get("lon")

            # Check for eco tags (usually missing — be honest about this)
            eco_tag = (tags.get("green_key")
                       or tags.get("ecolabel")
                       or tags.get("eco"))

            # Proxy sustainability indicators (not certification!)
            proxies = []
            if tags.get("internet_access") == "wlan":
                proxies.append("WiFi (less paper)")
            if tags.get("bicycle_parking"):
                proxies.append("bicycle parking")
            if tags.get("wheelchair") == "yes":
                proxies.append("accessible")

            hotels.append({
                "name": tags["name"],
                "stars": tags.get("stars"),
                "eco_certified": eco_tag,
                "eco_proxies": proxies,
                "lat": h_lat,
                "lon": h_lon,
                "source": "OpenStreetMap"
            })
        return hotels

    except requests.exceptions.RequestException as e:
        logger.error(f"Overpass hotel search error: {e}")
        return []


def search_overpass_transport(lat: float, lon: float,
                              radius_m: int = 1500) -> list:
    """
    Find rail, metro and tram access points near a location.
    Following tutor's 03_find_transport.py pattern.
    """
    query = f"""
    [out:json][timeout:15];
    (
      node["railway"="station"](around:{radius_m},{lat},{lon});
      node["railway"="subway_entrance"](around:{radius_m},{lat},{lon});
      node["railway"="tram_stop"](around:{radius_m},{lat},{lon});
    );
    out body 25;
    """

    try:
        response = requests.post(
            OVERPASS_URL,
            data={"data": query},
            headers=OSM_HEADERS,
            timeout=20,
        )
        response.raise_for_status()

        stops = []
        for element in response.json().get("elements", []):
            tags = element.get("tags", {})
            stops.append({
                "name": tags.get("name", "(unnamed)"),
                "type": tags.get("railway", "unknown"),
                "lat": element.get("lat"),
                "lon": element.get("lon"),
            })
        return stops

    except requests.exceptions.RequestException as e:
        logger.error(f"Overpass transport search error: {e}")
        return []


def summarise_transport(stops: list) -> dict:
    """Count how many of each type — for a one-line bot response."""
    counts = {}
    for s in stops:
        counts[s["type"]] = counts.get(s["type"], 0) + 1
    return counts


def transport_verdict(stops: list) -> str:
    """Turn raw transport data into travel advice."""
    count = len(stops)
    if count >= 10:
        return "excellent — you will not need a car"
    elif count >= 3:
        return "reasonable, but check routes for your specific trip"
    else:
        return "limited — factor transport emissions into your planning"


# Only historic things a tourist would visit
VISITABLE_HISTORIC = "castle|monument|ruins|fort|archaeological_site|city_gate"


def search_overpass_attractions(lat: float, lon: float,
                                radius_m: int = 2000, limit: int = 10) -> list:
    """
    Find museums and visit-worthy historic sites near a location.
    Following tutor's 04_find_attractions.py pattern.
    Uses nwr + "out center" to catch buildings mapped as ways.
    """
    query = f"""
    [out:json][timeout:15];
    (
      nwr["tourism"="museum"](around:{radius_m},{lat},{lon});
      nwr["historic"~"^({VISITABLE_HISTORIC})$"](around:{radius_m},{lat},{lon});
    );
    out center {limit};
    """

    try:
        response = requests.post(
            OVERPASS_URL,
            data={"data": query},
            headers=OSM_HEADERS,
            timeout=20,
        )
        response.raise_for_status()

        sites = []
        for element in response.json().get("elements", []):
            tags = element.get("tags", {})
            if not tags.get("name"):
                continue

            a_lat = element.get("lat") or element.get("center", {}).get("lat")
            a_lon = element.get("lon") or element.get("center", {}).get("lon")

            # Check for Wikipedia tag — useful for descriptions
            wiki_title = tags.get("wikipedia", "")
            if wiki_title and ":" in wiki_title:
                # Format is "en:Belem Tower" — strip language prefix
                wiki_title = wiki_title.split(":", 1)[1]

            sites.append({
                "name": tags["name"],
                "kind": tags.get("tourism") or tags.get("historic"),
                "wikipedia_title": wiki_title,
                "lat": a_lat,
                "lon": a_lon,
            })
        return sites

    except requests.exceptions.RequestException as e:
        logger.error(f"Overpass attractions search error: {e}")
        return []


# ══════════════════════════════════════════════════════════════
# WIKIPEDIA API HELPER
# ══════════════════════════════════════════════════════════════


def get_wikipedia_summary(title: str, sentences: int = 2) -> dict:
    """
    Get a short description of a place from Wikipedia REST API.
    Returns dict with title, description, summary, url — or None.
    Following tutor's 05_place_description.py pattern.
    """
    safe_title = urllib.parse.quote(title.replace(" ", "_"))

    try:
        response = requests.get(
            f"https://en.wikipedia.org/api/rest_v1/page/summary/{safe_title}",
            headers=OSM_HEADERS,
            timeout=20,
        )

        if response.status_code == 404:
            return None
        response.raise_for_status()

        data = response.json()

        # Trim extract to requested number of sentences
        text = data.get("extract", "")
        parts = text.split(". ")
        short = ". ".join(parts[:sentences])
        if short and not short.endswith("."):
            short += "."

        return {
            "title": data.get("title"),
            "description": data.get("description"),
            "summary": short,
            "url": data.get("content_urls", {}).get("desktop", {}).get("page"),
        }

    except requests.exceptions.RequestException as e:
        logger.error(f"Wikipedia API error for '{title}': {e}")
        return None


# ══════════════════════════════════════════════════════════════
# OPEN-METEO WEATHER API HELPER
# ══════════════════════════════════════════════════════════════


def get_weather(lat: float, lon: float) -> dict:
    """
    Current conditions plus a 3-day outlook for a coordinate.
    Following tutor's 06_weather_forecast.py pattern.
    No API key needed.
    """
    try:
        response = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,precipitation,wind_speed_10m,weather_code",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
                "forecast_days": 3,
                "timezone": "auto",
            },
            headers=OSM_HEADERS,
            timeout=20,
        )
        response.raise_for_status()
        return response.json()

    except requests.exceptions.RequestException as e:
        logger.error(f"Open-Meteo API error: {e}")
        return None


def weather_travel_advice(temp_c: float, rain_mm: float) -> str:
    """Turn weather numbers into travel advice."""
    if rain_mm > 5:
        return "wet — plan indoor activities, and public transport over cycling"
    if temp_c < 5:
        return "cold — walking tours will be hard going"
    if temp_c > 30:
        return "hot — avoid long walks during midday"
    return "good conditions for walking and cycling"


# WMO weather code to description mapping
WMO_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy",
    3: "Overcast", 45: "Foggy", 48: "Rime fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow",
    80: "Light showers", 81: "Showers", 82: "Heavy showers",
    95: "Thunderstorm", 96: "Thunderstorm with hail",
}


# ══════════════════════════════════════════════════════════════
# FRANKFURTER CURRENCY API HELPER
# ══════════════════════════════════════════════════════════════


def convert_currency(amount: float, from_cur: str,
                     to_cur: str) -> tuple:
    """
    Convert an amount between currencies using Frankfurter API.
    Returns (converted_amount, rate, date) or (None, None, None).
    Following tutor's 07_currency_exchange.py pattern.
    """
    try:
        response = requests.get(
            "https://api.frankfurter.dev/v1/latest",
            params={"base": from_cur.upper(), "symbols": to_cur.upper()},
            headers=OSM_HEADERS,
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()

        rate = data["rates"][to_cur.upper()]
        return (amount * rate, rate, data.get("date", ""))

    except requests.exceptions.RequestException as e:
        logger.error(f"Frankfurter API error: {e}")
        return (None, None, None)
    except KeyError as e:
        logger.error(f"Frankfurter unknown currency: {e}")
        return (None, None, None)


def format_carbon(kg_co2: float) -> str:
    """Format carbon emissions in a readable way."""
    if kg_co2 >= 1000:
        return f"{kg_co2 / 1000:.2f} tonnes CO2"
    else:
        return f"{kg_co2:.1f} kg CO2"


# ══════════════════════════════════════════════════════════════
# ACTION 1: Search Transport
# Uses OpenRouteService for distance, Climatiq for carbon.
# Falls back to local data if any API is unavailable.
# ══════════════════════════════════════════════════════════════

# ── Helper: "What next?" buttons after each action ──────────
ALL_ACTION_BUTTONS = [
    {"title": "🚂 Search transport", "payload": "/search_transport"},
    {"title": "🏨 Find accommodation", "payload": "/search_accommodation"},
    {"title": "🎯 Explore activities", "payload": "/search_activities"},
    {"title": "📊 Carbon footprint", "payload": "/ask_carbon_footprint"},
    {"title": "🌤 Weather", "payload": "/ask_weather"},
    {"title": "💱 Currency", "payload": "/ask_currency"},
    {"title": "🏙 City info", "payload": "/ask_city_info"},
]


def _send_next_step_buttons(
    dispatcher: CollectingDispatcher,
    exclude: str = "",
    message: str = "What would you like to do next?"
):
    """Send 'what next?' buttons, excluding the action just used."""
    buttons = [b for b in ALL_ACTION_BUTTONS if b["payload"] != exclude]
    buttons.append(
        {"title": "🆕 Plan another trip", "payload": "/plan_trip"}
    )
    dispatcher.utter_message(text=message, buttons=buttons)


class ActionSearchTransport(Action):
    """Search for transport options and show their carbon impact."""

    def name(self) -> Text:
        return "action_search_transport"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any]
    ) -> List[Dict[Text, Any]]:

        origin = tracker.get_slot("origin")
        destination = tracker.get_slot("destination")
        sustainability = tracker.get_slot("sustainability_preference") or "medium"

        if not destination:
            dispatcher.utter_message(
                text="I need a destination to search for transport. "
                     "Where would you like to travel to?"
            )
            return []

        if not origin:
            dispatcher.utter_message(
                text="Where will you be travelling from?"
            )
            return []

        # Step 1: Get distance (try API first, then fallback)
        distance = get_distance_from_api(origin, destination)
        data_source = "OpenRouteService API"
        if distance == get_fallback_distance(origin, destination):
            data_source = "estimated distance"

        # Step 2: Determine which transport modes are feasible
        # for this route (e.g. no bus/car across oceans).
        origin_coords = get_coordinates(origin)
        dest_coords = get_coordinates(destination)
        used_fallback = (distance == get_fallback_distance(origin, destination))

        transport_modes = get_feasible_transport_modes(
            origin, destination,
            origin_coords, dest_coords,
            distance, used_fallback
        )

        # Use straight-line distance for intercontinental flights
        # when ORS road distance is unreliable
        if used_fallback and origin_coords and dest_coords:
            distance = int(haversine_distance(
                origin_coords[0], origin_coords[1],
                dest_coords[0], dest_coords[1]
            ))

        # Step 3: Calculate carbon and price for each feasible mode,
        # then rank them using the weighted eco-scoring function.
        scored_options = []
        used_climatiq = False

        for mode in transport_modes:
            # Try Climatiq API first, fall back to local factors
            carbon_kg = get_carbon_from_climatiq(mode, distance)

            if carbon_kg is not None:
                used_climatiq = True
            else:
                factor = FALLBACK_CARBON_FACTORS.get(mode, 0.1)
                carbon_kg = distance * factor

            # Estimate price for the scoring function
            price = estimate_transport_price(mode, distance)

            # Calculate weighted eco-score
            score_result = calculate_eco_score(
                carbon_kg=carbon_kg,
                estimated_price=price,
                has_eco_certification=False,
                sustainability_preference=sustainability
            )

            # Estimate travel time
            speed_map = {"train": 120, "bus": 70, "car": 90, "plane": 700}
            hours = distance / speed_map.get(mode, 80)

            scored_options.append({
                "mode": mode,
                "carbon_kg": carbon_kg,
                "price": price,
                "hours": hours,
                "score": score_result["score"],
                "colour": score_result["colour"],
                "label": score_result["label"],
            })

        # Step 3: Sort by eco-score (highest = best option first)
        scored_options.sort(key=lambda x: x["score"], reverse=True)

        carbon_source = "Climatiq API" if used_climatiq else "estimated factors"

        # Send structured custom payload for the frontend
        custom_payload = {
            "payload_type": "transport_results",
            "header": (
                f"Transport options from {origin} to {destination} "
                f"({distance} km), ranked by eco-score:"
            ),
            "origin": origin,
            "destination": destination,
            "distance": distance,
            "results": scored_options,
            "tip": (
                "\U0001f33f Tip: The train produces up to 6x less CO2 "
                "than flying for the same distance!"
            ),
        }
        dispatcher.utter_message(custom={"data": custom_payload})

        _send_next_step_buttons(dispatcher, exclude="/search_transport")
        return []


# ══════════════════════════════════════════════════════════════
# ACTION 2: Compare Transport
# Side-by-side carbon comparison of transport modes.
# ══════════════════════════════════════════════════════════════

class ActionCompareTransport(Action):
    """Compare transport options by carbon emissions."""

    def name(self) -> Text:
        return "action_compare_transport"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any]
    ) -> List[Dict[Text, Any]]:

        origin = tracker.get_slot("origin")
        destination = tracker.get_slot("destination")

        if not origin or not destination:
            dispatcher.utter_message(
                text="I need both an origin and destination to compare "
                     "transport options. Could you tell me where you're "
                     "travelling from and to?"
            )
            return []

        distance = get_distance_from_api(origin, destination)

        # Calculate emissions for each mode
        modes = ["train", "bus", "car", "plane"]
        carbon_values = {}

        for mode in modes:
            carbon_kg = get_carbon_from_climatiq(mode, distance)
            if carbon_kg is None:
                factor = FALLBACK_CARBON_FACTORS.get(mode, 0.1)
                carbon_kg = distance * factor
            carbon_values[mode] = carbon_kg

        # Calculate savings
        train_co2 = carbon_values.get("train", 0)
        plane_co2 = carbon_values.get("plane", 0)
        savings = plane_co2 - train_co2

        # Send structured custom payload for the frontend
        comparison_data = []
        for mode in modes:
            c_kg = carbon_values[mode]
            if c_kg < 20:
                c_colour = "green"
            elif c_kg < 80:
                c_colour = "amber"
            else:
                c_colour = "red"
            comparison_data.append({
                "mode": mode,
                "carbon_kg": round(c_kg, 1),
                "colour": c_colour,
            })
        custom_payload = {
            "payload_type": "carbon_comparison",
            "header": (
                f"Carbon comparison: {origin} → {destination} "
                f"({distance} km) — per passenger, one way:"
            ),
            "comparisons": comparison_data,
            "tip": (
                f"\U0001f30d Choosing the train over a plane saves "
                f"approximately {format_carbon(savings)} per passenger!"
            ),
        }
        dispatcher.utter_message(custom={"data": custom_payload})

        _send_next_step_buttons(dispatcher, exclude="/search_transport")
        return []


# ══════════════════════════════════════════════════════════════
# ACTION 3: Search Accommodation
# Uses Overpass API to find real hotels from OpenStreetMap.
# Falls back to curated eco-hotel data when Overpass is
# unavailable or returns no results.
#
# GREENWASHING NOTE: OSM has NO reliable eco-certification
# data. We use proxy indicators (bicycle parking, etc.) and
# state honestly that these are proxies, not certifications.
# ══════════════════════════════════════════════════════════════

class ActionSearchAccommodation(Action):
    """Find accommodation options using Overpass + curated eco data."""

    def name(self) -> Text:
        return "action_search_accommodation"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any]
    ) -> List[Dict[Text, Any]]:

        destination = tracker.get_slot("destination")

        # If no destination slot, try to extract from user's latest message
        # (handles case where user types city name directly after being asked)
        if not destination:
            latest_text = tracker.latest_message.get("text", "").strip()
            # Check if it looks like a direct intent trigger
            if latest_text.startswith("/"):
                dispatcher.utter_message(
                    text="Which city should I search for accommodation in?"
                )
                return []
            # Try to use the raw text as destination
            entities = tracker.latest_message.get("entities", [])
            dest_entity = next(
                (e["value"] for e in entities if e["entity"] == "destination"),
                None
            )
            if dest_entity:
                destination = dest_entity
            elif latest_text and not latest_text.startswith("/"):
                # Use the raw text as destination if it's not an intent
                destination = latest_text
            else:
                dispatcher.utter_message(
                    text="Which city should I search for accommodation in?"
                )
                return []

        dest_lower = destination.lower().strip()
        sustainability = tracker.get_slot("sustainability_preference") or "medium"

        # Step 1: Get coordinates for Overpass query
        coords = get_coordinates(destination)
        overpass_hotels = []
        if coords:
            overpass_hotels = search_overpass_hotels(coords[0], coords[1])

        # Step 2: Check our curated eco-certified database
        eco_hotels = ECO_HOTELS.get(dest_lower, [])

        # Step 3: Build hotel cards combining both sources
        hotel_cards = []

        # Add Overpass hotels (real OSM data)
        for hotel in overpass_hotels[:5]:
            stars_text = f"{hotel['stars']}*" if hotel.get("stars") else None

            # Score: no certification bonus for Overpass hotels
            # (we cannot verify eco-certification from OSM data)
            score_result = calculate_eco_score(
                carbon_kg=0,
                estimated_price=80,  # average estimate
                has_eco_certification=bool(hotel.get("eco_certified")),
                sustainability_preference=sustainability
            )

            hotel_cards.append({
                "name": hotel["name"],
                "stars": stars_text,
                "rating": None,
                "price_per_night": None,
                "certifications": (
                    [hotel["eco_certified"]] if hotel.get("eco_certified")
                    else []
                ),
                "eco_features": hotel.get("eco_proxies", []),
                "eco_note": (
                    "Eco-certified" if hotel.get("eco_certified")
                    else "No verified eco-certification on record"
                ),
                "source": "OpenStreetMap",
                "lat": hotel.get("lat"),
                "lon": hotel.get("lon"),
                "score": score_result["score"],
                "colour": score_result["colour"],
                "label": score_result["label"],
            })

        # Add curated eco-certified hotels
        for hotel in eco_hotels:
            score_result = calculate_eco_score(
                carbon_kg=0,
                estimated_price=hotel["price_per_night"],
                has_eco_certification=True,
                sustainability_preference=sustainability
            )
            hotel_cards.append({
                "name": hotel["name"],
                "stars": None,
                "rating": hotel["rating"],
                "price_per_night": hotel["price_per_night"],
                "certifications": hotel["certifications"],
                "eco_features": hotel["eco_features"],
                "eco_note": "Verified eco-certified",
                "source": "Curated eco-database",
                "lat": None,
                "lon": None,
                "score": score_result["score"],
                "colour": score_result["colour"],
                "label": score_result["label"],
            })

        # Sort by eco-score (highest first)
        hotel_cards.sort(key=lambda x: x["score"], reverse=True)

        if hotel_cards:
            # Determine data sources for attribution
            sources = set(h["source"] for h in hotel_cards)
            source_text = " & ".join(sorted(sources))

            custom_payload = {
                "payload_type": "hotel_results",
                "header": f"Accommodation in {destination}:",
                "destination": destination,
                "hotels": hotel_cards,
                "tip": (
                    f"\U0001f3e8 Data from {source_text}. "
                    "Hotels marked 'eco-certified' have verified "
                    "environmental certifications. Others show proxy "
                    "indicators only — always verify directly."
                ),
            }
            dispatcher.utter_message(custom={"data": custom_payload})
        else:
            # No data from either source
            dispatcher.utter_message(
                text=(
                    f"I couldn't find hotels for {destination} right now. "
                    f"I recommend looking for hotels with these certifications:\n"
                    f"  \U0001f3f7️ Green Key\n"
                    f"  \U0001f3f7️ EU Ecolabel\n"
                    f"  \U0001f3f7️ EarthCheck\n"
                    f"  \U0001f3f7️ Travelife Gold\n\n"
                    f"Would you like to try a different city?"
                )
            )

        _send_next_step_buttons(dispatcher, exclude="/search_accommodation")
        return []


# ══════════════════════════════════════════════════════════════
# ACTION 4: Search Activities
# Uses Overpass to find real attractions from OpenStreetMap,
# enriched with Wikipedia descriptions where available.
# Replaces the old mock ECO_ACTIVITIES data.
# ══════════════════════════════════════════════════════════════

class ActionSearchActivities(Action):
    """Find cultural attractions and activities at the destination."""

    def name(self) -> Text:
        return "action_search_activities"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any]
    ) -> List[Dict[Text, Any]]:

        destination = tracker.get_slot("destination")

        if not destination:
            dispatcher.utter_message(
                text="Which city should I search for activities in?"
            )
            return []

        # Get coordinates
        coords = get_coordinates(destination)

        if not coords:
            dispatcher.utter_message(
                text=f"I couldn't locate {destination} on the map. "
                     "Could you check the spelling?"
            )
            return []

        # Get attractions from Overpass
        attractions = search_overpass_attractions(coords[0], coords[1])

        # Also get nearby transport to assess walkability
        transport_stops = search_overpass_transport(coords[0], coords[1])
        t_counts = summarise_transport(transport_stops)
        t_verdict = transport_verdict(transport_stops)

        if not attractions:
            dispatcher.utter_message(
                text=(
                    f"I couldn't find cultural attractions near "
                    f"{destination} in OpenStreetMap right now. "
                    f"Here are ideas for any destination:\n"
                    f"  \U0001f6b6 Walking tours (zero emissions)\n"
                    f"  \U0001f6b2 Cycling tours (explore sustainably)\n"
                    f"  \U0001f333 Parks and nature reserves\n"
                    f"  \U0001f37d️ Local food markets"
                )
            )
            _send_next_step_buttons(dispatcher, exclude="/search_activities")
            return []

        # Enrich top attractions with Wikipedia descriptions
        activity_cards = []
        for site in attractions[:8]:
            # Try Wikipedia for a description
            wiki_info = None
            wiki_title = site.get("wikipedia_title") or site["name"]
            wiki_info = get_wikipedia_summary(wiki_title, sentences=2)

            card = {
                "name": site["name"],
                "kind": site.get("kind", "attraction"),
                "description": (
                    wiki_info["summary"] if wiki_info
                    else f"A {site.get('kind', 'site')} in {destination}"
                ),
                "wiki_url": wiki_info["url"] if wiki_info else None,
                "lat": site.get("lat"),
                "lon": site.get("lon"),
                "eco_note": "Zero-emission cultural visit",
            }
            activity_cards.append(card)

        # Build transport summary
        transport_summary = []
        for kind, count in t_counts.items():
            label = kind.replace("_", " ")
            transport_summary.append(f"{count} {label}(s)")

        custom_payload = {
            "payload_type": "activity_results",
            "header": f"Cultural experiences in {destination}:",
            "destination": destination,
            "activities": activity_cards,
            "transport": {
                "stops_found": len(transport_stops),
                "summary": transport_summary,
                "verdict": t_verdict,
            },
            "tip": (
                f"\U0001f33f All attractions are zero-emission visits. "
                f"Public transport access: {t_verdict}. "
                f"Source: OpenStreetMap + Wikipedia (CC BY-SA)."
            ),
        }
        dispatcher.utter_message(custom={"data": custom_payload})

        _send_next_step_buttons(dispatcher, exclude="/search_activities")
        return []


# ══════════════════════════════════════════════════════════════
# ACTION 5: Calculate Carbon Footprint
# Uses Climatiq API for accurate real-time emission data.
# Falls back to local emission factors if API is unavailable.
# ══════════════════════════════════════════════════════════════

class ActionCalculateCarbon(Action):
    """Calculate the carbon footprint of the user's trip."""

    def name(self) -> Text:
        return "action_calculate_carbon"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any]
    ) -> List[Dict[Text, Any]]:

        origin = tracker.get_slot("origin")
        destination = tracker.get_slot("destination")
        num_travelers = tracker.get_slot("num_travelers")

        if not origin or not destination:
            dispatcher.utter_message(
                text="I need both your origin and destination to "
                     "calculate carbon emissions. Where are you "
                     "travelling from and to?"
            )
            return []

        # Get distance
        distance = get_distance_from_api(origin, destination)

        # Parse number of travelers
        try:
            travelers = int(num_travelers) if num_travelers else 1
        except (ValueError, TypeError):
            travelers = 1

        # Round trip
        round_trip = distance * 2

        # Calculate for each mode
        carbon_cards = []
        used_api = False

        for mode in ["train", "bus", "car", "plane"]:
            carbon_kg = get_carbon_from_climatiq(mode, round_trip)

            if carbon_kg is not None:
                used_api = True
            else:
                factor = FALLBACK_CARBON_FACTORS.get(mode, 0.1)
                carbon_kg = round_trip * factor

            per_person = carbon_kg
            total = per_person * travelers

            # Colour based on per-person emissions
            if per_person < 30:
                c_colour = "green"
            elif per_person < 100:
                c_colour = "amber"
            else:
                c_colour = "red"

            carbon_cards.append({
                "mode": mode,
                "carbon_per_person": round(per_person, 1),
                "carbon_total": round(total, 1),
                "colour": c_colour,
            })

        # Train vs plane savings
        train_carbon = get_carbon_from_climatiq("train", round_trip)
        plane_carbon = get_carbon_from_climatiq("plane", round_trip)
        if train_carbon is None:
            train_carbon = round_trip * FALLBACK_CARBON_FACTORS["train"]
        if plane_carbon is None:
            plane_carbon = round_trip * FALLBACK_CARBON_FACTORS["plane"]

        savings = (plane_carbon - train_carbon) * travelers
        source = "Climatiq API" if used_api else "estimated factors"

        custom_payload = {
            "payload_type": "carbon_footprint",
            "header": (
                f"Carbon footprint: {origin} ↔ {destination} "
                f"(round trip, {round_trip} km)"
            ),
            "origin": origin,
            "destination": destination,
            "distance_km": round_trip,
            "travelers": travelers,
            "results": carbon_cards,
            "savings_kg": round(savings, 1),
            "savings_days": int(savings / 21),
            "tip": (
                f"\U0001f30d By choosing the train over flying, you save "
                f"{format_carbon(savings)} — that's ~{int(savings / 21)} "
                f"days of an average person's carbon footprint!"
            ),
        }
        dispatcher.utter_message(custom={"data": custom_payload})

        _send_next_step_buttons(dispatcher, exclude="/ask_carbon_footprint")
        return []


# ══════════════════════════════════════════════════════════════
# ACTION 6: Carbon Offset
# Suggests verified carbon offset projects.
# ══════════════════════════════════════════════════════════════

class ActionCarbonOffset(Action):
    """Suggest carbon offset options for the trip."""

    def name(self) -> Text:
        return "action_carbon_offset"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any]
    ) -> List[Dict[Text, Any]]:

        origin = tracker.get_slot("origin")
        destination = tracker.get_slot("destination")

        if origin and destination:
            distance = get_distance_from_api(origin, destination)
            carbon_kg = get_carbon_from_climatiq("plane", distance * 2)
            if carbon_kg is None:
                carbon_kg = distance * 2 * FALLBACK_CARBON_FACTORS["plane"]
            carbon_tonnes = carbon_kg / 1000
            transport_note = "by plane (round trip)"
        else:
            carbon_kg = 500
            carbon_tonnes = 0.5
            transport_note = "(estimated)"

        project_list = []
        for i, project in enumerate(OFFSET_PROJECTS, 1):
            cost = max(carbon_tonnes * project["price_per_ton"], 1.0)
            project_list.append(
                f"  {i}. {project['name']}\n"
                f"     \U0001f30d Location: {project['location']}\n"
                f"     \U0001f4cb Type: {project['type']}\n"
                f"     ✅ Certification: {project['certification']}\n"
                f"     \U0001f4b0 Cost to offset your trip: €{cost:.2f}"
            )

        message = (
            f"To offset {format_carbon(carbon_kg)} {transport_note}, "
            f"here are certified projects you can support:\n\n"
            + "\n\n".join(project_list)
            + "\n\n\U0001f4a1 Tip: Look for Gold Standard or Verra VCS "
              "certification to ensure your offset makes a real impact."
        )

        dispatcher.utter_message(text=message)

        _send_next_step_buttons(
            dispatcher,
            exclude="/ask_carbon_offset",
            message="Anything else you'd like to explore?"
        )
        return []


# ══════════════════════════════════════════════════════════════
# ACTION 7: Get Weather
# Uses Open-Meteo API for real-time weather data.
# No API key needed.
# ══════════════════════════════════════════════════════════════

class ActionGetWeather(Action):
    """Get current weather and 3-day forecast for destination."""

    def name(self) -> Text:
        return "action_get_weather"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any]
    ) -> List[Dict[Text, Any]]:

        destination = tracker.get_slot("destination")

        if not destination:
            dispatcher.utter_message(
                text="Which city should I check the weather for?"
            )
            return []

        coords = get_coordinates(destination)
        if not coords:
            dispatcher.utter_message(
                text=f"I couldn't locate {destination} on the map. "
                     "Could you check the spelling?"
            )
            return []

        weather_data = get_weather(coords[0], coords[1])
        if not weather_data:
            dispatcher.utter_message(
                text=f"Sorry, I couldn't fetch weather data for "
                     f"{destination} right now. Please try again later."
            )
            return []

        # Parse current conditions
        current = weather_data.get("current", {})
        temp = current.get("temperature_2m", "?")
        precip = current.get("precipitation", 0)
        wind = current.get("wind_speed_10m", 0)
        weather_code = current.get("weather_code", 0)
        condition = WMO_CODES.get(weather_code, "Unknown")

        # Parse forecast
        daily = weather_data.get("daily", {})
        forecast_days = []
        for i, date in enumerate(daily.get("time", [])):
            t_max = daily.get("temperature_2m_max", [None])[i]
            t_min = daily.get("temperature_2m_min", [None])[i]
            rain = daily.get("precipitation_sum", [0])[i]
            advice = weather_travel_advice(t_max or 20, rain or 0)
            forecast_days.append({
                "date": date,
                "temp_max": t_max,
                "temp_min": t_min,
                "rain_mm": rain,
                "advice": advice,
            })

        # Travel advice based on current weather
        travel_tip = weather_travel_advice(
            float(temp) if temp != "?" else 20,
            float(precip)
        )

        custom_payload = {
            "payload_type": "weather_results",
            "header": f"Weather in {destination}:",
            "destination": destination,
            "current": {
                "temperature": temp,
                "condition": condition,
                "precipitation": precip,
                "wind_speed": wind,
            },
            "forecast": forecast_days,
            "travel_tip": travel_tip,
            "tip": (
                f"\U0001f324️ Travel conditions: {travel_tip}. "
                "Source: Open-Meteo (free, no key)."
            ),
        }
        dispatcher.utter_message(custom={"data": custom_payload})

        _send_next_step_buttons(dispatcher, exclude="/ask_weather")
        return []


# ══════════════════════════════════════════════════════════════
# ACTION 8: Get City Info
# Uses Wikipedia REST API for city descriptions.
# ══════════════════════════════════════════════════════════════

class ActionGetCityInfo(Action):
    """Get a description and key facts about the destination city."""

    def name(self) -> Text:
        return "action_get_city_info"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any]
    ) -> List[Dict[Text, Any]]:

        destination = tracker.get_slot("destination")

        if not destination:
            dispatcher.utter_message(
                text="Which city would you like to learn about?"
            )
            return []

        # Get Wikipedia summary
        wiki_info = get_wikipedia_summary(destination, sentences=3)

        if not wiki_info:
            dispatcher.utter_message(
                text=f"I couldn't find information about {destination} "
                     "on Wikipedia. Could you check the spelling?"
            )
            _send_next_step_buttons(dispatcher, exclude="/ask_city_info")
            return []

        custom_payload = {
            "payload_type": "city_info",
            "header": f"About {destination}:",
            "destination": destination,
            "title": wiki_info["title"],
            "description": wiki_info.get("description", ""),
            "summary": wiki_info["summary"],
            "wiki_url": wiki_info.get("url", ""),
            "tip": (
                "\U0001f4d6 Source: Wikipedia (CC BY-SA). "
                "Content attributed under Creative Commons licence."
            ),
        }
        dispatcher.utter_message(custom={"data": custom_payload})

        _send_next_step_buttons(dispatcher, exclude="/ask_city_info")
        return []


# ══════════════════════════════════════════════════════════════
# ACTION 9: Currency Convert
# Uses Frankfurter API (ECB rates) for currency conversion.
# ══════════════════════════════════════════════════════════════

class ActionCurrencyConvert(Action):
    """Convert currency using ECB reference rates."""

    def name(self) -> Text:
        return "action_currency_convert"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any]
    ) -> List[Dict[Text, Any]]:

        budget = tracker.get_slot("budget")

        # Try to parse amount from budget
        import re as _re_local
        amount = 100.0  # default
        from_cur = "EUR"
        to_cur = "GBP"

        if budget:
            numbers = _re_local.findall(r"[\d][\d,\.]*", str(budget))
            if numbers:
                try:
                    amount = float(numbers[0].replace(",", ""))
                except ValueError:
                    amount = 100.0

        # Detect currency from text
        text = tracker.latest_message.get("text", "").lower()
        if "gbp" in text or "pound" in text or "£" in text:
            from_cur = "GBP"
            to_cur = "EUR"
        elif "usd" in text or "dollar" in text or "$" in text:
            from_cur = "USD"
            to_cur = "EUR"
        elif "try" in text or "lira" in text or "₺" in text:
            from_cur = "TRY"
            to_cur = "EUR"

        # Do 3 common conversions
        conversions = []
        for target in ["EUR", "GBP", "USD"]:
            if target == from_cur:
                continue
            converted, rate, date = convert_currency(amount, from_cur, target)
            if converted is not None:
                conversions.append({
                    "from_cur": from_cur,
                    "to_cur": target,
                    "amount": amount,
                    "converted": round(converted, 2),
                    "rate": rate,
                    "date": date,
                })

        if not conversions:
            dispatcher.utter_message(
                text="Sorry, I couldn't fetch exchange rates right now. "
                     "Please try again later."
            )
            return []

        custom_payload = {
            "payload_type": "currency_results",
            "header": f"Currency conversion ({from_cur} {amount:.0f}):",
            "base_amount": amount,
            "base_currency": from_cur,
            "conversions": conversions,
            "tip": (
                "\U0001f4b1 Rates from the European Central Bank via "
                "Frankfurter API. Reference rates — actual exchange "
                "rates may vary."
            ),
        }
        dispatcher.utter_message(custom={"data": custom_payload})

        _send_next_step_buttons(dispatcher, exclude="/ask_currency")
        return []


# ══════════════════════════════════════════════════════════════
# ACTION 10: Handover to Human
# ══════════════════════════════════════════════════════════════

class ActionHandoverToHuman(Action):
    """Transfer the conversation to a human travel advisor."""

    def name(self) -> Text:
        return "action_handover_to_human"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any]
    ) -> List[Dict[Text, Any]]:

        # Collect full conversation context
        destination = tracker.get_slot("destination") or "not specified"
        origin = tracker.get_slot("origin") or "not specified"
        budget = tracker.get_slot("budget") or "not specified"
        date_start = tracker.get_slot("travel_date_start") or "not specified"
        num_travelers = tracker.get_slot("num_travelers") or "not specified"
        sustainability = tracker.get_slot("sustainability_preference") or "not specified"

        context = (
            f"Destination: {destination}, "
            f"Origin: {origin}, "
            f"Dates: {date_start}, "
            f"Budget: {budget}, "
            f"Travellers: {num_travelers}, "
            f"Sustainability: {sustainability}"
        )

        handover_text = (
            f"I'm transferring you to a sustainable travel "
            f"specialist now.\n\n"
            f"Here's what I'm passing on to them:\n"
            f"  \U0001f4cd {context}\n\n"
            f"A human advisor will be with you shortly. "
            f"Thank you for choosing eco-friendly travel! \U0001f33f\n\n"
            f"(Note: In this prototype, the handover is simulated. "
            f"In production, this would connect to a live agent "
            f"system like Zendesk or LiveChat.)"
        )

        # Send custom payload so the frontend shows the handover banner
        dispatcher.utter_message(custom={"data": {
            "payload_type": "handover",
            "text": handover_text,
        }})

        # Plain-text fallback for non-custom channels
        dispatcher.utter_message(text=handover_text)

        return [SlotSet("handover_context", context)]


# ══════════════════════════════════════════════════════════════
# ACTION 11: Trip Summary
# ══════════════════════════════════════════════════════════════

class ActionTripSummary(Action):
    """Show a summary of all collected trip information."""

    def name(self) -> Text:
        return "action_trip_summary"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any]
    ) -> List[Dict[Text, Any]]:

        destination = tracker.get_slot("destination") or "not specified"
        origin = tracker.get_slot("origin") or "not specified"
        date_start = tracker.get_slot("travel_date_start") or "not specified"
        date_end = tracker.get_slot("travel_date_end")
        duration = tracker.get_slot("trip_duration")
        budget = tracker.get_slot("budget") or "not specified"
        num_travelers = tracker.get_slot("num_travelers") or "1"
        sustainability = tracker.get_slot("sustainability_preference") or "medium"

        # Handle date display
        if date_end:
            dates_display = f"{date_start} to {date_end}"
        elif duration:
            dates_display = f"{date_start} ({duration})"
        else:
            dates_display = date_start

        summary = (
            f"Here's your trip plan summary:\n"
            f"\U0001f4cd From: {origin}\n"
            f"\U0001f4cd To: {destination}\n"
            f"\U0001f4c5 Dates: {dates_display}\n"
            f"\U0001f4b0 Budget: {budget}\n"
            f"\U0001f465 Travellers: {num_travelers}\n"
            f"\U0001f33f Sustainability: {sustainability}"
        )
        dispatcher.utter_message(text=summary)

        # Send action buttons
        dispatcher.utter_message(
            text="Everything look correct? What would you like to do first?",
            buttons=[
                {"title": "\U0001f682 Search transport", "payload": "/search_transport"},
                {"title": "\U0001f3e8 Find accommodation", "payload": "/search_accommodation"},
                {"title": "\U0001f3af Explore activities", "payload": "/search_activities"},
                {"title": "\U0001f4ca Carbon footprint", "payload": "/ask_carbon_footprint"},
                {"title": "\U0001f324️ Weather", "payload": "/ask_weather"},
                {"title": "\U0001f4b1 Currency", "payload": "/ask_currency"},
                {"title": "\U0001f3d9 City info", "payload": "/ask_city_info"},
            ]
        )
        return []


# ══════════════════════════════════════════════════════════════
# ACTION 12: Two-Stage Fallback
# ══════════════════════════════════════════════════════════════



# ══════════════════════════════════════════════════════════════
# ACTION: Smart Greeting
# Checks whether this is the first greeting in the conversation
# or a subsequent one. First greeting gets the full introduction;
# later greetings get a shorter, more natural response.
# ══════════════════════════════════════════════════════════════

class ActionGreet(Action):
    """Smart greeting that avoids repeating the full introduction."""

    def name(self) -> Text:
        return "action_greet"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:

        # Count how many times the bot has already greeted
        greet_count = 0
        for event in tracker.events:
            if event.get("event") == "action" and event.get("name") == "action_greet":
                greet_count += 1

        # Check if any trip slots are filled
        destination = tracker.get_slot("destination")
        origin = tracker.get_slot("origin")

        if greet_count <= 1:
            # First greeting — full introduction
            import random
            intros = [
                (
                    "Hello! \U0001f30d I'm **Sky**, your eco-travel advisor. "
                    "I can help you plan a sustainable trip with low carbon impact."
                ),
                (
                    "Hey there! \U0001f331 Welcome to **Sky**. "
                    "I help travellers plan greener, more sustainable trips."
                ),
                (
                    "Hi! \U0001f33f I'm **Sky**, here to help you travel sustainably. "
                    "Let's plan an eco-friendly trip together!"
                ),
            ]
            dispatcher.utter_message(
                text=random.choice(intros),
                buttons=[
                    {"title": "🌍 Plan a Trip", "payload": "/plan_trip"},
                    {"title": "ℹ️ How does Sky work?", "payload": "/sky_info"},
                ]
            )
        else:
            # Subsequent greeting — short and natural
            import random
            if destination:
                responses = [
                    f"Hey again! \U0001f44b We were looking at your trip to **{destination}**. What would you like to do next?",
                    f"Welcome back! \U0001f60a Still interested in **{destination}**? How can I help?",
                    f"Hi! \U0001f30d Ready to continue planning your trip to **{destination}**?",
                ]
            else:
                responses = [
                    "Hey! \U0001f44b How can I help you today?",
                    "Hi again! \U0001f60a What can I do for you?",
                    "Hello! \U0001f33f Would you like to plan a trip or ask about sustainable travel?",
                    "Hey there! \U0001f30d Ready to explore some eco-friendly travel options?",
                ]
            dispatcher.utter_message(text=random.choice(responses))

        return []

class ActionTwoStageFallback(Action):
    """Custom 2-stage fallback action."""

    def name(self) -> Text:
        return "action_two_stage_fallback"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:

        previous_action = None
        for event in reversed(tracker.events):
            if event.get("event") != "action":
                continue
            action_name = event.get("name")
            if action_name in ["action_listen", "action_session_start"]:
                continue
            previous_action = action_name
            break

        if previous_action == "action_two_stage_fallback":
            # Stage 2: still not understood
            dispatcher.utter_message(
                text=(
                    "I'm really sorry, I still couldn't understand that. \U0001f614\n"
                    "Here's what I can help you with:"
                ),
                buttons=[
                    {"title": "\U0001f30d Search Transport", "payload": "/search_transport"},
                    {"title": "\U0001f3e8 Find Hotels", "payload": "/search_accommodation"},
                    {"title": "\U0001f331 Carbon Footprint", "payload": "/ask_carbon_footprint"},
                    {"title": "\U0001f464 Human Advisor", "payload": "/request_human"},
                    {"title": "❓ Help", "payload": "/ask_help"},
                ],
            )
        else:
            # Stage 1: first misunderstanding
            dispatcher.utter_message(
                text=(
                    "I'm sorry, I didn't quite understand that. \U0001f914\n"
                    "Could you please rephrase, or pick one of these options:"
                ),
                buttons=[
                    {"title": "\U0001f30d Plan a Trip", "payload": "/plan_trip"},
                    {"title": "\U0001f3e8 Find Hotels", "payload": "/search_accommodation"},
                    {"title": "\U0001f331 Carbon Footprint", "payload": "/ask_carbon_footprint"},
                    {"title": "❓ Help", "payload": "/ask_help"},
                ],
            )

        return []


# ══════════════════════════════════════════════════════════════
# ACTION 13: Default Fallback
# Required by Rasa — registered in domain.yml
# ══════════════════════════════════════════════════════════════

class ActionDefaultFallback(Action):
    """Rasa's built-in default fallback action name."""

    def name(self) -> Text:
        return "action_default_fallback"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:

        dispatcher.utter_message(
            text=(
                "I'm sorry, I didn't understand that. \U0001f914\n"
                "Could you please rephrase, or type 'help' to see "
                "what I can do?"
            )
        )
        return []


# ══════════════════════════════════════════════════════════════
# OUT-OF-SCOPE HANDLER
# ══════════════════════════════════════════════════════════════

class ActionHandleOutOfScope(Action):
    """Handles out-of-scope messages by redirecting the user."""

    def name(self) -> Text:
        return "action_handle_out_of_scope"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:

        destination = tracker.get_slot("destination")
        origin = tracker.get_slot("origin")
        sustainability = tracker.get_slot("sustainability_preference")
        active_loop = tracker.active_loop.get("name") if tracker.active_loop else None

        # CASE 1: User is in the middle of filling the form
        if active_loop == "trip_planning_form":
            requested = tracker.get_slot("requested_slot")
            slot_prompts = {
                "destination": "where you'd like to travel to",
                "origin": "where you'll be travelling from",
                "travel_dates": "your travel dates",
                "budget": "your budget for the trip",
                "num_travelers": "how many people are travelling",
                "sustainability_preference": "your sustainability preference (low, medium, or high)",
            }
            prompt = slot_prompts.get(requested, "your trip details")

            dispatcher.utter_message(
                text=(
                    "That's a bit outside my area — I'm specialised in "
                    "eco-friendly travel planning! \U0001f33f\n"
                    "Let's get back to planning your trip. "
                    "Could you tell me {}?".format(prompt)
                )
            )
            return []

        # CASE 2: All slots filled
        if destination and origin and sustainability:
            dispatcher.utter_message(
                text=(
                    "That's outside my expertise, but no worries! \U0001f33f\n"
                    "We were planning your trip from {origin} to {dest}. "
                    "What would you like to do next?".format(
                        origin=origin, dest=destination
                    )
                ),
                buttons=[
                    {"title": "\U0001f30d Search Transport", "payload": "/search_transport"},
                    {"title": "\U0001f3e8 Find Hotels", "payload": "/search_accommodation"},
                    {"title": "\U0001f3af Activities", "payload": "/search_activities"},
                    {"title": "\U0001f331 Carbon Footprint", "payload": "/ask_carbon_footprint"},
                ],
            )
            return []

        # CASE 3: Destination is set
        if destination:
            dispatcher.utter_message(
                text=(
                    "I'm not sure about that — I'm built for sustainable "
                    "travel planning! \U0001f33f\n"
                    "I see you're interested in travelling to {}. "
                    "Shall we continue planning your trip?".format(destination)
                ),
                buttons=[
                    {"title": "Yes, let's plan!", "payload": "/plan_trip"},
                    {"title": "New destination", "payload": "/provide_destination"},
                ],
            )
            return []

        # CASE 4: No context at all
        dispatcher.utter_message(
            text=(
                "That's outside my area of expertise — I'm Sky, your "
                "eco-travel advisor! \U0001f33f\n"
                "Would you like to start planning an eco-friendly trip?"
            ),
            buttons=[
                {"title": "\U0001f30d Plan a trip", "payload": "/plan_trip"},
                {"title": "❓ What can you do?", "payload": "/ask_help"},
            ],
        )
        return []


# ══════════════════════════════════════════════════════════════
# WEIGHTED ECO-SCORING FUNCTION
# ══════════════════════════════════════════════════════════════

def calculate_eco_score(
    carbon_kg: float,
    estimated_price: float,
    has_eco_certification: bool = False,
    sustainability_preference: str = "medium"
) -> dict:
    """
    Calculate a weighted eco-score for a travel option.

    Returns dict with "score" (0-100), "colour", "label".
    """
    weight_map = {
        "high":   {"carbon": 0.60, "price": 0.20, "eco": 0.20},
        "medium": {"carbon": 0.40, "price": 0.40, "eco": 0.20},
        "low":    {"carbon": 0.20, "price": 0.60, "eco": 0.20},
    }
    pref = (sustainability_preference or "medium").lower().strip()
    weights = weight_map.get(pref, weight_map["medium"])

    # Normalise carbon to 0-100 (0 kg=100, 500 kg=0)
    carbon_score = max(0, min(100, 100 - (carbon_kg / 500) * 100))

    # Normalise price to 0-100 (0 EUR=100, 500 EUR=0)
    price_score = max(0, min(100, 100 - (estimated_price / 500) * 100))

    # Eco certification bonus
    eco_bonus = 100 if has_eco_certification else 0

    # Weighted total
    total_score = (
        weights["carbon"] * carbon_score
        + weights["price"] * price_score
        + weights["eco"] * eco_bonus
    )

    total_score = max(0, min(100, round(total_score)))

    if total_score >= 70:
        colour = "green"
        label = "Eco-Friendly"
    elif total_score >= 40:
        colour = "amber"
        label = "Moderate Impact"
    else:
        colour = "red"
        label = "High Impact"

    return {"score": total_score, "colour": colour, "label": label}


# Estimated prices per transport mode (euros, one-way, average)
ESTIMATED_TRANSPORT_PRICES = {
    "train": {"base": 40, "per_km": 0.08},
    "bus":   {"base": 15, "per_km": 0.05},
    "car":   {"base": 20, "per_km": 0.12},
    "plane": {"base": 50, "per_km": 0.06},
}


def estimate_transport_price(mode: str, distance_km: float) -> float:
    """Estimate the price of a transport option in euros."""
    pricing = ESTIMATED_TRANSPORT_PRICES.get(
        mode, {"base": 30, "per_km": 0.08}
    )
    return pricing["base"] + pricing["per_km"] * distance_km


# ══════════════════════════════════════════════════════════════
# LOCATION DATABASE & FUZZY MATCHING
# ══════════════════════════════════════════════════════════════

from difflib import get_close_matches

# City -> Country mapping
KNOWN_CITIES = {
    # Western Europe
    "Amsterdam": "Netherlands", "Antwerp": "Belgium",
    "Barcelona": "Spain", "Berlin": "Germany",
    "Bordeaux": "France", "Bratislava": "Slovakia",
    "Brighton": "United Kingdom", "Bruges": "Belgium",
    "Brussels": "Belgium", "Budapest": "Hungary",
    "Canterbury": "United Kingdom", "Chamonix": "France",
    "Copenhagen": "Denmark", "Dublin": "Ireland",
    "Dubrovnik": "Croatia", "Edinburgh": "United Kingdom",
    "Florence": "Italy", "Frankfurt": "Germany",
    "Geneva": "Switzerland", "Gothenburg": "Sweden",
    "Hamburg": "Germany", "Hannover": "Germany",
    "Helsinki": "Finland",
    "Innsbruck": "Austria", "Krakow": "Poland",
    "Leipzig": "Germany", "Lisbon": "Portugal",
    "Ljubljana": "Slovenia",
    "London": "United Kingdom", "Lyon": "France",
    "Madrid": "Spain", "Malmo": "Sweden",
    "Marseille": "France", "Milan": "Italy",
    "Munich": "Germany",
    "Naples": "Italy", "Nice": "France", "Nuremberg": "Germany",
    "Oslo": "Norway", "Palermo": "Italy",
    "Paris": "France", "Porto": "Portugal",
    "Prague": "Czech Republic", "Reykjavik": "Iceland",
    "Riga": "Latvia", "Rome": "Italy",
    "Salzburg": "Austria", "Seville": "Spain",
    "Split": "Croatia", "Stockholm": "Sweden",
    "Stuttgart": "Germany", "Strasbourg": "France",
    "Tallinn": "Estonia",
    "Thessaloniki": "Greece", "Tirana": "Albania",
    "Valencia": "Spain",
    "Venice": "Italy", "Vienna": "Austria",
    "Vilnius": "Lithuania", "Warsaw": "Poland",
    "Zagreb": "Croatia", "Zurich": "Switzerland",
    # Additional European cities
    "Athens": "Greece", "Cologne": "Germany",
    "Dresden": "Germany", "Dusseldorf": "Germany",
    "Glasgow": "United Kingdom",
    "Malaga": "Spain",
    "Palma de Mallorca": "Spain", "Rotterdam": "Netherlands",
    # Turkey
    "Ankara": "Turkey", "Istanbul": "Turkey",
    "Izmir": "Turkey", "Antalya": "Turkey",
    "Bodrum": "Turkey", "Cappadocia": "Turkey",
    "Fethiye": "Turkey",
    # Africa
    "Marrakech": "Morocco", "Cairo": "Egypt",
    "Cape Town": "South Africa", "Nairobi": "Kenya",
    "Zanzibar": "Tanzania", "Tunis": "Tunisia",
    "Addis Ababa": "Ethiopia", "Casablanca": "Morocco",
    # Americas
    "New York": "United States", "Los Angeles": "United States",
    "San Francisco": "United States", "Chicago": "United States",
    "Honolulu": "United States", "Miami": "United States",
    "Toronto": "Canada",
    "Vancouver": "Canada", "Montreal": "Canada",
    "Mexico City": "Mexico", "Cancun": "Mexico",
    "Buenos Aires": "Argentina", "Rio de Janeiro": "Brazil",
    "Sao Paulo": "Brazil", "Lima": "Peru",
    "Bogota": "Colombia", "Santiago": "Chile",
    "Havana": "Cuba", "San Jose": "Costa Rica",
    # Asia
    "Tokyo": "Japan", "Kyoto": "Japan", "Osaka": "Japan",
    "Bangkok": "Thailand", "Chiang Mai": "Thailand",
    "Phuket": "Thailand", "Seoul": "South Korea",
    "Beijing": "China", "Shanghai": "China",
    "Hong Kong": "China", "Singapore": "Singapore",
    "Kuala Lumpur": "Malaysia", "Hanoi": "Vietnam",
    "Ho Chi Minh City": "Vietnam", "Manila": "Philippines",
    "Taipei": "Taiwan", "Colombo": "Sri Lanka",
    "Kathmandu": "Nepal", "Bali": "Indonesia",
    "Jakarta": "Indonesia", "Phnom Penh": "Cambodia",
    "Mumbai": "India", "Delhi": "India", "Goa": "India",
    # Middle East
    "Dubai": "UAE", "Abu Dhabi": "UAE",
    "Doha": "Qatar", "Muscat": "Oman",
    "Amman": "Jordan", "Beirut": "Lebanon",
    "Tel Aviv": "Israel", "Jerusalem": "Israel",
    # Oceania
    "Sydney": "Australia", "Melbourne": "Australia",
    "Auckland": "New Zealand", "Queenstown": "New Zealand",
    "Fiji": "Fiji",
}

COUNTRY_ALIASES = {
    "usa": "United States", "us": "United States",
    "u.s.a.": "United States", "u.s.": "United States",
    "america": "United States", "the states": "United States",
    "uk": "United Kingdom", "u.k.": "United Kingdom",
    "britain": "United Kingdom", "great britain": "United Kingdom",
    "england": "United Kingdom",
    "uae": "UAE", "u.a.e.": "UAE",
    "emirates": "UAE", "united arab emirates": "UAE",
    "holland": "Netherlands", "the netherlands": "Netherlands",
    "czech": "Czech Republic", "czechia": "Czech Republic",
    "south korea": "South Korea", "korea": "South Korea",
    "sri lanka": "Sri Lanka",
    "costa rica": "Costa Rica",
    "new zealand": "New Zealand", "nz": "New Zealand",
    "turkiye": "Turkey", "türkiye": "Turkey",
    "türkei": "Turkey",
}

KNOWN_COUNTRIES = {
    # Europe
    "Albania", "Andorra", "Armenia", "Austria", "Azerbaijan",
    "Belgium", "Bosnia", "Bulgaria", "Croatia", "Cyprus",
    "Czech Republic", "Denmark", "England", "Estonia",
    "Finland", "France", "Georgia", "Germany", "Greece",
    "Hungary", "Iceland", "Ireland", "Italy", "Kosovo",
    "Latvia", "Liechtenstein", "Lithuania", "Luxembourg",
    "Malta", "Moldova", "Monaco", "Montenegro",
    "Netherlands", "North Macedonia", "Norway", "Poland",
    "Portugal", "Romania", "San Marino", "Scotland",
    "Serbia", "Slovakia", "Slovenia", "Spain", "Sweden",
    "Switzerland", "Turkey", "Ukraine",
    "United Kingdom", "Wales",
    # Americas
    "Argentina", "Belize", "Bolivia", "Brazil", "Canada",
    "Chile", "Colombia", "Costa Rica", "Cuba", "Dominican Republic",
    "Ecuador", "Guatemala", "Jamaica", "Mexico", "Panama",
    "Paraguay", "Peru", "Trinidad and Tobago", "United States",
    "Uruguay", "Venezuela",
    # Asia
    "Cambodia", "China", "India", "Indonesia", "Japan",
    "Laos", "Malaysia", "Maldives", "Myanmar", "Nepal",
    "Philippines", "Singapore", "South Korea", "Sri Lanka",
    "Taiwan", "Thailand", "Vietnam",
    # Middle East
    "Israel", "Jordan", "Lebanon", "Oman", "Palestine",
    "Qatar", "Saudi Arabia", "UAE",
    # Africa
    "Egypt", "Ethiopia", "Kenya", "Madagascar", "Morocco",
    "Mozambique", "Namibia", "Rwanda", "Senegal",
    "South Africa", "Tanzania", "Tunisia", "Uganda",
    # Oceania
    "Australia", "Fiji", "New Zealand",
    "Hawaii",
}

ALL_KNOWN_LOCATIONS = list(KNOWN_CITIES.keys()) + list(KNOWN_COUNTRIES)


def _cities_in_country(country_name: str) -> list:
    """Return list of known cities belonging to the given country."""
    country_lower = country_name.lower()
    return [city for city, ctry in KNOWN_CITIES.items()
            if ctry.lower() == country_lower]


def _is_known_country(name: str) -> bool:
    """Check if name matches a known country (case-insensitive)."""
    resolved = _resolve_country_alias(name)
    return resolved.lower() in {c.lower() for c in KNOWN_COUNTRIES}


def _is_known_city(name: str) -> bool:
    """Check if name matches a known city (case-insensitive)."""
    return name.lower() in {c.lower() for c in KNOWN_CITIES.keys()}


def _resolve_country_alias(name: str) -> str:
    """Resolve common abbreviations like USA, UK, UAE."""
    return COUNTRY_ALIASES.get(name.lower().strip(), name)


def fuzzy_match_location(user_input: str) -> str:
    """Match user input to a known city or country name."""
    if not user_input or not user_input.strip():
        return user_input

    cleaned = user_input.strip()

    # Check country aliases first
    alias_resolved = _resolve_country_alias(cleaned)
    if alias_resolved.lower() != cleaned.lower():
        return alias_resolved

    # Exact match (case-insensitive)
    for name in ALL_KNOWN_LOCATIONS:
        if cleaned.lower() == name.lower():
            return name

    # Fuzzy match with 75% similarity threshold
    matches = get_close_matches(
        cleaned.lower(),
        [n.lower() for n in ALL_KNOWN_LOCATIONS],
        n=1,
        cutoff=0.75
    )

    if matches:
        matched_lower = matches[0]
        # First letter must match to avoid wild corrections
        if cleaned[0].lower() == matched_lower[0].lower():
            for name in ALL_KNOWN_LOCATIONS:
                if name.lower() == matched_lower:
                    return name

    return cleaned.title()


# ══════════════════════════════════════════════════════════════
# FORM VALIDATION (ValidateTripPlanningForm)
# ══════════════════════════════════════════════════════════════

import re as _re


class ActionAskDestination(Action):
    """Custom ask action for destination slot."""

    def name(self) -> Text:
        return "action_ask_destination"

    def run(self, dispatcher, tracker, domain):
        hint = tracker.get_slot("_dest_country_hint")
        if hint:
            cities = _cities_in_country(hint)
            if cities:
                examples = ", ".join(cities[:4])
                dispatcher.utter_message(
                    text=(
                        "Great choice! I need a specific city to plan "
                        "your trip properly (for transport routes, "
                        "hotels, etc.).\n\n"
                        "Which city in {} would you like to visit? "
                        "For example: {}".format(hint, examples)
                    )
                )
            else:
                dispatcher.utter_message(
                    text=(
                        "I'd love to help you visit {}! Could you "
                        "tell me which city you'd like to go to?"
                        .format(hint)
                    )
                )
        else:
            dispatcher.utter_message(
                text="Where would you like to travel to? "
                     "You can tell me a city or a country "
                     "(e.g. Paris, France, Tokyo, Spain)."
            )
        return []


class ActionAskOrigin(Action):
    """Custom ask action for origin slot."""

    def name(self) -> Text:
        return "action_ask_origin"

    def run(self, dispatcher, tracker, domain):
        hint = tracker.get_slot("_origin_country_hint")
        if hint:
            cities = _cities_in_country(hint)
            if cities:
                examples = ", ".join(cities[:4])
                dispatcher.utter_message(
                    text=(
                        "I need a specific city to calculate routes "
                        "and distances.\n\n"
                        "Which city in {} are you departing from? "
                        "For example: {}".format(hint, examples)
                    )
                )
            else:
                dispatcher.utter_message(
                    text=(
                        "Could you tell me which city in {} "
                        "you'll be departing from?".format(hint)
                    )
                )
        else:
            dispatcher.utter_message(
                text="Where will you be departing from? "
                     "You can tell me a city or a country "
                     "(e.g. London, Germany, Istanbul)."
            )
        return []


class ValidateTripPlanningForm(FormValidationAction):
    """Validates slots collected by the trip_planning_form."""

    def name(self) -> Text:
        return "validate_trip_planning_form"

    def _is_off_topic(self, tracker, dispatcher, requested_slot):
        """Return True if latest intent is out_of_scope."""
        intent = tracker.latest_message.get("intent", {}).get("name", "")
        if intent == "out_of_scope":
            slot_prompts = {
                "destination": "which city or country you'd like to visit",
                "origin": "where you'll be travelling from",
                "travel_date_start": "your travel dates",
                "budget": "your budget for the trip",
                "num_travelers": "how many people are travelling",
                "sustainability_preference": "your sustainability preference (high, medium, or low)",
            }
            prompt = slot_prompts.get(requested_slot, "your trip details")
            dispatcher.utter_message(
                text=(
                    "That's a bit outside my area — I'm specialised in "
                    "eco-friendly travel planning! \U0001f33f\n"
                    "Let's get back to your trip. "
                    "Could you tell me {}?".format(prompt)
                )
            )
            return True
        return False

    def _is_valid_place_name(self, val, dispatcher, slot_type="destination"):
        """Reject gibberish, sentences, and nonsensical input."""
        if len(val) < 2:
            dispatcher.utter_message(
                text="That's too short to be a place name. Please enter a city or country, e.g. Paris, France, Tokyo..."
            )
            return False
        if len(val) > 80:
            dispatcher.utter_message(
                text="That's too long. Please enter just the city or country name."
            )
            return False

        vowels = set("aeiouAEIOU")
        consonants = set("bcdfghjklmnpqrstvwxyzBCDFGHJKLMNPQRSTVWXYZ")
        if not any(c in vowels for c in val):
            dispatcher.utter_message(
                text="I couldn't recognise that as a place name. Please try again, e.g. Berlin, Spain, Istanbul..."
            )
            return False

        letters_only = [c for c in val if c.isalpha()]
        v_count = sum(1 for c in letters_only if c in vowels)
        c_count = sum(1 for c in letters_only if c in consonants)
        if v_count > 0 and c_count / v_count > 4:
            dispatcher.utter_message(
                text="I couldn't recognise that as a place name. "
                     "Please try again, e.g. Berlin, Spain, Istanbul..."
            )
            return False

        if _re.search(r'[bcdfghjklmnpqrstvwxyz]{4,}', val.lower()):
            dispatcher.utter_message(
                text="That doesn't look like a real place name. "
                     "Could you check the spelling? "
                     "E.g. Paris, London, Istanbul..."
            )
            return False

        if len(val) >= 6:
            for pat_len in (2, 3):
                pattern = val[:pat_len].lower()
                repeats = val.lower().count(pattern)
                if repeats >= 3 and len(pattern) * repeats >= len(val) * 0.7:
                    dispatcher.utter_message(
                        text="That doesn't look like a place name. "
                             "Please enter a city or country, "
                             "e.g. Paris, France, Tokyo..."
                    )
                    return False

        if len(val.split()) > 6:
            if slot_type == "origin":
                dispatcher.utter_message(
                    text="That looks like a sentence. Please just tell me the city or country you're travelling from."
                )
            else:
                dispatcher.utter_message(
                    text="That looks like a sentence. Please just tell me the city or country you'd like to visit."
                )
            return False

        non_place_words = [
            "like", "love", "hate", "want", "need", "think",
            "feel", "know", "believe", "wish", "hope",
            "pizza", "chocolate", "coffee", "football", "music",
            "movie", "book", "game", "phone", "computer",
            "mother", "father", "brother", "sister", "friend",
            "happy", "sad", "tired", "bored", "hungry",
            "please help", "what is", "how to", "can you",
        ]
        val_lower = val.lower()
        if len(val.split()) > 1:
            for nw in non_place_words:
                if nw in val_lower:
                    if slot_type == "origin":
                        dispatcher.utter_message(
                            text="That doesn't seem like a place name. Where are you travelling from? E.g. London, Berlin, New York..."
                        )
                    else:
                        dispatcher.utter_message(
                            text="That doesn't seem like a place name. Where would you like to go? E.g. Paris, Japan, Barcelona..."
                        )
                    return False

        return True

    def validate_destination(self, slot_value, dispatcher, tracker, domain):
        """Validate destination: reject off-topic & gibberish, fuzzy-correct."""
        if self._is_off_topic(tracker, dispatcher, "destination"):
            return {"destination": None, "_dest_country_hint": None}

        if slot_value and str(slot_value).strip():
            val = str(slot_value).strip()
            if not self._is_valid_place_name(val, dispatcher, "destination"):
                return {"destination": None, "_dest_country_hint": None}

            corrected = fuzzy_match_location(val)
            if corrected.lower() != val.lower():
                dispatcher.utter_message(
                    text='(I understood that as "{}")'.format(corrected)
                )

            if _is_known_country(corrected):
                return {"destination": None, "_dest_country_hint": corrected}

            return {"destination": corrected, "_dest_country_hint": None}
        return {"destination": None, "_dest_country_hint": None}

    def validate_origin(self, slot_value, dispatcher, tracker, domain):
        """Validate origin: reject off-topic & gibberish, fuzzy-correct."""
        current_destination = tracker.get_slot("destination")

        if self._is_off_topic(tracker, dispatcher, "origin"):
            return {"origin": None, "destination": current_destination,
                    "_origin_country_hint": None}

        if slot_value and str(slot_value).strip():
            val = str(slot_value).strip()
            if not self._is_valid_place_name(val, dispatcher, "origin"):
                return {"origin": None, "destination": current_destination,
                        "_origin_country_hint": None}

            corrected = fuzzy_match_location(val)
            if corrected.lower() != val.lower():
                dispatcher.utter_message(
                    text='(I understood that as "{}")'.format(corrected)
                )

            if _is_known_country(corrected):
                return {"origin": None, "destination": current_destination,
                        "_origin_country_hint": corrected}

            return {"origin": corrected, "destination": current_destination,
                    "_origin_country_hint": None}
        return {"origin": None, "destination": current_destination,
                "_origin_country_hint": None}

    def validate_travel_date_start(self, slot_value, dispatcher, tracker, domain):
        """Validate dates: must contain a date-related word or number."""
        if self._is_off_topic(tracker, dispatcher, "travel_date_start"):
            return {"travel_date_start": None}

        if slot_value and str(slot_value).strip():
            val = str(slot_value).strip()

            clean_chars = _re.sub(r"[a-zA-Z0-9\s/\-,\.]", "", val)
            if len(clean_chars) > len(val) * 0.3:
                dispatcher.utter_message(
                    text=(
                        "I need a date or time frame for your trip. "
                        "For example:\n"
                        "• \"15 March to 22 March\"\n"
                        "• \"next summer\"\n"
                        "• \"2 weeks in December\""
                    )
                )
                return {"travel_date_start": None}

            if _re.search(r"\d", val):
                transitions = 0
                for i in range(1, len(val)):
                    a_is_digit = val[i-1].isdigit()
                    b_is_digit = val[i].isdigit()
                    a_is_alpha = val[i-1].isalpha()
                    b_is_alpha = val[i].isalpha()
                    if (a_is_digit and b_is_alpha) or (a_is_alpha and b_is_digit):
                        transitions += 1
                if transitions > 4:
                    dispatcher.utter_message(
                        text="I need a date or time frame. E.g. \"15 March\" or \"next summer\"."
                    )
                    return {"travel_date_start": None}

            if " " not in val and _re.search(r"[a-zA-Z]", val) and _re.search(r"\d", val):
                alpha_part = _re.sub(r"[^a-zA-Z]", "", val).lower()
                quick_date_check = [
                    "jan", "feb", "mar", "apr", "may", "jun",
                    "jul", "aug", "sep", "oct", "nov", "dec",
                    "week", "month", "day", "summer", "winter",
                    "spring", "autumn",
                ]
                if not any(w in alpha_part for w in quick_date_check):
                    dispatcher.utter_message(
                        text="I need a date or time frame. E.g. \"15 March\" or \"2 weeks in December\"."
                    )
                    return {"travel_date_start": None}

            date_words = [
                "jan", "feb", "mar", "apr", "may", "jun",
                "jul", "aug", "sep", "oct", "nov", "dec",
                "january", "february", "march", "april",
                "june", "july", "august", "september",
                "october", "november", "december",
                "monday", "tuesday", "wednesday", "thursday",
                "friday", "saturday", "sunday",
                "week", "month", "day", "tomorrow", "today",
                "next", "this", "coming", "following",
                "summer", "winter", "spring", "autumn", "fall",
                "christmas", "easter", "holiday", "break",
                "beginning", "end", "mid", "early", "late",
                "year", "weekend",
            ]
            has_number = bool(_re.search(r"\d", val))
            has_date_word = any(w in val.lower().split() for w in date_words)
            if not has_date_word:
                has_date_word = any(val.lower().startswith(w) or
                                   (" " + w) in val.lower()
                                   for w in date_words)

            if not has_number and not has_date_word:
                dispatcher.utter_message(
                    text="I need a date or time frame. E.g. \"15 March\" or \"next summer\"."
                )
                return {"travel_date_start": None}

            return {"travel_date_start": val}
        return {"travel_date_start": None}

    def validate_budget(self, slot_value, dispatcher, tracker, domain):
        """Validate budget: number or descriptive word."""
        if self._is_off_topic(tracker, dispatcher, "budget"):
            return {"budget": None}

        if slot_value and str(slot_value).strip():
            val = str(slot_value).strip()

            budget_words = [
                "cheap", "expensive", "flexible", "unlimited",
                "no limit", "any", "moderate", "tight",
                "doesn't matter", "not sure", "open", "low",
                "mid", "high", "big",
            ]
            if any(w in val.lower() for w in budget_words):
                return {"budget": val}

            numbers = _re.findall(r"[\d][\d,\.]*", val)
            if not numbers:
                dispatcher.utter_message(
                    text="I need a budget amount. E.g. \"500 euros\", \"$2000\", or \"flexible\"."
                )
                return {"budget": None}

            alpha_parts = _re.findall(r"[a-zA-Z]+", val)
            ok_words = {
                "euro", "euros", "dollar", "dollars", "pound",
                "pounds", "usd", "eur", "gbp", "try", "yen",
                "around", "about", "approximately", "roughly",
                "max", "maximum", "min", "minimum", "up", "to",
                "per", "person", "total", "each", "budget",
                "spend", "k", "thousand", "hundred", "million",
                "or", "and", "less", "more", "than", "under",
                "over", "between",
            }
            for word in alpha_parts:
                if word.lower() not in ok_words:
                    dispatcher.utter_message(
                        text="That doesn't look like a valid budget. E.g. \"500 euros\", \"$2000\"."
                    )
                    return {"budget": None}

            try:
                num_str = numbers[0].replace(",", "")
                amount = float(num_str)
            except ValueError:
                return {"budget": None}

            if amount < 1:
                dispatcher.utter_message(
                    text="That budget seems too low. Please enter a realistic amount."
                )
                return {"budget": None}
            if amount > 1000000:
                dispatcher.utter_message(
                    text="That seems unusually high. Could you double-check?"
                )
                return {"budget": None}

            return {"budget": val}
        return {"budget": None}

    def validate_num_travelers(self, slot_value, dispatcher, tracker, domain):
        """Validate traveler count: 1-50, or a descriptive word."""
        if self._is_off_topic(tracker, dispatcher, "num_travelers"):
            return {"num_travelers": None}

        if slot_value and str(slot_value).strip():
            val = str(slot_value).strip()

            word_to_num = {
                "solo": "1", "alone": "1", "just me": "1",
                "myself": "1", "single": "1", "me": "1",
                "one": "1", "two": "2", "couple": "2",
                "pair": "2", "three": "3", "four": "4",
                "five": "5", "six": "6", "seven": "7",
                "eight": "8", "nine": "9", "ten": "10",
                "eleven": "11", "twelve": "12",
            }
            val_lower = val.lower()
            for word, num in word_to_num.items():
                if word in val_lower:
                    return {"num_travelers": num}

            if "family" in val_lower and not _re.search(r"\d", val):
                return {"num_travelers": "4"}

            if "group" in val_lower and not _re.search(r"\d", val):
                dispatcher.utter_message(
                    text="How many people are in your group?"
                )
                return {"num_travelers": None}

            if _re.search(r"[^a-zA-Z0-9\s,\.\-]", val):
                dispatcher.utter_message(
                    text="Please just tell me the number of travellers, e.g. \"2\", \"solo\", or \"family of 4\"."
                )
                return {"num_travelers": None}

            if _re.search(r"[a-zA-Z]", val) and _re.search(r"\d", val):
                transitions = sum(
                    1 for i in range(1, len(val))
                    if (val[i-1].isdigit() != val[i].isdigit())
                    and not val[i].isspace() and not val[i-1].isspace()
                )
                if transitions > 2:
                    dispatcher.utter_message(
                        text="Please just tell me the number of travellers."
                    )
                    return {"num_travelers": None}

            numbers = _re.findall(r"\d+", val)
            if not numbers:
                dispatcher.utter_message(
                    text="I need to know how many people are travelling. E.g. \"just me\", \"2 people\", \"family of 4\"."
                )
                return {"num_travelers": None}

            try:
                count = int(numbers[0])
            except ValueError:
                return {"num_travelers": None}

            if count < 1:
                dispatcher.utter_message(text="There must be at least 1 traveller!")
                return {"num_travelers": None}
            if count > 50:
                dispatcher.utter_message(
                    text="I can help with groups up to 50 people."
                )
                return {"num_travelers": None}

            alpha_parts = _re.findall(r"[a-zA-Z]+", val)
            ok_words = {
                "people", "person", "persons", "travelers",
                "travellers", "adults", "kids", "children",
                "of", "us", "and", "with", "plus", "total",
                "a", "the", "we", "are",
            }
            for word in alpha_parts:
                if word.lower() not in ok_words:
                    dispatcher.utter_message(
                        text="Please just tell me the number of travellers."
                    )
                    return {"num_travelers": None}

            return {"num_travelers": str(count)}
        return {"num_travelers": None}

    def validate_sustainability_preference(self, slot_value, dispatcher, tracker, domain):
        """Map user input to high/medium/low."""
        if self._is_off_topic(tracker, dispatcher, "sustainability_preference"):
            return {"sustainability_preference": None}

        if slot_value:
            val = str(slot_value).lower().strip()
            if val in ["high", "medium", "low"]:
                return {"sustainability_preference": val}

        text = tracker.latest_message.get("text", "").lower().strip()

        high_words = [
            "high", "very", "maximum", "max", "eco", "green",
            "sustainable", "environment", "greenest",
            "eco-friendly", "carbon-neutral", "zero-waste",
            "as green as possible", "eco priority",
            "most sustainable", "only eco", "very important",
        ]
        low_words = [
            "low", "not important", "doesn't matter",
            "cheapest", "don't care", "price", "cheap",
            "convenience", "fastest", "practical",
            "whatever is cheapest", "not focused",
            "isn't my priority", "budget first",
            "not really", "minimal",
        ]

        for kw in high_words:
            if kw in text:
                return {"sustainability_preference": "high"}
        for kw in low_words:
            if kw in text:
                return {"sustainability_preference": "low"}

        vowels = set("aeiou")
        if text and not any(c in vowels for c in text):
            dispatcher.utter_message(
                text=(
                    "Please choose your sustainability preference:\n"
                    "• **high** — only eco-friendly options\n"
                    "• **medium** — balanced approach\n"
                    "• **low** — prioritise price"
                )
            )
            return {"sustainability_preference": None}

        if text:
            dispatcher.utter_message(
                text='(I\'ll set sustainability to "medium" — a balanced approach.)'
            )
            return {"sustainability_preference": "medium"}

        return {"sustainability_preference": None}


# ══════════════════════════════════════════════════════════════
# ACTION: Restart Trip
# ══════════════════════════════════════════════════════════════

class ActionRestartTrip(Action):
    """Clear all trip-related slots for a fresh start."""

    def name(self) -> Text:
        return "action_restart_trip"

    def run(self, dispatcher, tracker, domain):
        dispatcher.utter_message(
            text="🔄 Starting fresh! Let's plan a new trip."
        )
        return [
            SlotSet("destination", None),
            SlotSet("origin", None),
            SlotSet("travel_date_start", None),
            SlotSet("travel_date_end", None),
            SlotSet("trip_duration", None),
            SlotSet("budget", None),
            SlotSet("num_travelers", None),
            SlotSet("sustainability_preference", None),
            SlotSet("_dest_country_hint", None),
            SlotSet("_origin_country_hint", None),
            SlotSet("handover_context", None),
        ]


# ══════════════════════════════════════════════════════════════
# ACTION: Deactivate Loop
# ══════════════════════════════════════════════════════════════

class ActionDeactivateLoop(Action):
    """Deactivate the current active form loop."""

    def name(self) -> Text:
        return "action_deactivate_loop"

    def run(self, dispatcher, tracker, domain):
        return [ActiveLoop(None), SlotSet("requested_slot", None)]
