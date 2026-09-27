"""Place names (Kartverket stedsnavn) and municipality lookups, with a disk cache."""
from __future__ import annotations

import json
import time
from pathlib import Path

from .net import SESSION

NAMES_URL = "https://api.kartverket.no/stedsnavn/v1/punkt"
KOMMUNE_URL = "https://api.kartverket.no/kommuneinfo/v1/punkt"

# Name types that only add noise to a trip report
SKIP_TYPES = ("Adressenavn",)


def _main_name(entry: dict) -> str | None:
    names = entry.get("stedsnavn") or []
    for n in names:
        if n.get("navnestatus") == "hovednavn" and "prioritert" in (n.get("skrivemåtestatus") or ""):
            return n.get("skrivemåte")
    return names[0].get("skrivemåte") if names else None


class PlaceLookup:
    def __init__(self, cache_path: Path):
        self.cache_path = cache_path
        self.cache: dict = json.loads(cache_path.read_text("utf-8")) if cache_path.exists() else {}
        self.errors = 0

    def save(self) -> None:
        self.cache_path.write_text(json.dumps(self.cache, ensure_ascii=False), "utf-8")

    def _get(self, url: str, params: dict):
        key = url + "?" + json.dumps(params, sort_keys=True)
        if key in self.cache:
            return self.cache[key]
        try:
            r = SESSION.get(url, params=params, timeout=20)
            data = r.json() if r.status_code == 200 else None
        except Exception:  # network trouble must not stop the extraction
            self.errors += 1
            return None
        self.cache[key] = data
        time.sleep(0.05)
        return data

    def names_near(self, lat: float, lon: float, radius: int = 300) -> list[dict]:
        data = self._get(NAMES_URL, {
            "nord": round(lat, 5), "ost": round(lon, 5), "koordsys": 4258, "utkoordsys": 4258,
            "radius": radius, "treffPerSide": 100, "side": 1,
        })
        out = []
        for e in (data or {}).get("navn", []):
            kind = e.get("navneobjekttype") or ""
            name = _main_name(e)
            if not name or kind.startswith(SKIP_TYPES):
                continue
            rp = e.get("representasjonspunkt") or {}
            out.append({
                "id": e.get("stedsnummer"), "navn": name, "type": kind,
                "m": e.get("meterFraPunkt"), "lat": rp.get("nord"), "lon": rp.get("øst"),
            })
        return sorted(out, key=lambda n: n["m"] or 0)

    def kommune(self, lat: float, lon: float) -> dict | None:
        data = self._get(KOMMUNE_URL, {"nord": round(lat, 5), "ost": round(lon, 5), "koordsys": 4258})
        if not data or "kommunenavn" not in data:
            return None
        return {"kommune": data["kommunenavn"], "fylke": data.get("fylkesnavn")}


def route_places(lookup: PlaceLookup, track, every_m: int = 400, radius: int = 300) -> list[dict]:
    """Named places along the route, ordered by where they are passed."""
    found: dict = {}
    for p in track.sample(every_m):
        for n in lookup.names_near(p.lat, p.lon, radius):
            prev = found.get(n["id"])
            if prev is None or n["m"] < prev["m"]:
                found[n["id"]] = {**n, "km": round(p.dist / 1000, 2),
                                  "tid": p.time.isoformat() if p.time else None}
    return sorted(found.values(), key=lambda n: n["km"])
