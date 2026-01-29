from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, List, Mapping, Optional

from ..models import MmWaveMeasurement, validate_mmwave_measurement


@dataclass(frozen=True)
class MmWaveIngestionError(ValueError):
    message: str

    def __str__(self) -> str:
        return self.message


def parse_mmwave_measurements(
    raw_measurements: Iterable[Mapping[str, object]],
) -> List[MmWaveMeasurement]:
    """Parse raw mmWave payloads into MmWaveMeasurement objects."""
    measurements: List[MmWaveMeasurement] = []
    last_timestamp_by_sensor: dict[str, float] = {}

    for idx, raw in enumerate(raw_measurements):
        sensor_id = _require_str(raw, "sensor_id", idx)
        timestamp = _require_float(raw, "timestamp", idx, sensor_id)
        confidence = _require_float(raw, "confidence", idx, sensor_id, timestamp)
        event_type = _require_str(raw, "event_type", idx, sensor_id, timestamp)
        range_meters = _optional_float(raw.get("range_meters"), "range_meters", sensor_id, timestamp)
        angle_radians = _optional_angle(raw, sensor_id, timestamp)

        last_timestamp = last_timestamp_by_sensor.get(sensor_id)
        if last_timestamp is not None and timestamp < last_timestamp:
            raise MmWaveIngestionError(
                _format_message(
                    (
                        "Timestamp out of order for mmWave measurement; "
                        f"previous timestamp was {last_timestamp:.3f}."
                    ),
                    sensor_id,
                    timestamp,
                )
            )
        last_timestamp_by_sensor[sensor_id] = timestamp

        metadata = raw.get("metadata")
        if metadata is not None and not isinstance(metadata, Mapping):
            raise MmWaveIngestionError(
                _format_message(
                    "metadata must be a mapping when provided.",
                    sensor_id,
                    timestamp,
                )
            )

        measurement = MmWaveMeasurement(
            timestamp=timestamp,
            sensor_id=sensor_id,
            confidence=confidence,
            event_type=event_type,
            range_meters=range_meters,
            angle_radians=angle_radians,
            metadata=dict(metadata) if isinstance(metadata, Mapping) else None,
        )
        try:
            validate_mmwave_measurement(measurement)
        except ValueError as exc:
            raise MmWaveIngestionError(
                _format_message(str(exc), sensor_id, timestamp)
            ) from exc

        measurements.append(measurement)

    return measurements


def _require_str(
    raw: Mapping[str, object],
    field: str,
    idx: int,
    sensor_id: Optional[str] = None,
    timestamp: Optional[float] = None,
) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or not value:
        if sensor_id is None:
            raise MmWaveIngestionError(
                f"mmWave measurement #{idx} missing required field '{field}'."
            )
        sensor_label = sensor_id or "unknown"
        timestamp_label = "unknown" if timestamp is None else f"{timestamp:.3f}"
        raise MmWaveIngestionError(
            _format_message(
                f"Invalid or missing '{field}' field.",
                sensor_label,
                timestamp_label,
            )
        )
    return value


def _require_float(
    raw: Mapping[str, object],
    field: str,
    idx: int,
    sensor_id: Optional[str] = None,
    timestamp: Optional[float] = None,
) -> float:
    value = raw.get(field)
    try:
        return float(value)
    except (TypeError, ValueError):
        sensor_label = sensor_id or "unknown"
        timestamp_label = "unknown" if timestamp is None else f"{timestamp:.3f}"
        raise MmWaveIngestionError(
            _format_message(
                f"Invalid or missing '{field}' field; received {value!r}.",
                sensor_label,
                timestamp_label,
            )
        )


def _optional_float(
    value: object,
    field: str,
    sensor_id: str,
    timestamp: float,
) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        raise MmWaveIngestionError(
            _format_message(
                f"{field} must be numeric when provided.",
                sensor_id,
                timestamp,
            )
        )


def _optional_angle(
    raw: Mapping[str, object],
    sensor_id: str,
    timestamp: float,
) -> Optional[float]:
    if "angle_radians" in raw:
        return _optional_float(raw.get("angle_radians"), "angle_radians", sensor_id, timestamp)
    if "angle_degrees" in raw:
        degrees = _optional_float(raw.get("angle_degrees"), "angle_degrees", sensor_id, timestamp)
        if degrees is None:
            return None
        return math.radians(degrees)
    return None


def _format_message(message: str, sensor_id: object, timestamp: object) -> str:
    return (
        f"mmWave ingestion error: {message} "
        f"(sensor_id={sensor_id}, timestamp={timestamp})."
    )
