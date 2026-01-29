from __future__ import annotations

from dataclasses import dataclass, field
import json
import time
from typing import IO, Iterable, List, Mapping, Optional

from ..models import MmWaveMeasurement
from .mmwave import MmWaveIngestionError, parse_mmwave_measurements


@dataclass(frozen=True)
class MmWaveSerialError(RuntimeError):
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True)
class SerialMmWaveConfig:
    port: str
    baudrate: int = 115200
    timeout_seconds: float = 0.5
    max_lines: int = 50
    default_sensor_id: Optional[str] = None
    clock_offset_seconds: float = 0.0
    source_name: str = "serial_mmwave"
    source_metadata: Mapping[str, object] = field(default_factory=dict)
    default_metadata: Mapping[str, object] = field(default_factory=dict)


class SerialMmWaveAdapter:
    """Read mmWave presence/motion events from a serial-connected sensor."""

    def __init__(self, config: SerialMmWaveConfig, stream: Optional[IO[str]] = None) -> None:
        self._config = config
        self._clock_offset_seconds = config.clock_offset_seconds
        self._stream = stream
        self._serial = None

    def fetch(self) -> List[MmWaveMeasurement]:
        read_time = time.time()
        lines = self._read_lines()
        normalized = self._normalize_lines(lines, read_time)
        return parse_mmwave_measurements(normalized)

    def _read_lines(self) -> List[str]:
        stream = self._ensure_stream()
        lines: List[str] = []
        for _ in range(self._config.max_lines):
            line = stream.readline()
            if not line:
                break
            if isinstance(line, bytes):
                line = line.decode("utf-8", errors="replace")
            lines.append(line)
        return lines

    def _ensure_stream(self) -> IO[str]:
        if self._stream is not None:
            return self._stream
        if self._serial is None:
            try:
                import serial  # type: ignore[import-not-found]
            except ImportError as exc:  # pragma: no cover - optional dependency
                raise MmWaveSerialError(
                    "pyserial is required to read mmWave data over UART/USB."
                ) from exc
            self._serial = serial.Serial(
                self._config.port,
                baudrate=self._config.baudrate,
                timeout=self._config.timeout_seconds,
            )
        return self._serial

    def _normalize_lines(
        self, lines: Iterable[str], read_time: float
    ) -> List[Mapping[str, object]]:
        normalized: List[Mapping[str, object]] = []
        for idx, raw_line in enumerate(lines):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            entry = self._parse_line(line, idx)
            if entry is None:
                continue
            entry = dict(entry)
            if "sensor_id" not in entry and self._config.default_sensor_id:
                entry["sensor_id"] = self._config.default_sensor_id
            if "event_type" in entry:
                entry["event_type"] = str(entry["event_type"]).lower()
            if "confidence" in entry:
                entry["confidence"] = self._normalize_confidence(entry["confidence"], idx)
            entry["timestamp"] = self._normalize_timestamp(entry, read_time)
            entry["metadata"] = self._merge_metadata(entry.get("metadata"))
            normalized.append(entry)
        return normalized

    def _parse_line(self, line: str, idx: int) -> Optional[Mapping[str, object]]:
        if line.lstrip().startswith("{"):
            return self._parse_json_line(line, idx)
        if "=" in line:
            return self._parse_kv_line(line, idx)
        return self._parse_csv_line(line, idx)

    def _parse_json_line(self, line: str, idx: int) -> Mapping[str, object]:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise MmWaveSerialError(
                f"Serial mmWave line #{idx} is not valid JSON: {exc}"
            ) from exc
        if not isinstance(payload, Mapping):
            raise MmWaveSerialError(
                f"Serial mmWave line #{idx} must be a JSON object."
            )
        return payload

    def _parse_csv_line(self, line: str, idx: int) -> Mapping[str, object]:
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 4:
            raise MmWaveSerialError(
                f"Serial mmWave line #{idx} must have at least 4 CSV fields."
            )
        payload: dict[str, object] = {
            "timestamp_ms": self._parse_float(parts[0], "timestamp_ms", idx),
            "sensor_id": parts[1],
            "event_type": parts[2],
            "confidence": self._parse_float(parts[3], "confidence", idx),
        }
        if len(parts) > 4 and parts[4]:
            payload["range_meters"] = self._parse_float(parts[4], "range_meters", idx)
        if len(parts) > 5 and parts[5]:
            payload["angle_degrees"] = self._parse_float(parts[5], "angle_degrees", idx)
        return payload

    def _parse_kv_line(self, line: str, idx: int) -> Mapping[str, object]:
        payload: dict[str, object] = {}
        parts = [part.strip() for part in line.split(",") if part.strip()]
        for part in parts:
            if "=" not in part:
                raise MmWaveSerialError(
                    f"Serial mmWave line #{idx} has invalid key-value segment: {part!r}."
                )
            key, value = part.split("=", 1)
            payload[key.strip()] = self._coerce_value(value.strip())
        return payload

    def _normalize_timestamp(self, entry: Mapping[str, object], read_time: float) -> float:
        timestamp = entry.get("timestamp")
        if timestamp is None and "timestamp_ms" in entry:
            timestamp = entry.get("timestamp_ms")
            try:
                timestamp = float(timestamp) / 1000.0
            except (TypeError, ValueError) as exc:
                raise MmWaveSerialError(
                    "Serial mmWave timestamp_ms must be numeric."
                ) from exc
        if timestamp is None:
            timestamp = read_time
        try:
            raw_timestamp = float(timestamp)
        except (TypeError, ValueError) as exc:
            raise MmWaveSerialError("Serial mmWave timestamp must be numeric.") from exc
        return raw_timestamp + self._clock_offset_seconds

    def _normalize_confidence(self, value: object, idx: int) -> float:
        try:
            confidence = float(value)
        except (TypeError, ValueError) as exc:
            raise MmWaveSerialError(
                f"Serial mmWave line #{idx} confidence must be numeric."
            ) from exc
        if confidence > 1.0 and confidence <= 100.0:
            confidence /= 100.0
        return confidence

    def _merge_metadata(self, metadata: Optional[object]) -> Mapping[str, object]:
        if metadata is None:
            base: dict[str, object] = {}
        elif isinstance(metadata, Mapping):
            base = dict(metadata)
        else:
            raise MmWaveIngestionError(
                "Serial mmWave metadata must be a mapping when provided."
            )
        merged = {
            "source": self._config.source_name,
            "port": self._config.port,
        }
        if self._config.default_sensor_id:
            merged["sensor_id"] = self._config.default_sensor_id
        merged.update(self._config.source_metadata)
        merged.update(self._config.default_metadata)
        merged.update(base)
        return merged

    @staticmethod
    def _parse_float(value: str, field: str, idx: int) -> float:
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise MmWaveSerialError(
                f"Serial mmWave line #{idx} field '{field}' must be numeric."
            ) from exc

    @staticmethod
    def _coerce_value(value: str) -> object:
        lowered = value.lower()
        if lowered in {"true", "false"}:
            return lowered == "true"
        try:
            if any(token in value for token in (".", "e", "E")):
                return float(value)
            return int(value)
        except ValueError:
            return value
