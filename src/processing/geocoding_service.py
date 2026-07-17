import os
import json
import urllib.request
import logging
from datetime import datetime, timezone
from src.storage.database import get_db

logger = logging.getLogger(__name__)

# Predefined centroids for ~80 common countries to resolve phone geocoding 100% offline
COUNTRY_CENTROIDS = {
    "IN": (20.5937, 78.9629, "India"),
    "US": (37.0902, -95.7129, "United States"),
    "RU": (61.5240, 105.3188, "Russia"),
    "CN": (35.8617, 104.1954, "China"),
    "GB": (55.3781, -3.4360, "United Kingdom"),
    "UK": (55.3781, -3.4360, "United Kingdom"),
    "CA": (56.1304, -106.3468, "Canada"),
    "AU": (-25.2744, 133.7751, "Australia"),
    "DE": (51.1657, 10.4515, "Germany"),
    "FR": (46.2276, 2.2137, "France"),
    "BR": (-14.2350, -51.9253, "Brazil"),
    "ZA": (-30.5595, 22.9375, "South Africa"),
    "AE": (23.4241, 53.8478, "United Arab Emirates"),
    "SG": (1.3521, 103.8198, "Singapore"),
    "PH": (12.8797, 121.7740, "Philippines"),
    "MY": (4.2105, 101.9758, "Malaysia"),
    "ID": (-0.7893, 113.9213, "Indonesia"),
    "TH": (15.8700, 100.9925, "Thailand"),
    "VN": (14.0583, 108.2772, "Vietnam"),
    "PK": (30.3753, 69.3451, "Pakistan"),
    "BD": (23.6850, 90.3563, "Bangladesh"),
    "UA": (48.3794, 31.1656, "Ukraine"),
    "PL": (51.9194, 19.1451, "Poland"),
    "NL": (52.1326, 5.2913, "Netherlands"),
    "IT": (41.8719, 12.5674, "Italy"),
    "ES": (40.4637, -3.7492, "Spain"),
    "TR": (38.9637, 35.2433, "Turkey"),
    "IR": (32.4279, 53.6880, "Iran"),
    "IQ": (33.2232, 43.6793, "Iraq"),
    "SA": (23.8859, 45.0792, "Saudi Arabia"),
    "EG": (26.8206, 30.8025, "Egypt"),
    "NG": (9.0820, 8.6753, "Nigeria"),
    "KE": (-1.2921, 36.8219, "Kenya"),
    "MX": (23.6345, -102.5528, "Mexico"),
    "CO": (4.5709, -74.2973, "Colombia"),
    "AR": (-38.4161, -63.6167, "Argentina"),
    "CL": (-35.6751, -71.5430, "Chile"),
    "PE": (-9.1900, -75.0152, "Peru"),
    "HK": (22.3964, 114.1095, "Hong Kong"),
    "TW": (23.6978, 120.9605, "Taiwan"),
    "JP": (36.2048, 138.2529, "Japan"),
    "KR": (35.9078, 127.7669, "South Korea"),
    "KP": (40.3399, 127.5101, "North Korea"),
    "LK": (7.8731, 80.7718, "Sri Lanka"),
    "NP": (28.3949, 84.1240, "Nepal"),
    "MM": (21.9162, 95.9560, "Myanmar"),
    "KH": (12.5657, 104.9910, "Cambodia"),
    "LA": (19.8563, 102.4955, "Laos"),
    "AF": (33.9391, 67.7100, "Afghanistan"),
    "KZ": (48.0196, 66.9237, "Kazakhstan"),
    "UZ": (41.3775, 64.5853, "Uzbekistan"),
    "SE": (60.1282, 18.6435, "Sweden"),
    "NO": (60.4720, 8.4689, "Norway"),
    "FI": (61.9241, 25.7482, "Finland"),
    "DK": (56.2639, 9.5018, "Denmark"),
    "CH": (46.8182, 8.2275, "Switzerland"),
    "AT": (47.5162, 14.5501, "Austria"),
    "BE": (50.5039, 4.4699, "Belgium"),
    "CZ": (49.8175, 15.4730, "Czechia"),
    "HU": (47.1625, 19.5033, "Hungary"),
    "RO": (45.9432, 24.9668, "Romania"),
    "GR": (39.0742, 21.8243, "Greece"),
    "PT": (39.3999, -8.2245, "Portugal"),
    "IE": (53.4129, -8.2439, "Ireland"),
    "NZ": (-40.9006, 174.8860, "New Zealand"),
    "IL": (31.0461, 34.8516, "Israel"),
    "JO": (30.5852, 36.2384, "Jordan"),
    "LB": (33.8547, 35.8623, "Lebanon"),
    "SY": (34.8021, 38.9968, "Syria"),
    "IS": (64.9631, -19.0208, "Iceland"),
    "MA": (31.7917, -7.0926, "Morocco"),
    "DZ": (28.0339, 1.6596, "Algeria"),
    "TN": (33.8869, 9.5375, "Tunisia"),
    "LY": (26.3351, 17.2283, "Libya"),
    "SD": (12.8628, 30.2176, "Sudan"),
    "ET": (9.1450, 40.4897, "Ethiopia"),
    "SO": (5.1521, 46.1996, "Somalia"),
}

class GeocodingService:
    def __init__(self, db_handler):
        self.db = db_handler

    def geocode_entity(self, entity_id: int, etype: str, evalue: str) -> tuple | None:
        """
        Resolves coordinates for an entity and caches it in the database.
        Returns (latitude, longitude, country, city) or None.
        """
        cached = self._get_cached_geocode(entity_id)
        if cached:
            return cached

        lat, lng, country, city = None, None, None, None

        if etype == "phone":
            lat, lng, country, city = self._geocode_phone(entity_id, evalue)
        elif etype == "ip_address":
            lat, lng, country, city = self._geocode_ip(evalue)
        
        if lat is not None and lng is not None:
            self._save_geocode_cache(entity_id, lat, lng, country, city)
            return (lat, lng, country, city)

        return None

    def _get_cached_geocode(self, entity_id: int) -> tuple | None:
        sql = "SELECT latitude, longitude, country, city FROM geocodes WHERE entity_id = ?"
        try:
            with get_db(self.db.db_path) as conn:
                row = conn.execute(sql, (entity_id,)).fetchone()
                if row:
                    return (row["latitude"], row["longitude"], row["country"], row["city"])
        except Exception as e:
            logger.warning("Error reading geocode cache: %s", e)
        return None

    def _save_geocode_cache(self, entity_id: int, lat: float, lng: float, country: str, city: str) -> None:
        sql = """
            INSERT OR REPLACE INTO geocodes (entity_id, latitude, longitude, country, city, resolved_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """
        now = datetime.now(timezone.utc).isoformat()
        try:
            with get_db(self.db.db_path) as conn:
                conn.execute(sql, (entity_id, lat, lng, country, city, now))
        except Exception as e:
            logger.error("Error saving geocode cache for entity %d: %s", entity_id, e)

    def _geocode_phone(self, entity_id: int, phone_val: str) -> tuple:
        """Geocode phone using phonenumbers country data and local centroids dictionary."""
        import phonenumbers
        from phonenumbers import geocoder
        
        lat, lng, country, city = None, None, None, None
        try:
            parsed = phonenumbers.parse(phone_val)
            country = geocoder.country_name_for_number(parsed, "en")
            city = geocoder.description_for_number(parsed, "en")
            if city == country:
                city = None

            region_code = phonenumbers.region_code_for_number(parsed)
            if region_code in COUNTRY_CENTROIDS:
                lat, lng, c_name = COUNTRY_CENTROIDS[region_code]
                if not country:
                    country = c_name
            else:
                if country:
                    lat, lng = self._query_nominatim(country)
        except Exception as e:
            logger.warning("Failed to geocode phone number %s: %s", phone_val, e)

        return lat, lng, country, city

    def _geocode_ip(self, ip_val: str) -> tuple:
        """Geocode IP address using free keyless online API ip-api.com."""
        if ip_val.startswith(("127.", "10.", "192.168.", "169.254.")):
            return None, None, "Local Loopback/Private Network", None
        if ip_val.startswith("172."):
            try:
                second = int(ip_val.split(".")[1])
                if 16 <= second <= 31:
                    return None, None, "Private Network", None
            except ValueError:
                pass

        lat, lng, country, city = None, None, None, None
        url = f"http://ip-api.com/json/{ip_val}"
        try:
            req = urllib.request.Request(
                url, 
                headers={'User-Agent': 'TeleWireThreatIntel/1.0'}
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                res_data = json.loads(response.read().decode())
                if res_data.get("status") == "success":
                    lat = res_data.get("lat")
                    lng = res_data.get("lon")
                    country = res_data.get("country")
                    city = res_data.get("city")
        except Exception as e:
            logger.warning("Online IP geocoder failed for %s: %s", ip_val, e)

        return lat, lng, country, city

    def _query_nominatim(self, query: str) -> tuple:
        """Polite online query to OpenStreetMap Nominatim API."""
        import urllib.parse
        encoded = urllib.parse.quote_plus(query)
        url = f"https://nominatim.openstreetmap.org/search?q={encoded}&format=json&limit=1"
        try:
            req = urllib.request.Request(
                url,
                headers={'User-Agent': 'TeleWireThreatIntel/1.0'}
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode())
                if data and len(data) > 0:
                    lat = float(data[0].get("lat"))
                    lng = float(data[0].get("lon"))
                    return lat, lng
        except Exception as e:
            logger.warning("OSM Nominatim lookup failed for '%s': %s", query, e)
        return None, None
