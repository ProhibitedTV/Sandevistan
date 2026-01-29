from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional, Sequence, Tuple


@dataclass(frozen=True)
class CameraIntrinsics:
    focal_length: Tuple[float, float]
    principal_point: Tuple[float, float]
    skew: float = 0.0


@dataclass(frozen=True)
class CameraExtrinsics:
    translation: Tuple[float, float]
    rotation_radians: float = 0.0


@dataclass(frozen=True)
class CameraCalibration:
    intrinsics: CameraIntrinsics
    extrinsics: CameraExtrinsics


@dataclass(frozen=True)
class AccessPointCalibration:
    position: Tuple[float, float]
    position_uncertainty_meters: float


@dataclass(frozen=True)
class SensorConfig:
    wifi_access_points: Dict[str, AccessPointCalibration]
    cameras: Dict[str, CameraCalibration]


@dataclass(frozen=True)
class SpaceConfig:
    width_meters: float
    height_meters: float
    coordinate_origin: Tuple[float, float] = (0.0, 0.0)


@dataclass(frozen=True)
class RetentionConfig:
    """Retention policy for in-memory measurements and audit logs.

    Retention is opt-in; set ``enabled=True`` and supply TTL values to activate.
    """

    enabled: bool = False
    measurement_ttl_seconds: Optional[float] = None
    log_ttl_seconds: Optional[float] = None
    cleanup_interval_seconds: float = 60.0

    def is_enabled(self) -> bool:
        return self.enabled and bool(self.measurement_ttl_seconds or self.log_ttl_seconds)


@dataclass(frozen=True)
class IngestionConfig:
    """Typed representation of ingestion sources in the JSON config."""

    wifi_sources: Sequence[Mapping[str, object]] = field(default_factory=tuple)
    vision_sources: Sequence[Mapping[str, object]] = field(default_factory=tuple)
    mmwave_sources: Sequence[Mapping[str, object]] = field(default_factory=tuple)
    ble_sources: Sequence[Mapping[str, object]] = field(default_factory=tuple)
