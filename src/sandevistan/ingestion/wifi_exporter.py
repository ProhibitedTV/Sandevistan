from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Iterable, List, Mapping, Optional
from urllib import request

from ..config import SensorConfig
from ..models import WiFiMeasurement
from .wifi import WiFiIngestionError, parse_wifi_measurements


@dataclass(frozen=True)
class WiFiExporterError(RuntimeError):
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True)
class HTTPWiFiExporterConfig:
    endpoint_url: str
    access_point_id: str
    timeout_seconds: float = 2.0
    default_metadata: Mapping[str, object] = field(default_factory=dict)


class HTTPWiFiExporterAdapter:
    """Pull Wi-Fi RSSI/CSI telemetry from an HTTP JSON exporter endpoint."""

    def __init__(self, config: HTTPWiFiExporterConfig, sensor_config: SensorConfig) -> None:
        self._config = config
        self._sensor_config = sensor_config

    def fetch(self) -> List[WiFiMeasurement]:
        """Fetch and normalize RSSI/CSI measurements from the exporter."""
        payload = self._fetch_payload()
        normalized = self._normalize_payload(payload)
        return parse_wifi_measurements(normalized, self._sensor_config)

    def _fetch_payload(self) -> Iterable[Mapping[str, object]]:
        try:
            with request.urlopen(
                self._config.endpoint_url, timeout=self._config.timeout_seconds
            ) as response:
                body = response.read().decode("utf-8")
        except Exception as exc:
            raise WiFiExporterError(
                f"Wi-Fi exporter request failed: {exc}"
            ) from exc

        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise WiFiExporterError(
                f"Wi-Fi exporter returned invalid JSON: {exc}"
            ) from exc

        if not isinstance(payload, list):
            raise WiFiExporterError(
                "Wi-Fi exporter payload must be a JSON list of measurements."
            )

        return payload

    def _normalize_payload(
        self, payload: Iterable[Mapping[str, object]]
    ) -> List[Mapping[str, object]]:
        normalized: List[Mapping[str, object]] = []
        for idx, item in enumerate(payload):
            if not isinstance(item, Mapping):
                raise WiFiExporterError(
                    f"Wi-Fi exporter measurement #{idx} must be an object."
                )

            entry = dict(item)
            if "access_point_id" not in entry:
                entry["access_point_id"] = self._config.access_point_id

            if "timestamp" not in entry and "timestamp_ms" in entry:
                try:
                    entry["timestamp"] = float(entry["timestamp_ms"]) / 1000.0
                except (TypeError, ValueError) as exc:
                    raise WiFiExporterError(
                        "Wi-Fi exporter timestamp_ms must be numeric."
                    ) from exc

            entry["metadata"] = self._merge_metadata(entry.get("metadata"))
            normalized.append(entry)

        return normalized

    def _merge_metadata(self, metadata: Optional[object]) -> Mapping[str, object]:
        if metadata is None:
            base: dict[str, object] = {}
        elif isinstance(metadata, Mapping):
            base = dict(metadata)
        else:
            raise WiFiIngestionError(
                "Wi-Fi exporter metadata must be a mapping when provided."
            )

        merged = {
            "source": "http_exporter",
            "endpoint": self._config.endpoint_url,
        }
        merged.update(self._config.default_metadata)
        merged.update(base)
        return merged
