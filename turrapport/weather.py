"""Historical hourly weather for the trip from Open-Meteo (free, no API key)."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from .net import SESSION

WMO = {
    0: "klarvær", 1: "lettskyet", 2: "delvis skyet", 3: "overskyet", 45: "tåke", 48: "rimtåke",
    51: "lett yr", 53: "yr", 55: "kraftig yr", 56: "underkjølt yr", 57: "underkjølt yr",
    61: "lett regn", 63: "regn", 65: "kraftig regn", 66: "underkjølt regn", 67: "underkjølt regn",
    71: "lett snø", 73: "snø", 75: "kraftig snø", 77: "snøkorn", 80: "lette regnbyger",
    81: "regnbyger", 82: "kraftige regnbyger", 85: "snøbyger", 86: "kraftige snøbyger",
    95: "tordenvær", 96: "tordenvær med hagl", 99: "tordenvær med hagl",
}


def hourly_weather(lat: float, lon: float, start: datetime, end: datetime, tz: str) -> list[dict]:
    """Hourly weather (local time) from one hour before start to one hour after end."""
    recent = (date.today() - end.date()).days <= 5
    url = ("https://api.open-meteo.com/v1/forecast" if recent
           else "https://archive-api.open-meteo.com/v1/archive")
    r = SESSION.get(url, timeout=20, params={
        "latitude": round(lat, 4), "longitude": round(lon, 4),
        "start_date": start.date().isoformat(), "end_date": end.date().isoformat(),
        "hourly": "temperature_2m,precipitation,wind_speed_10m,cloud_cover,weather_code",
        "timezone": tz, "wind_speed_unit": "ms",
    })
    r.raise_for_status()
    h = r.json()["hourly"]
    lo = (start - timedelta(hours=1)).replace(tzinfo=None)
    hi = (end + timedelta(hours=1)).replace(tzinfo=None)
    out = []
    for i, t in enumerate(h["time"]):
        ts = datetime.fromisoformat(t)
        if lo <= ts <= hi:
            out.append({
                "tid": t, "temp_c": h["temperature_2m"][i], "nedbør_mm": h["precipitation"][i],
                "vind_ms": h["wind_speed_10m"][i], "skydekke_pct": h["cloud_cover"][i],
                "vær": WMO.get(h["weather_code"][i], str(h["weather_code"][i])),
            })
    return out
