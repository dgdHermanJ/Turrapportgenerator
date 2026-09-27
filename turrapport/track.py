"""Loading GPX files and computing route statistics."""
from __future__ import annotations

import bisect
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import gpxpy
import gpxpy.gpx
from gpxpy.geo import haversine_distance


@dataclass
class Point:
    lat: float
    lon: float
    ele: float | None
    time: datetime | None  # UTC
    dist: float = 0.0  # meters from start


def _utc(t: datetime | None) -> datetime | None:
    if t is None:
        return None
    return t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t.astimezone(timezone.utc)


class Track:
    def __init__(self, gpx_paths: list[Path]):
        self.gpx = gpxpy.gpx.GPX()
        self.waypoints: list[gpxpy.gpx.GPXWaypoint] = []
        self.names: list[str] = []
        for path in gpx_paths:
            with open(path, encoding="utf-8") as f:
                g = gpxpy.parse(f)
            if g.name:
                self.names.append(g.name)
            self.waypoints.extend(g.waypoints)
            self.gpx.tracks.extend(g.tracks)
            if not g.tracks:  # route-only file: treat the route as a track
                for route in g.routes:
                    seg = gpxpy.gpx.GPXTrackSegment(
                        [gpxpy.gpx.GPXTrackPoint(p.latitude, p.longitude, p.elevation, p.time) for p in route.points]
                    )
                    trk = gpxpy.gpx.GPXTrack(name=route.name)
                    trk.segments.append(seg)
                    self.gpx.tracks.append(trk)
            self.names.extend(t.name for t in g.tracks if t.name)

        pts = [
            Point(p.latitude, p.longitude, p.elevation, _utc(p.time))
            for t in self.gpx.tracks for s in t.segments for p in s.points
        ]
        if not pts:
            raise ValueError("GPX-filene inneholder ingen sporpunkter")
        if all(p.time for p in pts):
            pts.sort(key=lambda p: p.time)
        for prev, cur in zip(pts, pts[1:]):
            cur.dist = prev.dist + haversine_distance(prev.lat, prev.lon, cur.lat, cur.lon)
        self.points = pts
        self.has_time = all(p.time for p in pts)
        self._times = [p.time for p in pts] if self.has_time else []

    @property
    def start(self) -> datetime | None:
        return self.points[0].time

    @property
    def end(self) -> datetime | None:
        return self.points[-1].time

    @property
    def length(self) -> float:
        return self.points[-1].dist

    def position_at(self, t: datetime, tolerance=timedelta(minutes=15)) -> Point | None:
        """Interpolated position at time t, or None if t is outside the track."""
        if not self.has_time or t < self.start - tolerance or t > self.end + tolerance:
            return None
        i = bisect.bisect_left(self._times, t)
        if i == 0:
            return self.points[0]
        if i >= len(self.points):
            return self.points[-1]
        a, b = self.points[i - 1], self.points[i]
        span = (b.time - a.time).total_seconds()
        f = 0.0 if span <= 0 else (t - a.time).total_seconds() / span
        ele = None if a.ele is None or b.ele is None else a.ele + f * (b.ele - a.ele)
        return Point(a.lat + f * (b.lat - a.lat), a.lon + f * (b.lon - a.lon), ele, t, a.dist + f * (b.dist - a.dist))

    def nearest(self, lat: float, lon: float, near_time: datetime | None = None,
                window=timedelta(minutes=30)) -> tuple[Point, float]:
        """Nearest track point and the distance (m) to it.

        With near_time, points close in time are preferred, so a photo on an out-and-back
        route lands on the leg it was actually taken on.
        """
        candidates = self.points
        if near_time is not None and self.has_time:
            lo = bisect.bisect_left(self._times, near_time - window)
            hi = bisect.bisect_right(self._times, near_time + window)
            candidates = self.points[lo:hi] or self.points
        best = min(candidates, key=lambda p: (p.lat - lat) ** 2 + ((p.lon - lon) * 0.5) ** 2)
        dist = haversine_distance(lat, lon, best.lat, best.lon)
        if candidates is not self.points and dist > 500:  # time looks wrong; fall back to position only
            return self.nearest(lat, lon)
        return best, dist

    def sample(self, every_m: float) -> list[Point]:
        out, next_d = [], 0.0
        for p in self.points:
            if p.dist >= next_d:
                out.append(p)
                next_d = p.dist + every_m
        if out[-1] is not self.points[-1]:
            out.append(self.points[-1])
        return out

    def stats(self) -> dict:
        ud = self.gpx.get_uphill_downhill()
        with_ele = [p for p in self.points if p.ele is not None]
        highest = max(with_ele, key=lambda p: p.ele) if with_ele else None
        lowest = min(with_ele, key=lambda p: p.ele) if with_ele else None
        s = {
            "distance_km": round(self.length / 1000, 2),
            "ascent_m": round(ud.uphill) if with_ele else None,
            "descent_m": round(ud.downhill) if with_ele else None,
            "max_ele_m": round(highest.ele) if highest else None,
            "min_ele_m": round(lowest.ele) if lowest else None,
            "highest_point": (
                {"lat": highest.lat, "lon": highest.lon, "km": round(highest.dist / 1000, 2)} if highest else None
            ),
            "start": self.start.isoformat() if self.start else None,
            "end": self.end.isoformat() if self.end else None,
            "duration_s": None,
            "moving_s": None,
        }
        if self.has_time:
            s["duration_s"] = int((self.end - self.start).total_seconds())
            md = self.gpx.get_moving_data()
            if md:
                s["moving_s"] = int(md.moving_time)
        return s
