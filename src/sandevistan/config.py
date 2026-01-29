from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass(frozen=True)
class SensorConfig:
    wifi_access_points: Dict[str, Tuple[float, float]]
    cameras: Dict[str, Tuple[float, float]]


@dataclass(frozen=True)
class SpaceConfig:
    width_meters: float
    height_meters: float
    coordinate_origin: Tuple[float, float] = (0.0, 0.0)
