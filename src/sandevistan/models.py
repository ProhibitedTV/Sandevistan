from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence, Tuple


@dataclass(frozen=True)
class WiFiMeasurement:
    timestamp: float
    access_point_id: str
    rssi: float
    csi: Optional[Sequence[float]] = None
    metadata: Optional[dict] = None


@dataclass(frozen=True)
class Detection:
    timestamp: float
    camera_id: str
    bbox: Tuple[float, float, float, float]
    confidence: float
    keypoints: Optional[Sequence[Tuple[float, float]]] = None


@dataclass(frozen=True)
class FusionInput:
    wifi: Sequence[WiFiMeasurement]
    vision: Sequence[Detection]


@dataclass(frozen=True)
class TrackState:
    track_id: str
    timestamp: float
    position: Tuple[float, float]
    velocity: Optional[Tuple[float, float]]
    uncertainty: Tuple[float, float]
    confidence: float
