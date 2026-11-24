"""Geodesy helpers."""

import math

EARTH_RADIUS_NM = 3440.065  # mean Earth radius in nautical miles


def haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points, in nautical miles.

    Haversine treats the Earth as a sphere (error < 0.5% vs. the ellipsoid),
    which is plenty for ship tracks. Nautical miles because 1 knot = 1 nm/h,
    so distance / hours gives speed in knots directly.
    """
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * EARTH_RADIUS_NM * math.asin(math.sqrt(a))


def point_in_polygon(lat: float, lon: float, polygon: list[tuple[float, float]]) -> bool:
    """Ray casting: cast a ray from the point towards +longitude and count how
    many polygon edges it crosses. Odd = inside. Works for concave polygons.

    Treats lon/lat as flat x/y, which is fine for zones a few tens of km wide
    away from the poles and the antimeridian. Points exactly on an edge may go
    either way; for alerting that is irrelevant.
    """
    inside = False
    n = len(polygon)
    for i in range(n):
        lat1, lon1 = polygon[i]
        lat2, lon2 = polygon[(i + 1) % n]  # wraps: closes the polygon
        if (lat1 > lat) != (lat2 > lat):  # edge spans the point's latitude
            # Longitude where the edge crosses that latitude.
            cross_lon = lon1 + (lat - lat1) * (lon2 - lon1) / (lat2 - lat1)
            if lon < cross_lon:
                inside = not inside
    return inside
