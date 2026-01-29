from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import hashlib
import time
from typing import Iterable, List, Mapping, Optional, Sequence

from .ble import parse_ble_measurements
from ..models import BLEMeasurement


@dataclass(frozen=True)
class BleakScannerAdapterError(RuntimeError):
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True)
class BleakScannerConfig:
    adapter_name: str
    scan_timeout_seconds: float = 2.0
    offline: bool = False
    offline_payloads: Sequence[Mapping[str, object]] = field(default_factory=tuple)
    include_hashed_identifier: bool = True


class BleakScannerAdapter:
    """Collect BLE advertisements via bleak and normalize for BLE ingestion."""

    def __init__(self, config: BleakScannerConfig) -> None:
        self._config = config

    def scan(self) -> List[Mapping[str, object]]:
        """Return raw scan payloads formatted for parse_ble_measurements."""
        if self._config.offline:
            return self._normalize_offline_payloads()
        return self._scan_bleak()

    def fetch(self) -> List[BLEMeasurement]:
        """Return parsed BLE measurements from the latest scan."""
        return parse_ble_measurements(self.scan())

    def _scan_bleak(self) -> List[Mapping[str, object]]:
        from bleak import BleakScanner

        discoveries = asyncio.run(self._discover(BleakScanner))
        return self._normalize_discoveries(discoveries)

    async def _discover(self, scanner: type) -> Sequence[object]:
        return await scanner.discover(
            timeout=self._config.scan_timeout_seconds,
            return_adv=True,
        )

    def _normalize_offline_payloads(self) -> List[Mapping[str, object]]:
        normalized: List[Mapping[str, object]] = []
        for idx, item in enumerate(self._config.offline_payloads):
            if not isinstance(item, Mapping):
                raise BleakScannerAdapterError(
                    f"Offline BLE payload #{idx} must be a mapping."
                )
            entry = dict(item)
            entry.setdefault("timestamp", time.time())

            device_id = _optional_str(entry.get("device_id"))
            hashed_identifier = _optional_str(entry.get("hashed_identifier"))
            if not device_id and not hashed_identifier:
                raise BleakScannerAdapterError(
                    f"Offline BLE payload #{idx} must include device_id or hashed_identifier."
                )
            if self._config.include_hashed_identifier and device_id and not hashed_identifier:
                entry["hashed_identifier"] = _hash_identifier(device_id)
            entry.setdefault("adapter", self._config.adapter_name)
            if "rssi" not in entry:
                raise BleakScannerAdapterError(
                    f"Offline BLE payload #{idx} must include rssi."
                )
            normalized.append(entry)
        return normalized

    def _normalize_discoveries(self, discoveries: Sequence[object]) -> List[Mapping[str, object]]:
        normalized: List[Mapping[str, object]] = []
        timestamp = time.time()
        for idx, item in enumerate(discoveries):
            device, advertisement = _split_discovery(item)
            device_id = _resolve_device_identifier(device, advertisement)
            if not device_id:
                raise BleakScannerAdapterError(
                    f"BLE discovery #{idx} missing device identifier."
                )
            rssi = _resolve_rssi(device, advertisement)
            if rssi is None:
                raise BleakScannerAdapterError(
                    f"BLE discovery #{idx} missing RSSI value for {device_id}."
                )
            entry: dict[str, object] = {
                "timestamp": timestamp,
                "rssi": rssi,
                "device_id": device_id,
                "adapter": self._config.adapter_name,
            }
            manufacturer_data = _resolve_manufacturer_data(device, advertisement)
            if manufacturer_data is not None:
                entry["manufacturer_data"] = manufacturer_data
            if self._config.include_hashed_identifier:
                entry["hashed_identifier"] = _hash_identifier(device_id)
            normalized.append(entry)
        return normalized


def _split_discovery(item: object) -> tuple[object, Optional[object]]:
    if isinstance(item, tuple) and len(item) == 2:
        return item[0], item[1]
    return item, None


def _optional_str(value: object) -> Optional[str]:
    if isinstance(value, str) and value:
        return value
    return None


def _resolve_device_identifier(device: object, advertisement: Optional[object]) -> Optional[str]:
    for candidate in (
        getattr(device, "address", None),
        getattr(device, "name", None),
        getattr(advertisement, "local_name", None),
    ):
        identifier = _optional_str(candidate)
        if identifier:
            return identifier
    metadata = getattr(device, "metadata", None)
    if isinstance(metadata, Mapping):
        identifier = _optional_str(metadata.get("identifier"))
        if identifier:
            return identifier
    return None


def _resolve_rssi(device: object, advertisement: Optional[object]) -> Optional[float]:
    for candidate in (
        getattr(advertisement, "rssi", None),
        getattr(device, "rssi", None),
    ):
        if candidate is None:
            continue
        try:
            return float(candidate)
        except (TypeError, ValueError):
            continue
    return None


def _resolve_manufacturer_data(
    device: object, advertisement: Optional[object]
) -> Optional[dict]:
    manufacturer_data = getattr(advertisement, "manufacturer_data", None)
    if isinstance(manufacturer_data, Mapping):
        return dict(manufacturer_data)
    metadata = getattr(device, "metadata", None)
    if isinstance(metadata, Mapping) and isinstance(metadata.get("manufacturer_data"), Mapping):
        return dict(metadata["manufacturer_data"])
    return None


def _hash_identifier(identifier: str) -> str:
    return hashlib.sha256(identifier.encode("utf-8")).hexdigest()
