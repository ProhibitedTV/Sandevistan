from __future__ import annotations

"""Local Wi-Fi capture via iw/nl80211 scans with optional CSI collection."""

from dataclasses import dataclass, field
import json
import subprocess
import time
from typing import Iterable, List, Mapping, Optional, Sequence, Tuple

from ..config import SensorConfig
from ..models import WiFiMeasurement
from .wifi import parse_wifi_measurements


@dataclass(frozen=True)
class LocalWiFiCaptureError(RuntimeError):
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True)
class LocalWiFiCaptureConfig:
    interface_name: str
    access_point_id: str
    target_bssid: Optional[str] = None
    target_ssid: Optional[str] = None
    scan_timeout_seconds: float = 2.0
    scan_command: Optional[Sequence[str]] = None
    csi_command: Optional[Sequence[str]] = None
    csi_timeout_seconds: float = 1.0
    clock_offset_seconds: float = 0.0
    source_name: str = "local_wifi"
    source_metadata: Mapping[str, object] = field(default_factory=dict)
    default_metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class _ScanResult:
    bssid: str
    signal_dbm: float
    ssid: Optional[str] = None
    frequency_mhz: Optional[int] = None


class LocalWiFiCaptureAdapter:
    """Capture Wi-Fi RSSI/CSI samples locally via iw/nl80211 or a CSI-capable NIC."""

    def __init__(self, config: LocalWiFiCaptureConfig, sensor_config: SensorConfig) -> None:
        self._config = config
        self._sensor_config = sensor_config
        self._last_timestamp_by_ap: dict[str, float] = {}

    def fetch(self) -> List[WiFiMeasurement]:
        scan_time = time.time()
        scan_result = self._read_scan_result()
        measurement = self._build_measurement(scan_result, scan_time)
        normalized = parse_wifi_measurements([measurement], self._sensor_config)
        self._validate_monotonic(normalized)
        return normalized

    def _read_scan_result(self) -> _ScanResult:
        command = (
            list(self._config.scan_command)
            if self._config.scan_command
            else ["iw", "dev", self._config.interface_name, "scan"]
        )
        output = self._run_command(
            command,
            self._config.scan_timeout_seconds,
            "Wi-Fi scan",
        )
        results = _parse_iw_scan(output)
        return _select_scan_result(
            results,
            target_bssid=self._config.target_bssid,
            target_ssid=self._config.target_ssid,
        )

    def _build_measurement(
        self, scan_result: _ScanResult, scan_time: float
    ) -> Mapping[str, object]:
        timestamp = scan_time + self._config.clock_offset_seconds
        csi_values, csi_timestamp = self._read_csi()
        if csi_timestamp is not None:
            timestamp = csi_timestamp + self._config.clock_offset_seconds
        metadata = self._merge_metadata(scan_result)

        measurement: dict[str, object] = {
            "timestamp": timestamp,
            "access_point_id": self._config.access_point_id,
            "rssi": scan_result.signal_dbm,
            "metadata": metadata,
        }
        if csi_values is not None:
            measurement["csi"] = csi_values
        return measurement

    def _read_csi(self) -> Tuple[Optional[Sequence[float]], Optional[float]]:
        if not self._config.csi_command:
            return None, None
        output = self._run_command(
            list(self._config.csi_command),
            self._config.csi_timeout_seconds,
            "CSI capture",
        )
        return _parse_csi_output(output)

    def _merge_metadata(self, scan_result: _ScanResult) -> Mapping[str, object]:
        base = {
            "source": self._config.source_name,
            "interface": self._config.interface_name,
            "bssid": scan_result.bssid,
        }
        if scan_result.ssid:
            base["ssid"] = scan_result.ssid
        if scan_result.frequency_mhz is not None:
            base["frequency_mhz"] = scan_result.frequency_mhz
        base.update(self._config.source_metadata)
        base.update(self._config.default_metadata)
        return base

    def _run_command(self, command: Sequence[str], timeout: float, label: str) -> str:
        try:
            completed = subprocess.run(
                list(command),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise LocalWiFiCaptureError(f"{label} command timed out.") from exc
        if completed.returncode != 0:
            stderr = completed.stderr.strip()
            detail = f": {stderr}" if stderr else ""
            raise LocalWiFiCaptureError(
                f"{label} command failed with exit code {completed.returncode}{detail}"
            )
        return completed.stdout

    def _validate_monotonic(self, measurements: Iterable[WiFiMeasurement]) -> None:
        for measurement in measurements:
            last_timestamp = self._last_timestamp_by_ap.get(measurement.access_point_id)
            if last_timestamp is not None and measurement.timestamp < last_timestamp:
                raise LocalWiFiCaptureError(
                    "Local Wi-Fi capture produced out-of-order timestamps "
                    f"for {measurement.access_point_id} (last={last_timestamp:.3f}, "
                    f"current={measurement.timestamp:.3f})."
                )
            self._last_timestamp_by_ap[measurement.access_point_id] = measurement.timestamp


def _parse_iw_scan(output: str) -> List[_ScanResult]:
    results: List[_ScanResult] = []
    current: dict[str, object] = {}
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if line.startswith("BSS "):
            if current:
                results.append(_build_scan_result(current))
                current = {}
            parts = line.split()
            if len(parts) >= 2:
                current["bssid"] = parts[1].strip()
            continue
        if not current:
            continue
        if line.startswith("signal:"):
            parts = line.split()
            if len(parts) >= 2:
                current["signal_dbm"] = _parse_float(parts[1], "signal")
        elif line.startswith("SSID:"):
            current["ssid"] = line.split(":", 1)[1].strip() or None
        elif line.startswith("freq:"):
            parts = line.split()
            if len(parts) >= 2:
                current["frequency_mhz"] = int(_parse_float(parts[1], "freq"))
    if current:
        results.append(_build_scan_result(current))
    return results


def _build_scan_result(entry: Mapping[str, object]) -> _ScanResult:
    bssid = entry.get("bssid")
    if not isinstance(bssid, str) or not bssid:
        raise LocalWiFiCaptureError("Wi-Fi scan output missing BSSID entries.")
    signal_dbm = entry.get("signal_dbm")
    if not isinstance(signal_dbm, (float, int)):
        raise LocalWiFiCaptureError(
            f"Wi-Fi scan output missing signal for BSSID {bssid}."
        )
    ssid = entry.get("ssid") if isinstance(entry.get("ssid"), str) else None
    frequency_mhz = entry.get("frequency_mhz")
    if frequency_mhz is not None and not isinstance(frequency_mhz, int):
        frequency_mhz = int(float(frequency_mhz))
    return _ScanResult(
        bssid=bssid,
        signal_dbm=float(signal_dbm),
        ssid=ssid,
        frequency_mhz=frequency_mhz,
    )


def _select_scan_result(
    results: Sequence[_ScanResult],
    target_bssid: Optional[str],
    target_ssid: Optional[str],
) -> _ScanResult:
    if not results:
        raise LocalWiFiCaptureError("Wi-Fi scan returned no access points.")
    if target_bssid:
        for result in results:
            if result.bssid.lower() == target_bssid.lower():
                return result
        raise LocalWiFiCaptureError(
            f"Wi-Fi scan did not find target BSSID {target_bssid}."
        )
    if target_ssid:
        candidates = [result for result in results if result.ssid == target_ssid]
        if not candidates:
            raise LocalWiFiCaptureError(
                f"Wi-Fi scan did not find target SSID {target_ssid}."
            )
        return max(candidates, key=lambda item: item.signal_dbm)
    return max(results, key=lambda item: item.signal_dbm)


def _parse_csi_output(output: str) -> Tuple[Optional[Sequence[float]], Optional[float]]:
    content = None
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if line:
            content = line
    if not content:
        raise LocalWiFiCaptureError("CSI capture returned empty output.")

    if content.lstrip().startswith(("{", "[")):
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise LocalWiFiCaptureError("CSI capture output is not valid JSON.") from exc
    else:
        payload = [segment for segment in content.split() if segment]

    timestamp = _extract_timestamp(payload)
    csi_values = _extract_csi_values(payload)
    if csi_values is None:
        raise LocalWiFiCaptureError("CSI capture output missing csi values.")
    return csi_values, timestamp


def _extract_timestamp(payload: object) -> Optional[float]:
    if isinstance(payload, Mapping):
        timestamp = payload.get("timestamp")
        if timestamp is None and "timestamp_ms" in payload:
            timestamp = payload.get("timestamp_ms")
            try:
                return float(timestamp) / 1000.0
            except (TypeError, ValueError) as exc:
                raise LocalWiFiCaptureError(
                    "CSI capture timestamp_ms must be numeric."
                ) from exc
        if timestamp is None:
            return None
        try:
            return float(timestamp)
        except (TypeError, ValueError) as exc:
            raise LocalWiFiCaptureError("CSI capture timestamp must be numeric.") from exc
    return None


def _extract_csi_values(payload: object) -> Optional[Sequence[float]]:
    if isinstance(payload, Mapping):
        candidate = payload.get("csi")
        if candidate is None:
            candidate = payload.get("csi_values")
        return _coerce_float_sequence(candidate)
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
        return _coerce_float_sequence(payload)
    return None


def _coerce_float_sequence(value: object) -> Optional[Sequence[float]]:
    if value is None:
        return None
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes)):
        raise LocalWiFiCaptureError("CSI capture values must be a sequence of numbers.")
    flattened: List[float] = []
    for item in value:
        if isinstance(item, Iterable) and not isinstance(item, (str, bytes)):
            for nested in item:
                flattened.append(_parse_float(nested, "csi"))
        else:
            flattened.append(_parse_float(item, "csi"))
    return flattened


def _parse_float(value: object, label: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise LocalWiFiCaptureError(
            f"Local Wi-Fi capture {label} value must be numeric."
        ) from exc
