"""AIS "type of ship and cargo" codes (phase 17a), grouped into labels.

Source: ITU-R M.1371 ship type table, as reproduced in the US Coast Guard
Navigation Center AIS encoding guide (navcen.uscg.gov). Only the groups the
map needs are named; the exact code is always kept as well.

Real data does not always follow the table: the captured sample has a ship
reporting type 7, which the table does not define. Such codes are "unknown".
"""

FISHING = "Fishing"

_EXACT = {
    30: FISHING,
    31: "Towing",
    32: "Towing",
    33: "Dredger",
    34: "Diving",
    35: "Military",
    36: "Sailing",
    37: "Pleasure craft",
    50: "Pilot",
    51: "Search and rescue",
    52: "Tug",
    53: "Port tender",
    54: "Anti-pollution",
    55: "Law enforcement",
    58: "Medical transport",
}
_RANGES = [
    (20, 29, "Wing in ground"),
    (40, 49, "High-speed craft"),
    (60, 69, "Passenger"),
    (70, 79, "Cargo"),
    (80, 89, "Tanker"),
    (90, 99, "Other"),
]


def ship_type_label(code: int | None) -> str:
    """Human label for a type code; "" when not available (None or 0)."""
    if not code:
        return ""
    if code in _EXACT:
        return _EXACT[code]
    for low, high, label in _RANGES:
        if low <= code <= high:
            return label
    return f"Unknown ({code})"
