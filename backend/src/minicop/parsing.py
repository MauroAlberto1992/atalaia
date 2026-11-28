"""Turn raw aisstream frames into validated models. Never raises on bad input:
the stream must keep flowing, so bad frames are logged and dropped."""

import logging
from datetime import UTC, datetime

from pydantic import ValidationError

from minicop.events import PositionEvent, StaticEvent
from minicop.models import AisEnvelope, PositionReport

log = logging.getLogger(__name__)


def has_valid_position(lat: float, lon: float) -> bool:
    # AIS uses lat=91 / lon=181 as "not available"; the range check covers both.
    return -90 <= lat <= 90 and -180 <= lon <= 180


# aisstream message types that carry a position, and the AIS class they come from.
POSITION_TYPES = {
    "PositionReport": "A",  # messages 1/2/3
    "StandardClassBPositionReport": "B",  # message 18
    "ExtendedClassBPositionReport": "B",  # message 19 (not seen in the captured sample)
}


# Static data (phase 17a). Field names checked on captured real frames in
# tests/fixtures/captured/ (ShipStaticData_*.json, StaticDataReport_*.json).
STATIC_TYPES = ("ShipStaticData", "StaticDataReport")


def parse_static(raw: str | bytes) -> StaticEvent | None:
    """Ship type and draught from a static message, or None if the frame is not
    one or carries neither. Class B message 24 comes in two parts: part A
    (PartNumber false) has only the name, part B has the ship type."""
    try:
        envelope = AisEnvelope.model_validate_json(raw)
        if envelope.message_type not in STATIC_TYPES:
            return None
        body = envelope.message[envelope.message_type]
        mmsi = int(body["UserID"])
        if envelope.message_type == "ShipStaticData":
            ship_type = int(body.get("Type") or 0) or None
            # Metres in the captured frames (e.g. 10.6 for a cargo ship); 0 = not available.
            draught = float(body.get("MaximumStaticDraught") or 0) or None
        else:
            part_b = body.get("ReportB") or {}
            if not body.get("PartNumber") or not part_b.get("Valid"):
                return None  # part A: name only
            ship_type = int(part_b.get("ShipType") or 0) or None
            draught = None
    except (ValidationError, KeyError, TypeError, ValueError) as exc:
        log.warning("Dropping malformed static frame: %s | frame: %.200s", exc, raw)
        return None
    if ship_type is None and draught is None:
        return None
    return StaticEvent(mmsi=mmsi, ship_type=ship_type, draught_m=draught)


def parse_position(raw: str | bytes) -> PositionReport | None:
    """Return a PositionReport, or None if the frame is not a usable position."""
    try:
        envelope = AisEnvelope.model_validate_json(raw)
    except ValidationError as exc:  # also covers malformed JSON
        err = exc.errors()[0]
        # loc is the path to the bad field, e.g. ('MetaData', 'time_utc').
        log.warning("Dropping invalid frame: %s at %s | frame: %.200s", err["msg"], err["loc"], raw)
        return None

    ais_class = POSITION_TYPES.get(envelope.message_type)
    if ais_class is None:
        return None

    try:
        report = PositionReport.model_validate(envelope.message[envelope.message_type])
    except (KeyError, ValidationError) as exc:
        log.warning("Dropping malformed %s: %s", envelope.message_type, exc)
        return None
    report.ais_class = ais_class

    if not has_valid_position(report.latitude, report.longitude):
        return None
    return report


def parse_aisstream_time(value: str) -> datetime:
    """Parse aisstream's Go-style timestamp, e.g.
    "2026-11-24 21:30:12.123456789 +0000 UTC".

    Python's datetime only holds microseconds, so the fraction is cut to
    6 digits. The offset is always +0000, so we return UTC directly.
    """
    date_part, time_part = value.split()[:2]
    whole, _, fraction = time_part.partition(".")
    fraction = (fraction + "000000")[:6]  # pad or truncate to microseconds
    naive = datetime.fromisoformat(f"{date_part}T{whole}.{fraction}")
    return naive.replace(tzinfo=UTC)


def parse_event(raw: str | bytes) -> PositionEvent | None:
    """Like parse_position, but returns a PositionEvent with metadata and time."""
    report = parse_position(raw)
    if report is None:
        return None
    # parse_position already validated the envelope; parse it again for metadata.
    # Cheap enough at AIS rates, and keeps parse_position simple for the script.
    envelope = AisEnvelope.model_validate_json(raw)
    if envelope.metadata is None:
        log.warning("Dropping PositionReport without MetaData (mmsi=%s)", report.mmsi)
        return None
    try:
        received_at = parse_aisstream_time(envelope.metadata.time_utc)
    except ValueError:
        log.warning("Dropping frame with bad time_utc: %r", envelope.metadata.time_utc)
        return None
    return PositionEvent(
        mmsi=report.mmsi,
        latitude=report.latitude,
        longitude=report.longitude,
        sog=report.sog,
        cog=report.cog,
        true_heading=report.true_heading,
        navigational_status=report.navigational_status,
        ais_class=report.ais_class,
        ship_name=envelope.metadata.ship_name.strip(),  # AIS pads names with spaces
        received_at=received_at,
    )
