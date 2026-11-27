"""Phase 16: areas drawn by operators. Validation, the alert engine, the API."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from minicop.alerts import AlertEngine
from minicop.api import create_app
from minicop.config import Area
from minicop.events import PositionEvent, Track
from minicop.user_zones import UserZoneIn, polygon_problem

T0 = datetime(2026, 11, 27, 20, 0, tzinfo=UTC)
# A box offshore the Algarve, ~5.4 nm x 6 nm.
BOX = [(36.90, -8.50), (36.90, -8.40), (36.81, -8.40), (36.81, -8.50)]
ALGARVE = Area(name="Algarve", boxes=[((36.5, -9.0), (37.2, -7.4))])


def ship(mmsi: int, lat: float, lon: float, t: datetime = T0) -> Track:
    return Track(
        mmsi=mmsi,
        ship_name=f"S{mmsi}",
        latitude=lat,
        longitude=lon,
        sog=8.0,
        cog=90.0,
        true_heading=511,
        navigational_status=0,
        last_seen=t,
    )


# ---- polygon validation ---------------------------------------------------------


def test_a_plain_box_is_fine():
    assert polygon_problem(BOX, ALGARVE) is None


def test_crossing_edges_are_refused():
    bow_tie = [BOX[0], BOX[2], BOX[1], BOX[3]]  # diagonals cross in the middle
    assert "cross" in (polygon_problem(bow_tie, ALGARVE) or "")


def test_repeated_points_are_refused():
    assert polygon_problem([BOX[0], BOX[1], BOX[0]], ALGARVE) is not None


def test_points_outside_the_monitored_area_are_refused():
    madeira = [(32.7, -16.9), (32.7, -16.8), (32.6, -16.85)]
    assert "outside" in (polygon_problem(madeira, ALGARVE) or "")


def test_concave_polygon_is_fine():
    l_shape = [
        (36.9, -8.5),
        (36.9, -8.4),
        (36.85, -8.4),
        (36.85, -8.45),
        (36.8, -8.45),
        (36.8, -8.5),
    ]
    assert polygon_problem(l_shape, ALGARVE) is None


# ---- alert engine ---------------------------------------------------------------


def area(name: str = "Watch box") -> UserZoneIn:
    return UserZoneIn(name=name, kind="watch", polygon=BOX)


def test_ship_already_inside_a_new_area_does_not_alert():
    engine = AlertEngine([])
    inside = ship(1, 36.85, -8.45)
    engine.on_track(inside)
    engine.add_zone(area().to_zone(), [inside])
    later = inside.model_copy(update={"last_seen": T0 + timedelta(minutes=1)})
    assert engine.on_track(later) == []


def test_ship_entering_a_new_area_alerts_once():
    engine = AlertEngine([])
    outside = ship(2, 36.85, -8.55)  # ~2.4 nm west of the box
    engine.on_track(outside)
    engine.add_zone(area().to_zone(), [outside])
    # 8 kn east for 20 min = 2.7 nm: now inside.
    inside = ship(2, 36.85, -8.494, T0 + timedelta(minutes=20))
    alerts = engine.on_track(inside)
    assert [a.kind for a in alerts] == ["enter"]
    assert alerts[0].zone == "Watch box"


def test_removed_area_raises_no_exit_and_no_more_alerts():
    engine = AlertEngine([])
    engine.add_zone(area().to_zone(), [])
    engine.on_track(ship(3, 36.85, -8.45))  # enters
    engine.remove_zone("Watch box")
    assert engine.zones == []
    assert engine.on_track(ship(3, 36.85, -8.55, T0 + timedelta(minutes=20))) == []


# ---- API ------------------------------------------------------------------------


def post(client: TestClient, name: str = "Watch box", polygon=BOX, kind: str = "watch"):
    return client.post("/zones", json={"name": name, "kind": kind, "polygon": polygon})


def wait(client: TestClient, app) -> None:
    async def drain():
        await app.state.runtime.events.join()

    client.portal.call(drain)


def test_create_list_and_delete_an_area():
    app = create_app(ingest=False, zones=[])
    with TestClient(app) as client:
        r = post(client)
        assert r.status_code == 201
        assert r.json()["saved"] is False  # no database in unit tests
        wait(client, app)
        zones = client.get("/zones").json()
        assert [(z["name"], z["source"], z["alert_on_entry"]) for z in zones] == [
            ("Watch box", "user", True)
        ]
        assert post(client).status_code == 409  # same name
        assert client.delete("/zones/Watch box").status_code == 204
        wait(client, app)
        assert client.get("/zones").json() == []
        assert client.delete("/zones/Watch box").status_code == 404


def test_invalid_area_is_refused_with_a_reason():
    app = create_app(ingest=False, zones=[])
    with TestClient(app) as client:
        r = post(client, polygon=[BOX[0], BOX[2], BOX[1], BOX[3]])
        assert r.status_code == 422 and "cross" in r.json()["detail"]
        assert post(client, polygon=BOX[:2]).status_code == 422  # too few points
        assert post(client, kind="party").status_code == 422


def test_config_zones_cannot_be_deleted():
    from minicop.zones import Zone

    fixed = Zone(name="Fixed", kind="restricted", alert_on_entry=True, polygon=BOX)
    app = create_app(ingest=False, zones=[fixed])
    with TestClient(app) as client:
        assert client.delete("/zones/Fixed").status_code == 409
        assert post(client, name="Fixed").status_code == 409


def test_live_clients_are_told_when_areas_change_and_entries_alert():
    app = create_app(ingest=False, zones=[])
    with TestClient(app) as client, client.websocket_connect("/live") as ws:
        ws.receive_json()  # snapshot
        post(client)
        assert ws.receive_json() == {"type": "zones"}

        async def feed():
            rt = app.state.runtime
            await rt.events.put(
                PositionEvent(
                    mmsi=9,
                    latitude=36.85,
                    longitude=-8.45,
                    sog=8.0,
                    cog=90.0,
                    true_heading=511,
                    navigational_status=0,
                    ship_name="NEWCOMER",
                    received_at=T0,
                )
            )
            await rt.events.join()

        client.portal.call(feed)
        kinds = [a["kind"] for a in client.get("/alerts").json()]
        assert kinds == ["enter"]  # first seen inside an existing area = entering


def test_dark_contact_inside_an_area_alerts_once():
    """A scripted dark target crossing a drawn area raises dark_in_zone."""
    from minicop.events import SensorTick

    app = create_app(ingest=False, zones=[], simulated_sensor=True)
    with TestClient(app) as client:
        # Around DARK-1's path (config/sensors.toml): along 36.92-36.93 N.
        assert (
            post(
                client, polygon=[(36.95, -8.72), (36.95, -8.20), (36.90, -8.20), (36.90, -8.72)]
            ).status_code
            == 201
        )
        start = app.state.runtime.sensor.sim.start

        async def sweep(k: int) -> None:
            await app.state.runtime.events.put(SensorTick(now=start + timedelta(seconds=30 * k)))
            await app.state.runtime.events.join()

        def dark_in_zone() -> list[dict]:
            return [a for a in client.get("/alerts").json() if a["kind"] == "dark_in_zone"]

        k = 1
        while not dark_in_zone() and k < 360:
            client.portal.call(sweep, k)
            k += 1
        # Ten more sweeps (5 min) with the contact still inside: no repeats.
        for extra in range(10):
            client.portal.call(sweep, k + extra)
        hits = dark_in_zone()
        assert len(hits) == 1
        assert hits[0]["zone"] == "Watch box" and "SIMULATED" in hits[0]["message"]
