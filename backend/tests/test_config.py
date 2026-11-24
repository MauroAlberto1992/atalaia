import pytest

from minicop.config import ConfigError, load_area, load_settings


def test_algarve_bbox_is_lat_first():
    area = load_area("algarve")
    (lat_min, lon_min), (lat_max, lon_max) = area.bbox
    # Algarve: latitude ~37N, longitude ~8W. If the order were swapped this fails.
    assert 36 < lat_min < lat_max < 38
    assert -10 < lon_min < lon_max < -7


def test_unknown_area_raises():
    with pytest.raises(ConfigError, match="Unknown area"):
        load_area("atlantis")


def test_missing_api_key_raises(monkeypatch):
    # Set to empty so load_dotenv (which never overrides existing vars) can't fill it.
    monkeypatch.setenv("AISSTREAM_API_KEY", "")
    with pytest.raises(ConfigError, match="AISSTREAM_API_KEY"):
        load_settings()
