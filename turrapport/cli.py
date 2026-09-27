import argparse
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(prog="turrapport", description="Lag turrapport for Blogger fra GPX + bilder")
    sub = ap.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("extract", help="Pakk ut zip, les metadata, lag kart/høydeprofil og brief.md")
    e.add_argument("source", type=Path, help="zip-fil (eller mappe) med .gpx og bilder")
    e.add_argument("--out", type=Path, help="arbeidsmappe (standard: trips/<navn på zip>)")
    e.add_argument("--tz", default="Europe/Oslo", help="tidssone for bilder uten tidssone i EXIF")
    e.add_argument("--time-offset", type=float, default=0,
                   help="minutter å legge til bildetidene hvis kameraklokka gikk feil")
    e.add_argument("--no-net", action="store_true", help="ikke hent stedsnavn, vær eller kartfliser")
    e.add_argument("--max-px", type=int, default=1600, help="lengste side på webbildene")

    r = sub.add_parser("render", help="Lag blogger.html og preview.html fra report.md")
    r.add_argument("workdir", type=Path)
    r.add_argument("--report", type=Path, help="standard: <workdir>/report.md")
    r.add_argument("--urls-from", type=Path,
                   help="HTML kopiert fra et Blogger-utkast der bildene er lastet opp")
    r.add_argument("--image-base-url", help="alternativ: bildene ligger på <url>/<filnavn>")

    a = ap.parse_args()
    if a.cmd == "extract":
        from .extract import extract
        out = a.out or Path("trips") / a.source.stem
        extract(a.source, out, a.tz, a.time_offset, not a.no_net, a.max_px)
    else:
        from .render import render
        render(a.workdir, a.report, a.urls_from, a.image_base_url)
