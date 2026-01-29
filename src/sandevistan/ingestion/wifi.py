from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Mapping, Optional, Sequence

from ..config import SensorConfig
from ..models import WiFiMeasurement


@dataclass(frozen=True)
class WiFiIngestionError(ValueError):
    message: str

    def __str__(self) -> str:
        return self.message


def parse_wifi_measurements(
    raw_measurements: Iterable[Mapping[str, object]],
    sensor_config: SensorConfig,
) -> List[WiFiMeasurement]:
    """Parse raw Wi-Fi payloads into WiFiMeasurement objects.

    Raises WiFiIngestionError with actionable context when validation fails.
    """
    measurements: List[WiFiMeasurement] = []
    last_timestamp_by_ap: dict[str, float] = {}

    for idx, raw in enumerate(raw_measurements):
        access_point_id = _require_str(raw, "access_point_id", idx)
        timestamp = _require_float(raw, "timestamp", idx, access_point_id)
        rssi = _require_float(raw, "rssi", idx, access_point_id, timestamp)

        if access_point_id not in sensor_config.wifi_access_points:
            raise WiFiIngestionError(
                _format_message(
                    "Unknown access point; update SensorConfig before ingestion.",
                    access_point_id,
                    timestamp,
                )
            )

        last_timestamp = last_timestamp_by_ap.get(access_point_id)
        if last_timestamp is not None and timestamp < last_timestamp:
            raise WiFiIngestionError(
                _format_message(
                    (
                        "Timestamp out of order for Wi-Fi measurement; "
                        f"previous timestamp was {last_timestamp:.3f}."
                    ),
                    access_point_id,
                    timestamp,
                )
            )
        last_timestamp_by_ap[access_point_id] = timestamp

        csi = _optional_float_sequence(raw.get("csi"), "csi", access_point_id, timestamp)
        metadata = raw.get("metadata")
        if metadata is not None and not isinstance(metadata, Mapping):
            raise WiFiIngestionError(
                _format_message(
                    "metadata must be a mapping when provided.",
                    access_point_id,
                    timestamp,
                )
            )

        measurements.append(
            WiFiMeasurement(
                timestamp=timestamp,
                access_point_id=access_point_id,
                rssi=rssi,
                csi=csi,
                metadata=dict(metadata) if isinstance(metadata, Mapping) else None,
            )
        )

    return measurements


def _require_str(raw: Mapping[str, object], field: str, idx: int) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or not value:
        raise WiFiIngestionError(
            f"Wi-Fi measurement #{idx} missing required field '{field}'."
        )
    return value


def _require_float(
    raw: Mapping[str, object],
    field: str,
    idx: int,
    access_point_id: Optional[str] = None,
    timestamp: Optional[float] = None,
) -> float:
    value = raw.get(field)
    try:
        return float(value)
    except (TypeError, ValueError):
        sensor_label = access_point_id or "unknown"
        timestamp_label = "unknown" if timestamp is None else f"{timestamp:.3f}"
        raise WiFiIngestionError(
            _format_message(
                f"Invalid or missing '{field}' field; received {value!r}.",
                sensor_label,
                timestamp_label,
            )
        )


def _optional_float_sequence(
    value: object,
    field: str,
    access_point_id: str,
    timestamp: float,
) -> Optional[Sequence[float]]:
    if value is None:
        return None
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes)):
        raise WiFiIngestionError(
            _format_message(
                f"{field} must be a sequence of floats when provided.",
                access_point_id,
                timestamp,
            )
        )
    converted: List[float] = []
    for item in value:
        try:
            converted.append(float(item))
        except (TypeError, ValueError):
            raise WiFiIngestionError(
                _format_message(
                    f"{field} contains non-numeric values.",
                    access_point_id,
                    timestamp,
                )
            )
    return converted


def _format_message(message: str, access_point_id: object, timestamp: object) -> str:
    return (
        f"Wi-Fi ingestion error: {message} "
        f"(sensor_id={access_point_id}, timestamp={timestamp})."
    )
