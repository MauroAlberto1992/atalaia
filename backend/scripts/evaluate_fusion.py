"""Evaluate the AIS + sensor fusion against the simulator's ground truth.

Run from backend/:  python scripts/evaluate_fusion.py [--hours 6]

Everything here is SIMULATED: synthetic AIS ships with constant velocity
inside the patrol area, the scripted dark targets from config/sensors.toml,
and clutter. AIS reports reach the fusion with a random delay, like the sparse
real feed measured in phase 12 (about 30 reports per ship per hour).

Reported per scenario:
- dark targets confirmed, and how long after first entering the footprint;
- false dark contacts: confirmed contacts that were really clutter;
- AIS ships wrongly reported as dark;
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
            "lag_s": 0.0,
        }
        for i in range(n)
    ]


def ship_position(s: dict[str, float], hours: float) -> tuple[float, float]:
    d = s["sog"] * hours
    north, east = d * math.cos(math.radians(s["cog"])), d * math.sin(math.radians(s["cog"]))
    lat = s["lat"] + north / 60
    return lat, s["lon"] + east / (60 * math.cos(math.radians(lat)))


def run(
    cfg: SensorsConfig, hours: float, ships_n: int, max_ais_lag_min: float, seed: int
) -> dict[str, object]:
    rng = random.Random(seed)
    sim = DroneSimulator(cfg, T0)
    fusion = FusionEngine(cfg.fusion)
    ships = synthetic_ships(cfg, ships_n, rng)
    sweeps = int(hours * 3600 / cfg.drone.sweep_s)

    first_in_footprint: dict[str, datetime] = {}
    confirmed_at: dict[str, datetime] = {}
    assoc: Counter[str] = Counter()  # right / wrong / missed for AIS-ship detections
    confirmed_truths: Counter[str] = Counter()

    for k in range(sweeps):
        t = T0 + timedelta(seconds=cfg.drone.sweep_s * k)
        h = (t - T0).total_seconds() / 3600
        # The fusion sees each ship's last AIS report, which is `lag` old.
        tracks = []
        truth_tracks = []
        for s in ships:
            if rng.random() < 0.05:  # a new report arrives now and then
                s["lag_s"] = rng.uniform(0, max_ais_lag_min * 60)
            lag_h = s["lag_s"] / 3600
            lat_now, lon_now = ship_position(s, h)
            lat_rep, lon_rep = ship_position(s, max(0.0, h - lag_h))
            common = dict(
                mmsi=int(s["mmsi"]),
                ship_name="",
                sog=s["sog"],
                cog=s["cog"] if s["sog"] > 0 else 360.0,
                true_heading=511,
                navigational_status=0,
            )
            truth_tracks.append(Track(latitude=lat_now, longitude=lon_now, last_seen=t, **common))
            tracks.append(
                Track(
                    latitude=lat_rep,
                    longitude=lon_rep,
                    last_seen=t - timedelta(seconds=s["lag_s"]),
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
        ("default (Pd 0.9, 0.5 clutter/sweep, AIS lag <= 3 min)", base, 3.0),
        ("harder (Pd 0.7, 2 clutter/sweep)", variant(pd=0.7, false_alarms_per_sweep=2.0), 3.0),
        ("sparse AIS (lag up to 15 min, as on the real feed at times)", base, 15.0),
    ]
    for title, cfg, lag in scenarios:
        print(f"\n== {title}, {args.hours:g} h, {args.ships} AIS ships ==")
        for key, value in run(cfg, args.hours, args.ships, lag, seed=42).items():
            print(f"  {key:30} {value}")


if __name__ == "__main__":
    main()
