"""Turn raw aisstream frames into validated models. Never raises on bad input:
the stream must keep flowing, so bad frames are logged and dropped."""

import logging

from pydantic import ValidationError

from minicop.models import AisEnvelope, PositionReport

log = logging.getLogger(__name__)


def has_valid_position(lat: float, lon: float) -> bool:
    # AIS uses lat=91 / lon=181 as "not available"; the range check covers both.
    return -90 <= lat <= 90 and -180 <= lon <= 180


def parse_position(raw: str | bytes) -> PositionReport | None:
    """Return a PositionReport, or None if the frame is not a usable position."""
    try:
        envelope = AisEnvelope.model_validate_json(raw)
    except ValidationError as exc:  # also covers malformed JSON
        err = exc.errors()[0]
        # loc is the path to the bad field, e.g. ('MetaData', 'time_utc').
        log.warning(
            "Dropping invalid frame: %s at %s | frame: %.200s", err["msg"], err["loc"], raw
        )
        return None

    if envelope.message_type != "PositionReport":
        return None

    try:
        report = PositionReport.model_validate(envelope.message["PositionReport"])
    except (KeyError, ValidationError) as exc:
        log.warning("Dropping malformed PositionReport: %s", exc)
        return None

    if not has_valid_position(report.latitude, report.longitude):
        return None
    return report
