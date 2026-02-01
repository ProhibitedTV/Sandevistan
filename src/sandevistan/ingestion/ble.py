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
    last_timestamp: Optional[float] = None

    for idx, raw in enumerate(raw_measurements):
        timestamp = _require_float(raw, "timestamp", idx)
        rssi = _require_float(raw, "rssi", idx, timestamp)
        adapter_id = _optional_str(raw.get("adapter_id") or raw.get("adapter"))

        channel = _optional_channel(raw.get("channel"), adapter_id)
        manufacturer_data = _normalize_manufacturer_data(raw.get("manufacturer_data"), adapter_id)

        if last_timestamp is not None and timestamp < last_timestamp:
            raise BLEIngestionError(
                _format_message(
                    (
                        "Timestamp out of order for BLE measurement; "
                        f"previous timestamp was {last_timestamp:.3f}."
                    ),
                    adapter_id or "scan",
                    timestamp,
                )
            )
        last_timestamp = timestamp

        measurement = BLEMeasurement(
            timestamp=timestamp,
            rssi=rssi,
            channel=channel,
            manufacturer_data=manufacturer_data,
            adapter_id=adapter_id,
        )
        try:
            validate_ble_measurement(measurement)
        except ValueError as exc:
            raise BLEIngestionError(
                _format_message(str(exc), adapter_id or "scan", timestamp)
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
    adapter_id: Optional[str],
) -> Optional[int]:
    if value is None:
        return None
    try:
        channel = int(value)
    except (TypeError, ValueError):
        raise BLEIngestionError(
            _format_message(
                f"Invalid channel value; received {value!r}.",
                adapter_id or "scan",
                "unknown",
            )
        )
    return channel


def _normalize_manufacturer_data(
    value: object,
    adapter_id: Optional[str],
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
            adapter_id or "scan",
            "unknown",
        )
    )


def _format_message(message: str, source: object, timestamp: object) -> str:
    return (
        f"BLE ingestion error: {message} "
        f"(source={source}, timestamp={timestamp})."
    )
