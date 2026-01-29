from __future__ import annotations

from dataclasses import dataclass, field
import json
import time
from typing import Iterable, List, Mapping, Optional
from urllib import request

from ..models import MmWaveMeasurement
from .mmwave import MmWaveIngestionError, parse_mmwave_measurements


@dataclass(frozen=True)
class MmWaveExporterError(RuntimeError):
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True)
class HTTPMmWaveExporterConfig:
    endpoint_url: str
    default_sensor_id: Optional[str] = None
    timeout_seconds: float = 2.0
    max_retries: int = 2
    retry_backoff_seconds: float = 0.5
    clock_offset_seconds: float = 0.0
    clock_drift_tolerance_seconds: float = 2.0
    max_clock_offset_seconds: float = 300.0
    drift_smoothing: float = 0.25
    source_name: str = "http_mmwave_exporter"
    source_metadata: Mapping[str, object] = field(default_factory=dict)
    default_metadata: Mapping[str, object] = field(default_factory=dict)


class HTTPMmWaveExporterAdapter:
    """Pull mmWave presence/motion events from an HTTP JSON exporter endpoint."""

    def __init__(self, config: HTTPMmWaveExporterConfig) -> None:
        self._config = config
        self._clock_offset_seconds = config.clock_offset_seconds

    def fetch(self) -> List[MmWaveMeasurement]:
        fetch_time = time.time()
        payload = self._fetch_payload()
        normalized = self._normalize_payload(payload, fetch_time)
        return parse_mmwave_measurements(normalized)

    def _fetch_payload(self) -> Iterable[Mapping[str, object]]:
        for attempt in range(self._config.max_retries + 1):
            try:
                with request.urlopen(
                    self._config.endpoint_url, timeout=self._config.timeout_seconds
                ) as response:
                    body = response.read().decode("utf-8")
                break
            except Exception as exc:  # pragma: no cover - network error path
                if attempt >= self._config.max_retries:
                    raise MmWaveExporterError(
                        f"mmWave exporter request failed: {exc}"
                    ) from exc
                backoff = self._config.retry_backoff_seconds * (2**attempt)
                time.sleep(backoff)
        else:  # pragma: no cover - defensive
            raise MmWaveExporterError("mmWave exporter request failed with no response.")

        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise MmWaveExporterError(
                f"mmWave exporter returned invalid JSON: {exc}"
            ) from exc

        if not isinstance(payload, list):
            raise MmWaveExporterError(
                "mmWave exporter payload must be a JSON list of measurements."
            )

        return payload

    def _normalize_payload(
        self, payload: Iterable[Mapping[str, object]], fetch_time: float
    ) -> List[Mapping[str, object]]:
        normalized: List[Mapping[str, object]] = []
        for idx, item in enumerate(payload):
            if not isinstance(item, Mapping):
                raise MmWaveExporterError(
                    f"mmWave exporter measurement #{idx} must be an object."
                )

            entry = dict(item)
            if "sensor_id" not in entry and self._config.default_sensor_id:
                entry["sensor_id"] = self._config.default_sensor_id

            entry["timestamp"] = self._normalize_timestamp(entry, fetch_time)
            entry["metadata"] = self._merge_metadata(entry.get("metadata"))
            normalized.append(entry)

        return normalized

    def _normalize_timestamp(self, entry: Mapping[str, object], fetch_time: float) -> float:
        timestamp = entry.get("timestamp")
        if timestamp is None and "timestamp_ms" in entry:
            try:
                timestamp = float(entry["timestamp_ms"]) / 1000.0
            except (TypeError, ValueError) as exc:
                raise MmWaveExporterError(
                    "mmWave exporter timestamp_ms must be numeric."
                ) from exc
        if timestamp is None:
            timestamp = fetch_time
        try:
            raw_timestamp = float(timestamp)
        except (TypeError, ValueError) as exc:
            raise MmWaveExporterError(
                "mmWave exporter timestamp must be numeric."
            ) from exc

        corrected = raw_timestamp + self._clock_offset_seconds
        drift = fetch_time - corrected
        if abs(drift) > self._config.clock_drift_tolerance_seconds:
            proposed_offset = self._clock_offset_seconds + drift
            if abs(proposed_offset) <= self._config.max_clock_offset_seconds:
                smoothing = min(max(self._config.drift_smoothing, 0.0), 1.0)
                self._clock_offset_seconds = (
                    self._clock_offset_seconds * (1.0 - smoothing)
                    + proposed_offset * smoothing
                )
                corrected = raw_timestamp + self._clock_offset_seconds
        return corrected

    def _merge_metadata(self, metadata: Optional[object]) -> Mapping[str, object]:
        if metadata is None:
            base: dict[str, object] = {}
        elif isinstance(metadata, Mapping):
            base = dict(metadata)
        else:
            raise MmWaveIngestionError(
                "mmWave exporter metadata must be a mapping when provided."
            )

        merged = {
            "source": self._config.source_name,
            "endpoint": self._config.endpoint_url,
        }
        if self._config.default_sensor_id:
            merged["sensor_id"] = self._config.default_sensor_id
        merged.update(self._config.source_metadata)
        merged.update(self._config.default_metadata)
        merged.update(base)
        return merged
