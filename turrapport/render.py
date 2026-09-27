"""Step 2: report.md + trip.json -> HTML for Blogger (and a local preview).

report.md syntax
----------------
# Tittel                         (first line; becomes the post title, not part of the body)
## Mellomtittel
Vanlige avsnitt med **fet**, *kursiv* og [lenker](https://...).
- punktlister
[nøkkeltall]                     key figures box
[nøkkeltall: Høyeste punkt=2064 moh.; Følge=2 + 2 hunder]   override/add rows (empty value hides a row)
[kart]                           route map with numbered photo markers
[høydeprofil]                    elevation profile
[bilde: 03-img_1234.jpg | Bildetekst]
[bilder: 04-a.jpg, 05-b.jpg | Felles bildetekst]   two or more photos side by side
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from html import escape
from pathlib import Path

from .extract import MAP_FILE

WEEKDAYS = ["mandag", "tirsdag", "onsdag", "torsdag", "fredag", "lørdag", "søndag"]
MONTHS = ["januar", "februar", "mars", "april", "mai", "juni", "juli", "august", "september",
          "oktober", "november", "desember"]

FIG = 'margin:1.5em 0;text-align:center'
CAP = 'font-size:0.9em;color:#555;margin-top:0.4em;font-style:italic'
IMG = 'max-width:100%;max-height:85vh;width:auto;height:auto;border-radius:4px'


def _inline(text: str) -> str:
    s = escape(text, quote=False)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", lambda m: f'<a href="{escape(m[2])}">{m[1]}</a>', s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"<em>\1</em>", s)
    return s


def _norsk_dato(iso: str | None) -> str | None:
    if not iso:
        return None
    d = datetime.fromisoformat(iso)
    return f"{WEEKDAYS[d.weekday()]} {d.day}. {MONTHS[d.month - 1]} {d.year}"


def _dur(seconds: int | None) -> str | None:
    if not seconds:
        return None
    h, m = divmod(round(seconds / 60), 60)
    return f"{h} t {m:02d} min" if h else f"{m} min"


# ---------- image URLs ----------

def _resize_blogger(url: str, size: int = 1600) -> str:
    if re.search(r"/(s\d+|w\d+-h\d+(-[a-z]+)?)/", url):  # old format: .../s1600/name.jpg
        return re.sub(r"/(s\d+|w\d+-h\d+(-[a-z]+)?)/", f"/s{size}/", url)
    base = re.sub(r"=[a-z0-9-]+$", "", url)  # new format: .../img/a/<id>=s1600
    return f"{base}=s{size}"


def _fingerprint(im) -> list[int]:
    from PIL import ImageOps
    g = ImageOps.exif_transpose(im).convert("L").resize((16, 16))
    return list(g.getdata())


def _match_by_content(urls: list[str], files: list[str], images: Path) -> dict[str, str]:
    """Blogger URLs often lack filenames and upload order is unreliable: compare thumbnails instead."""
    from io import BytesIO

    from PIL import Image

    from .net import SESSION

    local = {}
    for f in files:
        with Image.open(images / f) as im:
            local[f] = _fingerprint(im)
    remote = {}
    for u in urls:
        r = SESSION.get(_resize_blogger(u, 256), timeout=30)
        r.raise_for_status()
        with Image.open(BytesIO(r.content)) as im:
            remote[u] = _fingerprint(im)
    pairs = sorted((sum((a - b) ** 2 for a, b in zip(local[f], remote[u])) / 256, f, u)
                   for f in local for u in remote)
    mapping, used_u = {}, set()
    for dist, f, u in pairs:  # greedy: best matches first
        if f not in mapping and u not in used_u and dist < 1500:
            mapping[f] = u
            used_u.add(u)
    return mapping


def urls_from_blogger_html(html: str, files: list[str], images: Path) -> dict[str, str]:
    """Map image files to URLs found in the HTML of a Blogger draft that the images were uploaded to.

    Matches by filename where Blogger kept it in the URL, otherwise by comparing image content.
    """
    urls = []
    for u in re.findall(r'(?:src|href)="(https://[^"]*(?:googleusercontent|bp\.blogspot)[^"]*)"', html):
        u = _resize_blogger(u)
        if u not in urls:
            urls.append(u)
    mapping, rest = {}, []
    for f in files:
        hit = next((u for u in urls if u.split("?")[0].rsplit("/", 1)[-1] == f), None)
        if hit:
            mapping[f] = hit
            urls.remove(hit)
        else:
            rest.append(f)
    if rest and urls:
        mapping.update(_match_by_content(urls, rest, images))
    return mapping


# ---------- rendering ----------

class Renderer:
    def __init__(self, work: Path, src_for):
        self.work = work
        self.trip = json.loads((work / "trip.json").read_text("utf-8"))
        self.src_for = src_for
        self.used: list[str] = []
        self.problems: list[str] = []
        self.known = {b["fil"] for b in self.trip["bilder"]} | {MAP_FILE}

    def _img(self, name: str, caption: str | None = None) -> str:
        if name not in self.known:
            self.problems.append(f"ukjent bilde: {name}")
        self.used.append(name)
        src = escape(self.src_for(name))
        return f'<a href="{src}"><img src="{src}" alt="{escape(caption or "")}" style="{IMG}"/></a>'

    def figure(self, names: list[str], caption: str | None) -> str:
        cap = f'<figcaption style="{CAP}">{_inline(caption)}</figcaption>' if caption else ""
        if len(names) == 1:
            return f'<figure style="{FIG}">{self._img(names[0], caption)}{cap}</figure>'
        cells = "".join(f'<div style="flex:1 1 240px">{self._img(n, caption)}</div>' for n in names)
        return f'<figure style="{FIG}"><div style="display:flex;flex-wrap:wrap;gap:8px">{cells}</div>{cap}</figure>'

    def key_figures(self, overrides: str = "") -> str:
        """overrides: "Høyeste punkt=2064 moh.; Deltakere=2 + 2 hunder" replaces or adds rows."""
        s, area = self.trip["statistikk"], self.trip.get("område")
        rows = [
            ("Dato", _norsk_dato(s["start"])),
            ("Område", f"{area['kommune']}, {area['fylke']}" if area else None),
            ("Distanse", f"{s['distance_km']:.1f} km".replace(".", ",")),
            ("Stigning", f"{s['ascent_m']} høydemeter" if s["ascent_m"] is not None else None),
            ("Høyeste punkt", f"{s['max_ele_m']} moh." + (
                f" ({s['highest_point']['navn'][0]})" if (s.get("highest_point") or {}).get("navn") else "")
             if s["max_ele_m"] is not None else None),
            ("Tid totalt", _dur(s["duration_s"])),
            ("Tid i bevegelse", _dur(s["moving_s"])),
        ]
        for item in filter(None, (x.strip() for x in overrides.split(";"))):
            k, _, v = (p.strip() for p in item.partition("="))
            i = next((i for i, (key, _) in enumerate(rows) if key.lower() == k.lower()), None)
            if i is None:
                rows.append((k, v or None))
            else:
                rows[i] = (rows[i][0], v or None)  # empty value hides the row
        cells = "".join(
            f'<tr><td style="padding:4px 12px 4px 0;color:#555">{k}</td>'
            f'<td style="padding:4px 0;font-weight:bold">{escape(v)}</td></tr>'
            for k, v in rows if v)
        return (f'<div style="background:#f3f4f6;border-left:4px solid #d62828;padding:12px 16px;margin:1.5em 0">'
                f'<table style="border-collapse:collapse;border:none">{cells}</table></div>')

    def map(self) -> str:
        m = self.trip.get("kart")
        if not m:
            self.problems.append("[kart] brukt, men kart mangler")
            return ""
        return self.figure([MAP_FILE], f"Ruta. Tallene viser hvor bildene er tatt. Kart: {m['kreditering']}")

    def profile(self) -> str:
        f = self.trip.get("høydeprofil")
        if not f:
            self.problems.append("[høydeprofil] brukt, men GPX mangler høydedata")
            return ""
        svg = (self.work / f).read_text("utf-8")
        return (f'<figure style="{FIG}">{svg}<figcaption style="{CAP}">Høydeprofil. '
                f'Tallene viser hvor bildene er tatt.</figcaption></figure>')

    def render(self, md: str) -> tuple[str, str]:
        title, out = "", []
        for block in re.split(r"\n\s*\n", md.strip()):
            lines = [ln.rstrip() for ln in block.strip().splitlines()]
            first = lines[0]
            if first.startswith("# ") and not title and not out:
                title = first[2:].strip()
                lines = lines[1:]
                if not lines:
                    continue
                first = lines[0]
            if m := re.fullmatch(r"(#{2,4})\s+(.*)", first):
                level = len(m[1])
                out.append(f"<h{level}>{_inline(m[2])}</h{level}>")
                lines = lines[1:]
                if not lines:
                    continue
            directive_lines = [ln for ln in lines if re.fullmatch(r"\[[^\]]+\]", ln.strip())]
            if directive_lines and len(directive_lines) == len(lines):
                out.extend(self.directive(ln.strip()[1:-1]) for ln in lines)
            elif all(ln.lstrip().startswith("- ") for ln in lines):
                out.append("<ul>" + "".join(f"<li>{_inline(ln.lstrip()[2:])}</li>" for ln in lines) + "</ul>")
            else:
                out.append(f"<p>{_inline(' '.join(ln.strip() for ln in lines))}</p>")
        return title, "\n".join(o for o in out if o)

    def directive(self, d: str) -> str:
        key, _, arg = d.partition(":")
        key = key.strip().lower()
        if key == "nøkkeltall":
            return self.key_figures(arg)
        if key == "kart":
            return self.map()
        if key in ("høydeprofil", "hoydeprofil"):
            return self.profile()
        if key in ("bilde", "bilder"):
            files, _, caption = arg.partition("|")
            names = [f.strip() for f in files.split(",") if f.strip()]
            return self.figure(names, caption.strip() or None)
        self.problems.append(f"ukjent direktiv: [{d}]")
        return ""


def render(work: Path, report: Path | None = None, urls_from: Path | None = None,
           base_url: str | None = None) -> None:
    report = report or work / "report.md"
    md = report.read_text("utf-8")
    url_file = work / "image_urls.json"

    # Pass 1: local preview (also tells us which images the report uses)
    pre = Renderer(work, lambda f: f"images/{f}")
    title, body_local = pre.render(md)
    used = [f for f in dict.fromkeys(pre.used) if f in pre.known]

    if urls_from:
        mapping = urls_from_blogger_html(urls_from.read_text("utf-8"), used, work / "images")
        if url_file.exists():  # keep earlier matches (e.g. the map uploaded in a separate round)
            mapping = {**json.loads(url_file.read_text("utf-8")), **mapping}
        url_file.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), "utf-8")
        print(f"Lagret {len(mapping)} bilde-URLer i {url_file}:")
        for f, u in mapping.items():
            print(f"  {f} -> {u[:90]}")
    mapping = json.loads(url_file.read_text("utf-8")) if url_file.exists() else {}

    missing = [f for f in used if f not in mapping and not base_url]

    def src_for(f):
        if f in mapping:
            return mapping[f]
        if base_url:
            return base_url.rstrip("/") + "/" + f
        return f"images/{f}"

    blog = Renderer(work, src_for)
    _, body = blog.render(md)
    (work / "blogger.html").write_text(body + "\n", "utf-8")
    (work / "preview.html").write_text(
        f'<!doctype html><html lang="no"><head><meta charset="utf-8"><title>{escape(title)}</title>'
        f'<meta name="viewport" content="width=device-width,initial-scale=1"></head>'
        f'<body style="max-width:760px;margin:2em auto;padding:0 16px;font-family:Georgia,serif;'
        f'line-height:1.6;color:#222"><h1>{escape(title)}</h1>\n{body_local}\n</body></html>', "utf-8")

    unused = [b["fil"] for b in pre.trip["bilder"] if b["fil"] not in used]
    print(f"Tittel: {title or '(mangler – start report.md med «# Tittel»)'}")
    print(f"Skrev {work / 'blogger.html'} og {work / 'preview.html'}")
    print(f"Bilder i bruk: {len(used)}  (ubrukte: {len(unused)})")
    for p in dict.fromkeys(pre.problems):
        print(f"  PROBLEM: {p}")
    if missing:
        print(f"  NB: {len(missing)} bilder har ingen nett-URL ennå – blogger.html peker til lokale filer.")
        print("      Last opp disse til et Blogger-utkast, kopier HTML-visningen til en fil og kjør")
        print("      render på nytt med --urls-from <fil>. Bildene som skal lastes opp:")
        for f in sorted(missing):
            print(f"        images/{f}")
