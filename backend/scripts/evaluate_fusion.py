"""Evaluate the AIS + sensor fusion against the simulator's ground truth.

Run from backend/:  python scripts/evaluate_fusion.py [--hours 6]

Everything here is SIMULATED: synthetic AIS ships with constant velocity
bouncing inside the patrol area, the scripted dark targets from
config/sensors.toml, and clutter. Each ship's AIS reports get through at random,
on average every `report_every_min`: between reports the fusion only has the
last one, which keeps getting older (a sparse feed).

Reported per scenario:
- dark targets confirmed, and how long after first entering the footprint;
- false dark contacts: confirmed contacts that were really clutter;
- AIS ships wrongly reported as dark;
- contacts explained by recent AIS ("possible AIS", no alert): right MMSI or
  not, and dark targets hidden that way (the risk of the check);
- association accuracy: detections of AIS ships matched to the right MMSI.
"""

import argparse
import math
import random
from collections import Counter
from datetime import UTC, datetime, timedelta

from minicop.events import Track
from minicop.fusion import FusionEngine, associate
from minicop.geo import haversine_nm
from minicop.sensors import DroneSimulator, SensorsConfig, load_sensors_config

T0 = datetime(2026, 11, 27, 0, 0, tzinfo=UTC)


def synthetic_ships(cfg: SensorsConfig, n: int, rng: random.Random) -> list[dict[str, float]]:
    lats = [p[0] for p in cfg.drone.patrol]
    lons = [p[1] for p in cfg.drone.patrol]
    return [
        {
            "mmsi": 263900000 + i,
            "lat": rng.uniform(min(lats) - 0.05, max(lats) + 0.05),
            "lon": rng.uniform(min(lons) - 0.05, max(lons) + 0.05),
            "sog": rng.choice([0.0, 0.0, 3.0, 6.0, 10.0, 12.0]),
            "cog": rng.uniform(0, 360),
            "report_h": 0.0,  # time of the last AIS report (hours since T0)
        }
        for i in range(n)
    ]


def _bounce(x: float, lo: float, hi: float) -> tuple[float, int]:
    """Fold x into [lo, hi] like a ball bouncing between walls; also returns
    the direction sign (+1 / -1) at that point."""
    span = hi - lo
    k = (x - lo) % (2 * span)
    return (lo + k, 1) if k <= span else (hi - (k - span), -1)


def ship_state(
    s: dict[str, float], hours: float, box: tuple[float, float, float, float]
) -> tuple[float, float, float]:
    """(lat, lon, cog) of a synthetic ship at `hours`: constant speed, bouncing
    off the edges of the patrol box (+ margin), so moving ships stay near the
    drone for the whole run (before the review they sailed out within the
    first hour and long runs mostly measured stopped ships)."""
    d = s["sog"] * hours
    north, east = d * math.cos(math.radians(s["cog"])), d * math.sin(math.radians(s["cog"]))
    lat_min, lon_min, lat_max, lon_max = box
    lat, sn = _bounce(s["lat"] + north / 60, lat_min, lat_max)
    lon, se = _bounce(s["lon"] + east / (60 * math.cos(math.radians(lat))), lon_min, lon_max)
    cog = (math.degrees(math.atan2(se * east, sn * north)) + 360) % 360 if d else s["cog"]
    return lat, lon, cog


def run(
    cfg: SensorsConfig, hours: float, ships_n: int, report_every_min: float, seed: int
) -> dict[str, object]:
    rng = random.Random(seed)
    sim = DroneSimulator(cfg, T0)
    fusion = FusionEngine(cfg.fusion)
    ships = synthetic_ships(cfg, ships_n, rng)
    lats = [p[0] for p in cfg.drone.patrol]
    lons = [p[1] for p in cfg.drone.patrol]
    box = (min(lats) - 0.05, min(lons) - 0.05, max(lats) + 0.05, max(lons) + 0.05)
    sweeps = int(hours * 3600 / cfg.drone.sweep_s)
    # Chance per sweep that a ship's next report gets through: reports arrive
    # on average every `report_every_min`, so the age of each ship's last
    # report grows between them (a sparse feed), as on the real feed.
    p_report = min(1.0, cfg.drone.sweep_s / 60 / report_every_min)

    first_in_footprint: dict[str, datetime] = {}
    confirmed_at: dict[str, datetime] = {}
    assoc: Counter[str] = Counter()  # right / wrong / missed for AIS-ship detections
    confirmed_truths: Counter[str] = Counter()
    explained: dict[str, str] = {}  # contact id -> "right" / "wrong mmsi" / "dark" / "clutter"
    ages: list[float] = []

    for k in range(sweeps):
        t = T0 + timedelta(seconds=cfg.drone.sweep_s * k)
        h = (t - T0).total_seconds() / 3600
        tracks = []
        truth_tracks = []
        for s in ships:
            if rng.random() < p_report:
                s["report_h"] = h  # a new report reaches us now
            lat_now, lon_now, cog_now = ship_state(s, h, box)
            lat_rep, lon_rep, cog_rep = ship_state(s, s["report_h"], box)
            ages.append((h - s["report_h"]) * 60)
            common = dict(
                mmsi=int(s["mmsi"]),
                ship_name="",
                sog=s["sog"],
                true_heading=511,
                navigational_status=0,
            )
            truth_tracks.append(
                Track(
                    latitude=lat_now,
                    longitude=lon_now,
                    cog=cog_now if s["sog"] > 0 else 360.0,
                    last_seen=t,
                    **common,
                )
            )
            tracks.append(
                Track(
                    latitude=lat_rep,
                    longitude=lon_rep,
                    cog=cog_rep if s["sog"] > 0 else 360.0,
                    last_seen=T0 + timedelta(hours=s["report_h"]),
                    **common,
                )
            )

        sweep = sim.sweep(t, truth_tracks)  # the sensor sees where ships really are
        dlat, dlon = sweep.lat, sweep.lon
        for name, (lat, lon) in sim.dark_positions(t).items():
            if haversine_nm(dlat, dlon, lat, lon) <= cfg.drone.footprint_nm:
                first_in_footprint.setdefault(name, t)

        out = fusion.process(sweep, tracks)

        # Same association the engine just ran (deterministic), to score it.
        matched, _ = associate(sweep.detections, tracks, t, cfg.fusion)
        for i, d in enumerate(sweep.detections):
            if d.truth and d.truth.startswith("ais:"):
                mmsi = matched.get(i)
                assoc[
                    "missed" if mmsi is None else ("right" if f"ais:{mmsi}" == d.truth else "wrong")
                ] += 1

        for c in out.dark:
            if c.possible_mmsi is not None and c.id not in explained:
                cand = next(x for x in fusion._candidates if x.id == c.id)
                tr = Counter(p.truth for p in cand.points).most_common(1)[0][0] or "?"
                explained[c.id] = (
                    "right MMSI"
                    if tr == f"ais:{c.possible_mmsi}"
                    else "wrong MMSI"
                    if tr.startswith("ais:")
                    else tr.split(":")[0]
                )

        for dark in out.newly_confirmed:
            # Evaluation only: majority ground truth of the contact's detections.
            cand = next(c for c in fusion._candidates if c.id == dark.id)
            truth = Counter(p.truth for p in cand.points).most_common(1)[0][0] or "?"
            confirmed_truths[truth.split(":")[0]] += 1
            if truth.startswith("dark:"):
                confirmed_at.setdefault(truth[5:], t)

    latencies = {
        n: (confirmed_at[n] - first_in_footprint[n]).total_seconds() / 60
        for n in confirmed_at
        if n in first_in_footprint
    }
    total_assoc = sum(assoc.values()) or 1
    return {
        "dark targets": f"{len(confirmed_at)}/{len(cfg.dark_targets)} confirmed",
        "time to confirm (min)": {n: round(v, 1) for n, v in latencies.items()},
        "false dark (clutter)": confirmed_truths.get("clutter", 0),
        "AIS ships reported dark": confirmed_truths.get("ais", 0),
        "explained by recent AIS": dict(Counter(explained.values())),
        "AIS report age (median / 90th pct, min)": (
            f"{sorted(ages)[len(ages) // 2]:.1f} / {sorted(ages)[int(len(ages) * 0.9)]:.1f}"
        ),
        "AIS detections -> right MMSI": f"{100 * assoc['right'] / total_assoc:.1f}%",
        "-> wrong MMSI": f"{100 * assoc['wrong'] / total_assoc:.1f}%",
        "-> unassociated": f"{100 * assoc['missed'] / total_assoc:.1f}%",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate sensor fusion (SIMULATED).")
    parser.add_argument("--hours", type=float, default=6)
    parser.add_argument("--ships", type=int, default=40)
    args = parser.parse_args()
    base = load_sensors_config()

    def variant(**drone: float) -> SensorsConfig:
        return base.model_copy(update={"drone": base.drone.model_copy(update=drone)})

    scenarios = [
        ("default (Pd 0.9, 0.5 clutter/sweep, AIS report every ~1 min)", base, 1.0),
        ("harder (Pd 0.7, 2 clutter/sweep)", variant(pd=0.7, false_alarms_per_sweep=2.0), 1.0),
        ("sparse AIS (a report every ~8 min on average)", base, 8.0),
    ]
    for title, cfg, every in scenarios:
        print(f"\n== {title}, {args.hours:g} h, {args.ships} AIS ships ==")
        for key, value in run(cfg, args.hours, args.ships, every, seed=42).items():
            print(f"  {key:30} {value}")


if __name__ == "__main__":
    main()
