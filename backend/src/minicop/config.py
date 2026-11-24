"""Runtime settings: secrets from .env, areas of interest from areas.toml."""

import os
import tomllib
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

# backend/src/minicop/config.py -> parents[2] is backend/, parents[3] is the repo root.
BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent
DEFAULT_AREAS_FILE = BACKEND_DIR / "config" / "areas.toml"

# A corner is (latitude, longitude) — aisstream order, latitude first.
Corner = tuple[float, float]


# (south-west, north-east)
Box = tuple[Corner, Corner]


class Area(BaseModel):
    name: str
    boxes: list[Box] = Field(min_length=1)


class Settings(BaseModel):
    api_key: str
    area: Area


class ConfigError(Exception):
    """Raised when configuration is missing or invalid."""


def load_area(name: str, areas_file: Path = DEFAULT_AREAS_FILE) -> Area:
    with areas_file.open("rb") as f:  # tomllib requires binary mode
        areas = tomllib.load(f).get("areas", {})
    if name not in areas:
        raise ConfigError(f"Unknown area '{name}'. Available: {', '.join(sorted(areas))}")
    return Area(name=name, **areas[name])


def load_settings(areas_file: Path = DEFAULT_AREAS_FILE) -> Settings:
    # Values already set in the real environment win over .env.
    load_dotenv(REPO_ROOT / ".env")
    api_key = os.getenv("AISSTREAM_API_KEY", "").strip()
    if not api_key:
        raise ConfigError("AISSTREAM_API_KEY is not set (copy .env.example to .env)")
    area_name = os.getenv("MINICOP_AREA", "algarve").strip()
    return Settings(api_key=api_key, area=load_area(area_name, areas_file))
