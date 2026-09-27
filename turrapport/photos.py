"""Reading photo metadata and creating web-sized copies."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageOps

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except ImportError:  # HEIC support is optional
    pass

PHOTO_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".tif", ".tiff", ".webp"}

EXIF_IFD, GPS_IFD = 0x8769, 0x8825
TAG_MAKE, TAG_MODEL, TAG_DATETIME = 271, 272, 306
TAG_DT_ORIGINAL, TAG_DT_DIGITIZED = 36867, 36868
TAG_OFFSET_ORIGINAL, TAG_OFFSET = 36881, 36880
TAG_IMAGE_DESCRIPTION, TAG_USER_COMMENT = 270, 37510


@dataclass
class Photo:
    source: Path
    file: str = ""  # web copy filename in images/
    time: datetime | None = None  # UTC
    time_source: str = "mangler"
    lat: float | None = None
    lon: float | None = None
    gps_ele: float | None = None
    camera: str | None = None
    description: str | None = None
    width: int = 0
    height: int = 0
    # Filled in when matched against the track
    nr: int | None = None
    placement: str = "ukjent"  # "gps", "tid" or "ukjent"
    km: float | None = None
    ele: float | None = None
    places: list[dict] = field(default_factory=list)


def _parse_exif_dt(value) -> datetime | None:
    if not value:
        return None
    s = str(value).strip().rstrip("\x00")[:19]
    try:
        return datetime.strptime(s, "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None


def _parse_offset(value) -> timezone | None:
    m = re.fullmatch(r"([+-])(\d{2}):?(\d{2})", str(value or "").strip().rstrip("\x00"))
    if not m:
        return None
    delta = timedelta(hours=int(m[2]), minutes=int(m[3]))
    return timezone(-delta if m[1] == "-" else delta)


def _dms(v) -> float:
    d, m, s = (float(x) for x in v)
    return d + m / 60 + s / 3600


def _gps(gps: dict) -> tuple[float | None, float | None, float | None, datetime | None]:
    lat = lon = ele = t = None
    try:
        if 2 in gps and 4 in gps:
            lat = _dms(gps[2]) * (-1 if gps.get(1) == "S" else 1)
            lon = _dms(gps[4]) * (-1 if gps.get(3) == "W" else 1)
            if lat == 0 and lon == 0:
                lat = lon = None
        if 6 in gps:
            ele = float(gps[6]) * (-1 if gps.get(5) in (1, b"\x01") else 1)
        if 29 in gps and 7 in gps:
            h, m, s = (float(x) for x in gps[7])
            d = datetime.strptime(str(gps[29]).strip("\x00"), "%Y:%m:%d")
            t = d.replace(tzinfo=timezone.utc) + timedelta(hours=h, minutes=m, seconds=s)
    except (ValueError, TypeError, ZeroDivisionError):
        pass
    return lat, lon, ele, t


def read_photo(path: Path, default_tz: ZoneInfo) -> Photo:
    photo = Photo(source=path)
    with Image.open(path) as im:
        photo.width, photo.height = im.size
        exif = im.getexif()
    ex = exif.get_ifd(EXIF_IFD)
    gps = exif.get_ifd(GPS_IFD)

    make, model = str(exif.get(TAG_MAKE, "")).strip("\x00 "), str(exif.get(TAG_MODEL, "")).strip("\x00 ")
    photo.camera = (model if make and model.startswith(make) else f"{make} {model}").strip() or None
    desc = str(exif.get(TAG_IMAGE_DESCRIPTION, "")).strip("\x00 ")
    photo.description = desc or None

    photo.lat, photo.lon, photo.gps_ele, gps_time = _gps(gps)

    local = _parse_exif_dt(ex.get(TAG_DT_ORIGINAL) or ex.get(TAG_DT_DIGITIZED) or exif.get(TAG_DATETIME))
    offset = _parse_offset(ex.get(TAG_OFFSET_ORIGINAL) or ex.get(TAG_OFFSET))
    if local and offset:
        photo.time, photo.time_source = local.replace(tzinfo=offset).astimezone(timezone.utc), "exif+offset"
    elif gps_time:
        photo.time, photo.time_source = gps_time, "gps"
    elif local:
        photo.time = local.replace(tzinfo=default_tz).astimezone(timezone.utc)
        photo.time_source = f"exif (antatt {default_tz.key})"
    return photo


def web_name(stem: str, taken: set[str]) -> str:
    stem = stem.lower().translate(str.maketrans({"æ": "ae", "ø": "o", "å": "a", "ä": "a", "ö": "o", "ü": "u"}))
    base = re.sub(r"[^a-z0-9_-]+", "-", stem).strip("-") or "bilde"
    name, i = f"{base}.jpg", 2
    while name in taken:
        name, i = f"{base}-{i}.jpg", i + 1
    taken.add(name)
    return name


def save_web_copy(src: Path, dst: Path, max_px: int = 1600) -> None:
    """Rotated, downscaled JPEG without metadata (no GPS position leaks online)."""
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((max_px, max_px), Image.LANCZOS)
        im.save(dst, "JPEG", quality=85, optimize=True, progressive=True)
