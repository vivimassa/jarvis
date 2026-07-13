"""
weather_report.py — real, spoken weather from the DEVICE's location.

No API key and no configured city: the location follows wherever the machine is
(IP geolocation), so it works on a laptop carried anywhere. Weather comes from
Open-Meteo (free, keyless). Returns concise text meant to be spoken aloud.
"""

import requests

_GEO_IP = "http://ip-api.com/json/?fields=status,city,regionName,country,lat,lon"
_GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST = "https://api.open-meteo.com/v1/forecast"

# WMO weather codes → short spoken description
_WMO = {
    0: "clear", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "foggy", 48: "foggy",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
    56: "freezing drizzle", 57: "freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain",
    66: "freezing rain", 67: "freezing rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "light showers", 81: "showers", 82: "heavy showers",
    85: "snow showers", 86: "snow showers",
    95: "thunderstorms", 96: "thunderstorms with hail", 99: "thunderstorms with hail",
}


def _device_location(timeout=5):
    """(city, lat, lon) from the device's public IP, or None."""
    try:
        r = requests.get(_GEO_IP, timeout=timeout)
        d = r.json()
        if d.get("status") == "success":
            name = d.get("city") or d.get("regionName") or d.get("country") or "your area"
            return name, float(d["lat"]), float(d["lon"])
    except Exception:
        pass
    return None


def _geocode(city, timeout=5):
    try:
        r = requests.get(_GEOCODE, params={"name": city, "count": 1}, timeout=timeout)
        res = (r.json() or {}).get("results") or []
        if res:
            g = res[0]
            return g.get("name", city), float(g["latitude"]), float(g["longitude"])
    except Exception:
        pass
    return None


def _fetch(lat, lon, timeout=6):
    params = {
        "latitude": lat, "longitude": lon,
        "current": "temperature_2m,apparent_temperature,weather_code",
        "daily": "temperature_2m_max,temperature_2m_min,weather_code,precipitation_probability_max",
        "timezone": "auto", "forecast_days": 1,
    }
    r = requests.get(_FORECAST, params=params, timeout=timeout)
    return r.json()


def get_weather_text(city: str | None = None) -> str:
    """Concise spoken weather for `city`, or the device's location if None."""
    loc = _geocode(city) if (city and city.strip()) else _device_location()
    if not loc:
        return ("I couldn't determine the location for a weather report — "
                "the location service may be unreachable.")
    name, lat, lon = loc
    try:
        d = _fetch(lat, lon)
        cur = d["current"]
        day = d["daily"]
        now_t = round(cur["temperature_2m"])
        feels = round(cur.get("apparent_temperature", cur["temperature_2m"]))
        cond = _WMO.get(int(cur["weather_code"]), "unsettled")
        hi = round(day["temperature_2m_max"][0])
        lo = round(day["temperature_2m_min"][0])
        pop = day.get("precipitation_probability_max", [None])[0]
        rain = f" Chance of precipitation {pop} percent." if pop not in (None, 0) else ""
        feels_clause = f", feeling like {feels}," if abs(feels - now_t) >= 2 else ""
        return (f"In {name} it's currently {now_t} degrees{feels_clause} and {cond}. "
                f"Today's high is {hi} and low is {lo}.{rain}")
    except Exception:
        return f"I found your location ({name}) but couldn't retrieve the weather just now."


def weather_action(parameters: dict, player=None, session_memory=None) -> str:
    """Gemini tool entry — speaks real weather. Uses the given city, else the
    device's own location (so it works anywhere with no configuration)."""
    city = (parameters or {}).get("city")
    text = get_weather_text(city if (city and str(city).strip()) else None)
    _log(text, player)
    if session_memory:
        try:
            session_memory.set_last_search(query=f"weather {city or 'here'}", response=text)
        except Exception:
            pass
    return text


def _log(message: str, player=None) -> None:
    print(f"[Weather] {message}")
    if player:
        try:
            player.write_log(f"JARVIS: {message}")
        except Exception:
            pass
