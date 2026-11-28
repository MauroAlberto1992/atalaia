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


def distance_to_polygon_nm(lat: float, lon: float, polygon: list[tuple[float, float]]) -> float:
    """Distance from a point to the nearest edge of a polygon, in nautical
    miles (0 is not returned for inside points: check point_in_polygon first).

    Uses a local flat projection around the point (1 minute of latitude =
    1 nm, longitude scaled by cos(lat)), accurate for distances of a few nm.
    """
    kx = 60 * math.cos(math.radians(lat))  # nm per degree of longitude here
    ky = 60.0  # nm per degree of latitude
    best = math.inf
    n = len(polygon)
    for i in range(n):
        (lat1, lon1), (lat2, lon2) = polygon[i], polygon[(i + 1) % n]
        # Segment and point in local nm coordinates, with the point at the origin.
        ax, ay = (lon1 - lon) * kx, (lat1 - lat) * ky
        bx, by = (lon2 - lon) * kx, (lat2 - lat) * ky
        dx, dy = bx - ax, by - ay
        length2 = dx * dx + dy * dy
        # Closest point on the segment to the origin, clamped to its ends.
        t = 0.0 if length2 == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / length2))
        cx, cy = ax + t * dx, ay + t * dy
        best = min(best, math.hypot(cx, cy))
    return best


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


def project(
    lat: float, lon: float, sog_kn: float, cog_deg: float, hours: float
) -> tuple[float, float]:
    """Position after `hours` at constant speed and course (flat approximation,
    fine for the few nm a ship covers between reports). COG >= 360 means "not
    available": then the ship is assumed to stay put."""
    if cog_deg >= 360 or sog_kn <= 0 or hours <= 0:
        return lat, lon
    dist_nm = sog_kn * hours
    north = dist_nm * math.cos(math.radians(cog_deg))
    east = dist_nm * math.sin(math.radians(cog_deg))
    return lat + north / 60, lon + east / (60 * math.cos(math.radians(lat)))
