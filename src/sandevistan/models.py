from __future__ import annotations

from dataclasses import dataclass
import math
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
class MmWaveMeasurement:
    timestamp: float
    sensor_id: str
    confidence: float
    event_type: str
    range_meters: Optional[float] = None
    angle_radians: Optional[float] = None
    metadata: Optional[dict] = None


@dataclass(frozen=True)
class BLEMeasurement:
    timestamp: float
    rssi: float
    device_id: Optional[str] = None
    hashed_identifier: Optional[str] = None
    channel: Optional[int] = None
    manufacturer_data: Optional[dict] = None


def validate_mmwave_measurement(measurement: MmWaveMeasurement) -> None:
    if not measurement.sensor_id:
        raise ValueError("mmWave sensor_id must be set.")
    if measurement.timestamp < 0:
        raise ValueError("mmWave timestamp must be non-negative.")
    if not 0.0 <= measurement.confidence <= 1.0:
        raise ValueError("mmWave confidence must be between 0 and 1.")
    if measurement.event_type not in {"presence", "motion"}:
        raise ValueError("mmWave event_type must be 'presence' or 'motion'.")
    if measurement.range_meters is not None and measurement.range_meters < 0:
        raise ValueError("mmWave range_meters must be non-negative when provided.")
    if measurement.angle_radians is not None:
        if not -math.pi <= measurement.angle_radians <= math.pi:
            raise ValueError("mmWave angle_radians must be between -pi and pi.")


def validate_ble_measurement(measurement: BLEMeasurement) -> None:
    if not measurement.device_id and not measurement.hashed_identifier:
        raise ValueError("BLE measurement must include device_id or hashed_identifier.")
    if measurement.timestamp < 0:
        raise ValueError("BLE timestamp must be non-negative.")
    if not math.isfinite(measurement.rssi):
        raise ValueError("BLE rssi must be a finite number.")
    if measurement.channel is not None and measurement.channel not in {37, 38, 39}:
        raise ValueError("BLE channel must be 37, 38, or 39 when provided.")


@dataclass(frozen=True)
class FusionInput:
    wifi: Sequence[WiFiMeasurement]
    vision: Sequence[Detection]
    mmwave: Sequence[MmWaveMeasurement]
    ble: Sequence[BLEMeasurement]


@dataclass(frozen=True)
class TrackState:
    track_id: str
    timestamp: float
    position: Tuple[float, float]
    velocity: Optional[Tuple[float, float]]
    uncertainty: Tuple[float, float]
    confidence: float
