"""Route map (JPEG) and elevation profile (inline SVG)."""
from __future__ import annotations

from html import escape
from pathlib import Path

from PIL import ImageDraw, ImageFont
from staticmap import CircleMarker, Line, StaticMap
from staticmap.staticmap import _lat_to_y, _lon_to_x

from . import net  # noqa: F401  (activates truststore for staticmap's requests)
from .net import USER_AGENT

TOPO_TILES = "https://cache.kartverket.no/v1/wmts/1.0.0/topo/default/webmercator/{z}/{y}/{x}.png"
OSM_TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"

ROUTE_COLOR = "#d62828"
PHOTO_COLOR = "#1d4ed8"


def _thin(points, max_n):
    step = max(1, len(points) // max_n)
    return points[::step] + ([points[-1]] if (len(points) - 1) % step else [])


def render_map(track, photos, out_path: Path, norway: bool, size=(1200, 800)) -> str:
    m = StaticMap(size[0], size[1], padding_x=70, padding_y=70,
                  url_template=TOPO_TILES if norway else OSM_TILES,
                  headers={"User-Agent": USER_AGENT}, tile_request_timeout=20)
    coords = [(p.lon, p.lat) for p in _thin(track.points, 3000)]
    m.add_line(Line(coords, "white", 8))
    m.add_line(Line(coords, ROUTE_COLOR, 4))
    m.add_marker(CircleMarker(coords[0], "white", 18))
    m.add_marker(CircleMarker(coords[0], "#16a34a", 12))
    m.add_marker(CircleMarker(coords[-1], "white", 18))
    m.add_marker(CircleMarker(coords[-1], "#111827", 12))
    img = m.render()

    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=15)
    for ph in photos:
        if ph.nr is None or ph.lat is None:
            continue
        x = m._x_to_px(_lon_to_x(ph.lon, m.zoom))
        y = m._y_to_px(_lat_to_y(ph.lat, m.zoom))
        r = 13
        draw.ellipse((x - r, y - r, x + r, y + r), fill=PHOTO_COLOR, outline="white", width=3)
        draw.text((x, y), str(ph.nr), fill="white", font=font, anchor="mm")

    credit = "© Kartverket" if norway else "© OpenStreetMap-bidragsytere"
    small = ImageFont.load_default(size=13)
    w = draw.textlength(credit, font=small)
    draw.rectangle((size[0] - w - 14, size[1] - 22, size[0], size[1]), fill=(255, 255, 255))
    draw.text((size[0] - 7, size[1] - 11), credit, fill="#333", font=small, anchor="rm")
    img.convert("RGB").save(out_path, "JPEG", quality=88, optimize=True)
    return credit


def elevation_svg(track, photos, width=800, height=240) -> str | None:
    pts = [p for p in track.points if p.ele is not None]
    if len(pts) < 2:
        return None
    pts = _thin(pts, 500)
    ml, mr, mt, mb = 48, 12, 16, 30
    pw, ph_ = width - ml - mr, height - mt - mb
    total = max(track.length, 1)
    lo, hi = min(p.ele for p in pts), max(p.ele for p in pts)
    step = next(s for s in (10, 20, 50, 100, 200, 250, 500, 1000) if (hi - lo) / s <= 5)
    lo, hi = (lo // step) * step, (hi // step + 1) * step

    def sx(d):
        return ml + d / total * pw

    def sy(e):
        return mt + (hi - e) / (hi - lo) * ph_

    line = " ".join(f"{sx(p.dist):.1f},{sy(p.ele):.1f}" for p in pts)
    area = f"{sx(pts[0].dist):.1f},{mt + ph_} {line} {sx(pts[-1].dist):.1f},{mt + ph_}"

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'style="width:100%;height:auto;font-family:sans-serif;font-size:11px" role="img" '
        f'aria-label="Høydeprofil">'
    ]
    e = lo
    while e <= hi:
        y = sy(e)
        parts.append(f'<line x1="{ml}" x2="{ml + pw}" y1="{y:.1f}" y2="{y:.1f}" stroke="#e5e7eb"/>')
        parts.append(f'<text x="{ml - 6}" y="{y + 4:.1f}" text-anchor="end" fill="#6b7280">{e:.0f}</text>')
        e += step
    km_total = total / 1000
    km_step = next(s for s in (0.5, 1, 2, 5, 10, 20, 50) if km_total / s <= 10)
    k = 0.0
    while k <= km_total + 1e-9:
        x = sx(k * 1000)
        parts.append(f'<text x="{x:.1f}" y="{height - 10}" text-anchor="middle" fill="#6b7280">{k:g}</text>')
        k += km_step
    parts.append(f'<polygon points="{area}" fill="{ROUTE_COLOR}" fill-opacity="0.15"/>')
    parts.append(f'<polyline points="{line}" fill="none" stroke="{ROUTE_COLOR}" stroke-width="2"/>')
    for ph in photos:
        if ph.nr is None or ph.km is None or ph.ele is None:
            continue
        x, y = sx(ph.km * 1000), sy(ph.ele)
        parts.append(f'<g><title>{escape(ph.file)}</title>'
                     f'<circle cx="{x:.1f}" cy="{y:.1f}" r="8" fill="{PHOTO_COLOR}" stroke="white" stroke-width="2"/>'
                     f'<text x="{x:.1f}" y="{y + 3.5:.1f}" text-anchor="middle" fill="white" '
                     f'font-size="9" font-weight="bold">{ph.nr}</text></g>')
    parts.append(f'<text x="{ml}" y="{mt - 4}" fill="#6b7280">moh.</text>')
    parts.append(f'<text x="{ml - 6}" y="{height - 10}" text-anchor="end" fill="#6b7280">km</text>')
    parts.append("</svg>")
    return "".join(parts)
