from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, List, Mapping, Optional

from ..models import BLEMeasurement, validate_ble_measurement


@dataclass(frozen=True)
class BLEIngestionError(ValueError):
    message: str

    def __str__(self) -> str:
        return self.message


class BLEAdvertisementScanner:
    """Scan for BLE advertisements and normalize them into BLEMeasurement objects."""

    def __init__(
        self,
        scan: Callable[[], Iterable[Mapping[str, object]]],
    ) -> None:
        self._scan = scan

    def fetch(self) -> List[BLEMeasurement]:
        return parse_ble_measurements(self._scan())


def parse_ble_measurements(
    raw_measurements: Iterable[Mapping[str, object]],
) -> List[BLEMeasurement]:
    """Parse raw BLE advertisement payloads into BLEMeasurement objects."""
    measurements: List[BLEMeasurement] = []
    last_timestamp_by_device: dict[str, float] = {}

    for idx, raw in enumerate(raw_measurements):
        timestamp = _require_float(raw, "timestamp", idx)
        rssi = _require_float(raw, "rssi", idx, timestamp)
        device_id = _optional_str(raw.get("device_id"))
        hashed_identifier = _optional_str(raw.get("hashed_identifier"))
        if not device_id and not hashed_identifier:
            raise BLEIngestionError(
                f"BLE measurement #{idx} missing device_id or hashed_identifier."
            )

        channel = _optional_channel(raw.get("channel"), device_id, hashed_identifier)
        manufacturer_data = _normalize_manufacturer_data(
            raw.get("manufacturer_data"), device_id, hashed_identifier
        )

        device_key = device_id or hashed_identifier or "unknown"
        last_timestamp = last_timestamp_by_device.get(device_key)
        if last_timestamp is not None and timestamp < last_timestamp:
            raise BLEIngestionError(
                _format_message(
                    (
                        "Timestamp out of order for BLE measurement; "
                        f"previous timestamp was {last_timestamp:.3f}."
                    ),
                    device_key,
                    timestamp,
                )
            )
        last_timestamp_by_device[device_key] = timestamp

        measurement = BLEMeasurement(
            timestamp=timestamp,
            rssi=rssi,
            device_id=device_id,
            hashed_identifier=hashed_identifier,
            channel=channel,
            manufacturer_data=manufacturer_data,
        )
        try:
            validate_ble_measurement(measurement)
        except ValueError as exc:
            raise BLEIngestionError(
                _format_message(str(exc), device_key, timestamp)
            ) from exc

        measurements.append(measurement)

    return measurements


def _require_float(
    raw: Mapping[str, object],
    field: str,
    idx: int,
    timestamp: Optional[float] = None,
) -> float:
    value = raw.get(field)
    try:
        return float(value)
    except (TypeError, ValueError):
        timestamp_label = "unknown" if timestamp is None else f"{timestamp:.3f}"
        raise BLEIngestionError(
            _format_message(
                f"Invalid or missing '{field}' field; received {value!r}.",
                "unknown",
                timestamp_label,
            )
        )


def _optional_str(value: object) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str) and value:
        return value
    return None


def _optional_channel(
    value: object,
    device_id: Optional[str],
    hashed_identifier: Optional[str],
) -> Optional[int]:
    if value is None:
        return None
    try:
        channel = int(value)
    except (TypeError, ValueError):
        raise BLEIngestionError(
            _format_message(
                f"Invalid channel value; received {value!r}.",
                device_id or hashed_identifier or "unknown",
                "unknown",
            )
        )
    return channel


def _normalize_manufacturer_data(
    value: object,
    device_id: Optional[str],
    hashed_identifier: Optional[str],
) -> Optional[dict]:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, (bytes, bytearray)):
        return {"raw_hex": value.hex()}
    if isinstance(value, str) and value:
        return {"raw": value}
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes, bytearray)):
        try:
            payload = bytes(int(item) for item in value)
        except (TypeError, ValueError):
            payload = b""
        if payload:
            return {"raw_hex": payload.hex()}
    raise BLEIngestionError(
        _format_message(
            "manufacturer_data must be a mapping or bytes-like payload when provided.",
            device_id or hashed_identifier or "unknown",
            "unknown",
        )
    )


def _format_message(message: str, device_id: object, timestamp: object) -> str:
    return (
        f"BLE ingestion error: {message} "
        f"(device_id={device_id}, timestamp={timestamp})."
    )
