"""Live weather for the almanac module.

Source: Open-Meteo (https://open-meteo.com) — free, no API key, no rate limit
for our volume, and CORS-enabled so the same endpoint works from the browser.

Two layers:
  * Build time  — this module bakes the current reading into the edition, so a
                  printed edition keeps the weather it was published with.
  * Read time   — the newest edition refreshes itself client-side, so opening
                  today's paper shows the weather right now.

Never invent a reading. If the fetch fails, the caller drops the module.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

# Haifa, resolved via Open-Meteo geocoding (Haifa District, Israel).
HAIFA = {"name": "חיפה", "lat": 32.81303, "lon": 34.99928, "tz": "Asia/Jerusalem"}

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# WMO weather interpretation codes -> Hebrew.
WMO_HE = {
    0: "בהיר",
    1: "בהיר בעיקר",
    2: "מעונן חלקית",
    3: "מעונן",
    45: "ערפל",
    48: "ערפל מקפיא",
    51: "טפטוף קל",
    53: "טפטוף",
    55: "טפטוף חזק",
    56: "טפטוף קפוא קל",
    57: "טפטוף קפוא",
    61: "גשם קל",
    63: "גשם",
    65: "גשם חזק",
    66: "גשם קפוא קל",
    67: "גשם קפוא",
    71: "שלג קל",
    73: "שלג",
    75: "שלג כבד",
    77: "גרגרי שלג",
    80: "ממטרים קלים",
    81: "ממטרים",
    82: "ממטרים עזים",
    85: "ממטרי שלג קלים",
    86: "ממטרי שלג",
    95: "סופת רעמים",
    96: "סופת רעמים עם ברד קל",
    99: "סופת רעמים עם ברד",
}


def describe(code: int) -> str:
    return WMO_HE.get(code, "לא ידוע")


def fetch(place: dict | None = None, timeout: int = 20) -> dict:
    """Return the current reading. Raises on any failure — never guesses."""
    place = place or HAIFA
    query = urllib.parse.urlencode(
        {
            "latitude": place["lat"],
            "longitude": place["lon"],
            "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code",
            "daily": "temperature_2m_max,temperature_2m_min",
            "timezone": place["tz"],
            "forecast_days": 1,
        }
    )
    req = urllib.request.Request(
        f"{FORECAST_URL}?{query}",
        headers={"User-Agent": "DailyDigest/1.0 (personal newspaper)"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.load(resp)

    cur = data["current"]
    daily = data["daily"]
    code = int(cur["weather_code"])

    return {
        "place": place["name"],
        "temp": f"{round(cur['temperature_2m'])}°",
        "conditions": describe(code),
        "feels_like": round(cur["apparent_temperature"]),
        "humidity": int(cur["relative_humidity_2m"]),
        "high": round(daily["temperature_2m_max"][0]),
        "low": round(daily["temperature_2m_min"][0]),
        "code": code,
        "observed": cur["time"],
        "source": "Open-Meteo",
        # Handed to the template so the browser can refresh the same reading.
        "lat": place["lat"],
        "lon": place["lon"],
        "tz": place["tz"],
    }


if __name__ == "__main__":
    for k, v in fetch().items():
        print(f"{k:12} {v}")
