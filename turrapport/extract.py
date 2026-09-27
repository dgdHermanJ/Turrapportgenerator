"""Step 1: zip (GPX + photos) -> working folder with facts, web images, map and profile."""
from __future__ import annotations

import json
import shutil
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .graphics import elevation_svg, render_map
from .photos import PHOTO_EXT, Photo, read_photo, save_web_copy, web_name
from .places import PlaceLookup, route_places
from .track import Track
from .weather import hourly_weather

# Web filenames are numbered so that alphabetical order = map first, then photos in time order
MAP_FILE = "00-kart.jpg"


def _zip_name(info: zipfile.ZipInfo) -> str:
    """Zips without the UTF-8 flag are decoded as cp437 by Python; Windows writes them in the
    OEM code page (cp850 on Norwegian systems), so æøå come out wrong unless we re-decode."""
    if info.flag_bits & 0x800:
        return info.filename
    raw = info.filename.encode("cp437")
    for enc in ("utf-8", "cp850"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return info.filename


def _unpack(src: Path, raw: Path) -> None:
    if src.is_dir():
        shutil.copytree(src, raw, dirs_exist_ok=True)
        return
    with zipfile.ZipFile(src) as zf:
        for info in zf.infolist():
            parts = Path(_zip_name(info)).parts
            if info.is_dir() or "__MACOSX" in parts or any(p.startswith(".") for p in parts):
                continue
            target = (raw / Path(*parts)).resolve()
            if raw.resolve() not in target.parents:  # zip-slip guard
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as f_in, open(target, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)


def _fmt_dur(seconds: int | None) -> str:
    if seconds is None:
        return "–"
    h, m = divmod(round(seconds / 60), 60)
    return f"{h} t {m:02d} min"


def _match(photos: list[Photo], track: Track) -> None:
    """Position every photo on the route: EXIF GPS first, otherwise timestamp against the GPX track."""
    nr = 1
    margin = timedelta(minutes=15)
    for ph in photos:
        if ph.time and track.has_time and not (track.start - margin <= ph.time <= track.end + margin):
            ph.placement = "før turen" if ph.time < track.start else "etter turen"
        elif ph.lat is not None:
            pt, off = track.nearest(ph.lat, ph.lon, ph.time)
            ph.placement = "gps" if off < 1000 else "gps (utenfor ruta)"
            if off < 1000:
                ph.km, ph.ele = round(pt.dist / 1000, 2), pt.ele if pt.ele is not None else ph.gps_ele
        elif ph.time is not None and (pt := track.position_at(ph.time)) is not None:
            ph.lat, ph.lon, ph.placement = pt.lat, pt.lon, "tid"
            ph.km, ph.ele = round(pt.dist / 1000, 2), pt.ele
        if ph.km is not None:
            ph.nr, nr = nr, nr + 1


def extract(src: Path, out: Path, tz_name: str = "Europe/Oslo", offset_min: float = 0,
            use_net: bool = True, max_px: int = 1600) -> Path:
    tz = ZoneInfo(tz_name)
    raw, images = out / "raw", out / "images"
    for d in (raw, images):
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
    print(f"Pakker ut {src} ...")
    _unpack(src, raw)

    files = sorted(p for p in raw.rglob("*") if p.is_file())
    gpx_files = [p for p in files if p.suffix.lower() == ".gpx"]
    photo_files = [p for p in files if p.suffix.lower() in PHOTO_EXT]
    if not gpx_files:
        raise SystemExit("Fant ingen .gpx-fil i zip-filen")
    print(f"Fant {len(gpx_files)} GPX-fil(er) og {len(photo_files)} bilder")

    track = Track(gpx_files)
    stats = track.stats()

    photos: list[Photo] = []
    for p in photo_files:
        try:
            photos.append(read_photo(p, tz))
        except Exception as e:  # unreadable/corrupt file: skip, but say so
            print(f"  hopper over {p.name}: {e}")
    if offset_min:
        for ph in photos:
            if ph.time:
                ph.time += timedelta(minutes=offset_min)
    photos.sort(key=lambda ph: (ph.time is None, ph.time or datetime.min, ph.source.name))
    _match(photos, track)

    taken: set[str] = {MAP_FILE}
    for i, ph in enumerate(photos, 1):
        ph.file = web_name(f"{i:02d}-{ph.source.stem}", taken)
        save_web_copy(ph.source, images / ph.file, max_px)
    print(f"Lagret {len(photos)} webversjoner i {images}")

    first = track.points[0]
    area, places, weather, norway = None, [], [], False
    if use_net:
        lookup = PlaceLookup(out / "places_cache.json")
        area = lookup.kommune(first.lat, first.lon)
        norway = area is not None
        if norway:
            print("Henter stedsnavn fra Kartverket ...")
            places = route_places(lookup, track)
            for p in places:
                if p["tid"]:
                    p["tid"] = datetime.fromisoformat(p["tid"]).astimezone(tz).isoformat(timespec="minutes")
            for ph in photos:
                if ph.lat is not None:
                    ph.places = lookup.names_near(ph.lat, ph.lon, 500)[:5]
            if stats["highest_point"]:
                hp = stats["highest_point"]
                hp["navn"] = [n["navn"] for n in lookup.names_near(hp["lat"], hp["lon"], 250)[:3]]
        lookup.save()
        if lookup.errors:
            print(f"  advarsel: {lookup.errors} stedsnavn-oppslag feilet")
        if track.has_time:
            try:
                weather = hourly_weather(first.lat, first.lon, track.start.astimezone(tz), track.end.astimezone(tz),
                                         tz_name)
            except Exception as e:
                print(f"  advarsel: kunne ikke hente vær: {e}")

    map_credit = None
    try:
        print("Tegner kart ...")
        map_credit = render_map(track, photos, images / MAP_FILE, norway)
    except Exception as e:
        print(f"  advarsel: kunne ikke tegne kart: {e}")
    svg = elevation_svg(track, photos)
    if svg:
        (out / "hoydeprofil.svg").write_text(svg, "utf-8")

    def local(t):
        return t.astimezone(tz).isoformat(timespec="minutes") if t else None

    trip = {
        "kilde": src.name,
        "tidssone": tz_name,
        "gpx_navn": track.names,
        "område": area,
        "statistikk": {**stats, "start": local(track.start), "end": local(track.end)},
        "kart": {"fil": MAP_FILE, "kreditering": map_credit} if map_credit else None,
        "høydeprofil": "hoydeprofil.svg" if svg else None,
        "veipunkter": [{"navn": w.name, "lat": w.latitude, "lon": w.longitude, "ele": w.elevation}
                       for w in track.waypoints],
        "steder_langs_ruta": places,
        "vær": weather,
        "bilder": [{
            "nr": ph.nr, "fil": ph.file, "original": ph.source.name, "tid": local(ph.time),
            "tidskilde": ph.time_source, "plassering": ph.placement, "km": ph.km,
            "moh": round(ph.ele) if ph.ele is not None else None,
            "lat": round(ph.lat, 5) if ph.lat is not None else None,
            "lon": round(ph.lon, 5) if ph.lon is not None else None,
            "kamera": ph.camera, "beskrivelse": ph.description, "steder_i_nærheten": ph.places,
        } for ph in photos],
    }
    (out / "trip.json").write_text(json.dumps(trip, ensure_ascii=False, indent=2), "utf-8")
    (out / "brief.md").write_text(_brief(trip), "utf-8")
    print(f"Ferdig: {out / 'brief.md'}")
    return out


def _brief(t: dict) -> str:
    s = t["statistikk"]
    hp_names = (s["highest_point"] or {}).get("navn")
    L = ["# Grunnlag for turrapport", ""]
    if t["område"]:
        L.append(f"**Område:** {t['område']['kommune']}, {t['område']['fylke']}")
    if t["gpx_navn"]:
        L.append(f"**Navn i GPX:** {', '.join(dict.fromkeys(t['gpx_navn']))}")
    L += [
        f"**Start:** {s['start'] or '–'}  **Slutt:** {s['end'] or '–'}",
        f"**Distanse:** {s['distance_km']} km  **Stigning:** {s['ascent_m']} m  **Nedstigning:** {s['descent_m']} m",
        f"**Høyeste punkt:** {s['max_ele_m']} moh."
        + (f" ({', '.join(hp_names)})" if hp_names else "")
        + f"  **Laveste:** {s['min_ele_m']} moh.",
        f"**Total tid:** {_fmt_dur(s['duration_s'])}  **I bevegelse:** {_fmt_dur(s['moving_s'])}",
        "",
    ]
    if t["vær"]:
        L += ["## Vær (Open-Meteo, modellverdier ved startpunktet)", "",
              "| Tid | Vær | Temp | Nedbør | Vind | Skydekke |", "|---|---|---|---|---|---|"]
        L += [f"| {w['tid'][11:16]} | {w['vær']} | {w['temp_c']} °C | {w['nedbør_mm']} mm | {w['vind_ms']} m/s "
              f"| {w['skydekke_pct']} % |" for w in t["vær"]]
        L.append("")
    if t["veipunkter"]:
        L += ["## Veipunkter i GPX", ""] + [f"- {w['navn']} ({w['ele'] or '?'} moh.)" for w in t["veipunkter"]] + [""]
    if t["steder_langs_ruta"]:
        L += ["## Stedsnavn langs ruta (Kartverket)", "", "| km | Klokka | Navn | Type | Avstand fra sporet |",
              "|---|---|---|---|---|"]
        L += [f"| {p['km']} | {(p['tid'] or '')[11:16]} | {p['navn']} "
              f"| {p['type']} | {p['m']} m |" for p in t["steder_langs_ruta"]]
        L.append("")
    L += ["## Bilder i tidsrekkefølge", "",
          "Se på hvert bilde i `images/` før du skriver. `nr` er nummeret på kartet og i høydeprofilen.", ""]
    for b in t["bilder"]:
        head = f"### {'#' + str(b['nr']) if b['nr'] else '(ikke plassert)'} – `{b['fil']}`"
        L.append(head)
        info = [f"tid {b['tid'][11:16] if b['tid'] else 'ukjent'}"]
        if b["km"] is not None:
            info.append(f"km {b['km']}")
        if b["moh"] is not None:
            info.append(f"{b['moh']} moh.")
        info.append(f"plassering: {b['plassering']}")
        L.append("- " + ", ".join(info))
        if b["steder_i_nærheten"]:
            L.append("- nær: " + ", ".join(f"{p['navn']} ({p['type']}, {p['m']} m)" for p in b["steder_i_nærheten"]))
        if b["beskrivelse"]:
            L.append(f"- beskrivelse i EXIF: {b['beskrivelse']}")
        L.append("")
    return "\n".join(L)
