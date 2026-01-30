from __future__ import annotations

import argparse
import json
import logging
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping, MutableMapping, Optional, Sequence

from .audit import AuditLogger
from .config import (
    AccessPointCalibration,
    CameraCalibration,
    CameraExtrinsics,
    CameraIntrinsics,
    MmWaveCalibration,
    RetentionConfig,
    SensorConfig,
    SpaceConfig,
)
from .ingestion import (
    HTTPMmWaveExporterAdapter,
    HTTPMmWaveExporterConfig,
    HTTPVisionExporterAdapter,
    HTTPVisionExporterConfig,
    HTTPWiFiExporterAdapter,
    HTTPWiFiExporterConfig,
    IngestionOrchestrator,
    LocalWiFiCaptureAdapter,
    LocalWiFiCaptureConfig,
    ProcessVisionExporterAdapter,
    ProcessVisionExporterConfig,
    SerialMmWaveAdapter,
    SerialMmWaveConfig,
)
from .models import BLEMeasurement, Detection, MmWaveMeasurement, TrackState, WiFiMeasurement
from .ingestion.ble import BLEAdvertisementScanner
from .ingestion.ble_scanner import BleakScannerAdapter, BleakScannerConfig
from .pipeline import FusionPipeline
from .retention import RetentionScheduler
from .sync import SyncBatch, SynchronizationBuffer

LOGGER = logging.getLogger(__name__)


class _MultiWiFiSource:
    def __init__(self, sources: Sequence[object]) -> None:
        self._sources = sources

    def fetch(self) -> Sequence[WiFiMeasurement]:
        measurements: list[WiFiMeasurement] = []
        for source in self._sources:
            try:
                measurements.extend(source.fetch())
            except Exception as exc:  # pragma: no cover - adapter failures
                LOGGER.exception("Wi-Fi source failed: %s", exc)
        return measurements


class _MultiVisionSource:
    def __init__(self, sources: Sequence[object]) -> None:
        self._sources = sources

    def fetch(self) -> Sequence[Detection]:
        detections: list[Detection] = []
        for source in self._sources:
            try:
                detections.extend(source.fetch())
            except Exception as exc:  # pragma: no cover - adapter failures
                LOGGER.exception("Vision source failed: %s", exc)
        return detections


class _MultiMmWaveSource:
    def __init__(self, sources: Sequence[object]) -> None:
        self._sources = sources

    def fetch(self) -> Sequence[MmWaveMeasurement]:
        measurements: list[MmWaveMeasurement] = []
        for source in self._sources:
            try:
                measurements.extend(source.fetch())
            except Exception as exc:  # pragma: no cover - adapter failures
                LOGGER.exception("mmWave source failed: %s", exc)
        return measurements


class _MultiBleSource:
    def __init__(self, sources: Sequence[object]) -> None:
        self._sources = sources

    def fetch(self) -> Sequence[BLEMeasurement]:
        measurements: list[BLEMeasurement] = []
        for source in self._sources:
            try:
                measurements.extend(source.fetch())
            except Exception as exc:  # pragma: no cover - adapter failures
                LOGGER.exception("BLE source failed: %s", exc)
        return measurements


class _BleStaticSource:
    def __init__(
        self,
        raw_measurements: Sequence[Mapping[str, object]],
        scan_interval_seconds: float,
        adapter_name: str,
    ) -> None:
        self._scanner = BLEAdvertisementScanner(self._drain)
        self._pending_measurements = list(raw_measurements)
        self._scan_interval_seconds = max(scan_interval_seconds, 0.0)
        self._adapter_name = adapter_name
        self._next_scan_time = 0.0

    def _drain(self) -> Sequence[Mapping[str, object]]:
        payload = self._pending_measurements
        self._pending_measurements = []
        return payload

    def fetch(self) -> Sequence[BLEMeasurement]:
        now = time.time()
        if now < self._next_scan_time:
            return []
        self._next_scan_time = now + self._scan_interval_seconds
        try:
            return self._scanner.fetch()
        except Exception as exc:  # pragma: no cover - adapter failures
            LOGGER.exception("BLE source '%s' failed: %s", self._adapter_name, exc)
            return []


class _BleScannerSource:
    def __init__(
        self,
        adapter: BleakScannerAdapter,
        scan_interval_seconds: float,
        adapter_name: str,
    ) -> None:
        self._adapter = adapter
        self._scan_interval_seconds = max(scan_interval_seconds, 0.0)
        self._adapter_name = adapter_name
        self._next_scan_time = 0.0

    def fetch(self) -> Sequence[BLEMeasurement]:
        now = time.time()
        if now < self._next_scan_time:
            return []
        self._next_scan_time = now + self._scan_interval_seconds
        try:
            return self._adapter.fetch()
        except Exception as exc:  # pragma: no cover - adapter failures
            LOGGER.exception("BLE source '%s' failed: %s", self._adapter_name, exc)
            return []

def _load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _require_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object.")
    return value


def _require_sequence(value: object, label: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{label} must be a list.")
    return value


def _require_float(value: object, label: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be numeric.")


def _optional_float(value: object) -> Optional[float]:
    if value is None:
        return None
    return _require_float(value, "value")


def _optional_str(value: object) -> Optional[str]:
    if isinstance(value, str) and value:
        return value
    return None


def _require_non_empty(value: object, label: str) -> str:
    if value is None:
        raise ValueError(f"{label} is required.")
    if isinstance(value, str):
        if not value.strip():
            raise ValueError(f"{label} is required.")
        return value
    return str(value)


def _optional_command(value: object, label: str) -> Optional[Sequence[str]]:
    if value is None:
        return None
    command = _require_sequence(value, label)
    if not command:
        raise ValueError(f"{label} must not be empty.")
    return [str(item) for item in command]


def _parse_homography(
    value: object, label: str
) -> Optional[tuple[tuple[float, float, float], ...]]:
    if value is None:
        return None
    rows = _require_sequence(value, label)
    if len(rows) != 3:
        raise ValueError(f"{label} must have 3 rows.")
    parsed_rows: list[tuple[float, float, float]] = []
    for row_index, row in enumerate(rows):
        row_values = _require_sequence(row, f"{label}[{row_index}]")
        if len(row_values) != 3:
            raise ValueError(f"{label}[{row_index}] must have 3 values.")
        parsed_rows.append(
            (
                _require_float(row_values[0], f"{label}[{row_index}][0]"),
                _require_float(row_values[1], f"{label}[{row_index}][1]"),
                _require_float(row_values[2], f"{label}[{row_index}][2]"),
            )
        )
    return tuple(parsed_rows)


def _parse_space_config(payload: Mapping[str, object]) -> SpaceConfig:
    width = _require_float(payload.get("width_meters"), "space.width_meters")
    height = _require_float(payload.get("height_meters"), "space.height_meters")
    origin = payload.get("coordinate_origin", (0.0, 0.0))
    origin_seq = _require_sequence(origin, "space.coordinate_origin")
    if len(origin_seq) != 2:
        raise ValueError("space.coordinate_origin must have 2 values.")
    origin_tuple = (
        _require_float(origin_seq[0], "space.coordinate_origin[0]"),
        _require_float(origin_seq[1], "space.coordinate_origin[1]"),
    )
    return SpaceConfig(
        width_meters=width,
        height_meters=height,
        coordinate_origin=origin_tuple,
    )


def _parse_sensor_config(payload: Mapping[str, object]) -> SensorConfig:
    wifi_payload = payload.get("wifi_access_points", {})
    cameras_payload = payload.get("cameras", {})
    mmwave_payload = payload.get("mmwave_sensors", {})
    wifi_access_points: dict[str, AccessPointCalibration] = {}
    cameras: dict[str, CameraCalibration] = {}
    mmwave_sensors: dict[str, MmWaveCalibration] = {}

    for access_point_id, entry in _require_mapping(
        wifi_payload, "sensors.wifi_access_points"
    ).items():
        entry_map = _require_mapping(entry, f"wifi_access_points.{access_point_id}")
        position = _require_sequence(entry_map.get("position"), "access_point.position")
        if len(position) != 2:
            raise ValueError("access_point.position must have 2 values.")
        wifi_access_points[str(access_point_id)] = AccessPointCalibration(
            position=(
                _require_float(position[0], "access_point.position[0]"),
                _require_float(position[1], "access_point.position[1]"),
            ),
            position_uncertainty_meters=_require_float(
                entry_map.get("position_uncertainty_meters"),
                "access_point.position_uncertainty_meters",
            ),
        )

    for camera_id, entry in _require_mapping(
        cameras_payload, "sensors.cameras"
    ).items():
        entry_map = _require_mapping(entry, f"cameras.{camera_id}")
        intrinsics_map = _require_mapping(
            entry_map.get("intrinsics"), "camera.intrinsics"
        )
        extrinsics_map = _require_mapping(
            entry_map.get("extrinsics"), "camera.extrinsics"
        )
        focal_length = _require_sequence(
            intrinsics_map.get("focal_length"), "camera.intrinsics.focal_length"
        )
        principal_point = _require_sequence(
            intrinsics_map.get("principal_point"), "camera.intrinsics.principal_point"
        )
        translation = _require_sequence(
            extrinsics_map.get("translation"), "camera.extrinsics.translation"
        )
        if len(focal_length) != 2 or len(principal_point) != 2 or len(translation) != 2:
            raise ValueError("Camera intrinsics/extrinsics must have 2-value tuples.")
        camera_height_value = entry_map.get("camera_height_meters")
        tilt_value = entry_map.get("tilt_radians")
        camera_height_meters = (
            _require_float(camera_height_value, "camera.camera_height_meters")
            if camera_height_value is not None
            else None
        )
        tilt_radians = (
            _require_float(tilt_value, "camera.tilt_radians") if tilt_value is not None else None
        )

        cameras[str(camera_id)] = CameraCalibration(
            intrinsics=CameraIntrinsics(
                focal_length=(
                    _require_float(focal_length[0], "camera.intrinsics.focal_length[0]"),
                    _require_float(focal_length[1], "camera.intrinsics.focal_length[1]"),
                ),
                principal_point=(
                    _require_float(principal_point[0], "camera.intrinsics.principal_point[0]"),
                    _require_float(principal_point[1], "camera.intrinsics.principal_point[1]"),
                ),
                skew=_require_float(
                    intrinsics_map.get("skew", 0.0), "camera.intrinsics.skew"
                ),
            ),
            extrinsics=CameraExtrinsics(
                translation=(
                    _require_float(translation[0], "camera.extrinsics.translation[0]"),
                    _require_float(translation[1], "camera.extrinsics.translation[1]"),
                ),
                rotation_radians=_require_float(
                    extrinsics_map.get("rotation_radians", 0.0),
                    "camera.extrinsics.rotation_radians",
                ),
            ),
            homography=_parse_homography(entry_map.get("homography"), "camera.homography"),
            camera_height_meters=camera_height_meters,
            tilt_radians=tilt_radians,
        )

    for sensor_id, entry in _require_mapping(
        mmwave_payload, "sensors.mmwave_sensors"
    ).items():
        entry_map = _require_mapping(entry, f"mmwave_sensors.{sensor_id}")
        position = _require_sequence(entry_map.get("position"), "mmwave_sensor.position")
        if len(position) != 2:
            raise ValueError("mmwave_sensor.position must have 2 values.")
        mmwave_sensors[str(sensor_id)] = MmWaveCalibration(
            position=(
                _require_float(position[0], "mmwave_sensor.position[0]"),
                _require_float(position[1], "mmwave_sensor.position[1]"),
            ),
            rotation_radians=_require_float(
                entry_map.get("rotation_radians", 0.0),
                "mmwave_sensor.rotation_radians",
            ),
            range_bias_meters=_require_float(
                entry_map.get("range_bias_meters", 0.0),
                "mmwave_sensor.range_bias_meters",
            ),
            angle_bias_radians=_require_float(
                entry_map.get("angle_bias_radians", 0.0),
                "mmwave_sensor.angle_bias_radians",
            ),
            position_uncertainty_meters=_require_float(
                entry_map.get("position_uncertainty_meters", 1.0),
                "mmwave_sensor.position_uncertainty_meters",
            ),
        )

    return SensorConfig(
        wifi_access_points=wifi_access_points,
        cameras=cameras,
        mmwave_sensors=mmwave_sensors,
    )


def _parse_retention_config(payload: Mapping[str, object]) -> RetentionConfig:
    return RetentionConfig(
        enabled=bool(payload.get("enabled", False)),
        measurement_ttl_seconds=_optional_float(payload.get("measurement_ttl_seconds")),
        log_ttl_seconds=_optional_float(payload.get("log_ttl_seconds")),
        cleanup_interval_seconds=_require_float(
            payload.get("cleanup_interval_seconds", 60.0),
            "retention.cleanup_interval_seconds",
        ),
    )


def _parse_sync_config(payload: Mapping[str, object]) -> SynchronizationBuffer:
    return SynchronizationBuffer(
        window_seconds=_require_float(payload.get("window_seconds", 0.25), "sync.window_seconds"),
        max_latency_seconds=_require_float(
            payload.get("max_latency_seconds", 0.25),
            "sync.max_latency_seconds",
        ),
        strategy=str(payload.get("strategy", "nearest")),
    )


def _parse_wifi_sources(
    payload: Sequence[object],
    sensor_config: SensorConfig,
) -> Optional[_MultiWiFiSource]:
    adapters = []
    for idx, entry in enumerate(payload):
        entry_map = _require_mapping(entry, f"ingestion.wifi_sources[{idx}]")
        source_type = str(entry_map.get("type", "http")).lower()
        if source_type == "http":
            endpoint_url = _require_non_empty(
                entry_map.get("endpoint_url"),
                f"ingestion.wifi_sources[{idx}].endpoint_url",
            )
            access_point_id = _require_non_empty(
                entry_map.get("access_point_id"),
                f"ingestion.wifi_sources[{idx}].access_point_id",
            )
            adapters.append(
                HTTPWiFiExporterAdapter(
                    HTTPWiFiExporterConfig(
                        endpoint_url=endpoint_url,
                        access_point_id=access_point_id,
                        timeout_seconds=_require_float(
                            entry_map.get("timeout_seconds", 2.0),
                            "wifi_source.timeout_seconds",
                        ),
                        max_retries=int(entry_map.get("max_retries", 2)),
                        retry_backoff_seconds=_require_float(
                            entry_map.get("retry_backoff_seconds", 0.5),
                            "wifi_source.retry_backoff_seconds",
                        ),
                        clock_offset_seconds=_require_float(
                            entry_map.get("clock_offset_seconds", 0.0),
                            "wifi_source.clock_offset_seconds",
                        ),
                        clock_drift_tolerance_seconds=_require_float(
                            entry_map.get("clock_drift_tolerance_seconds", 2.0),
                            "wifi_source.clock_drift_tolerance_seconds",
                        ),
                        max_clock_offset_seconds=_require_float(
                            entry_map.get("max_clock_offset_seconds", 300.0),
                            "wifi_source.max_clock_offset_seconds",
                        ),
                        drift_smoothing=_require_float(
                            entry_map.get("drift_smoothing", 0.25),
                            "wifi_source.drift_smoothing",
                        ),
                        source_name=str(entry_map.get("source_name", "http_exporter")),
                        source_metadata=_require_mapping(
                            entry_map.get("source_metadata", {}),
                            "wifi_source.source_metadata",
                        ),
                        default_metadata=_require_mapping(
                            entry_map.get("default_metadata", {}),
                            "wifi_source.default_metadata",
                        ),
                    ),
                    sensor_config,
                )
            )
        elif source_type == "local":
            interface_name = _require_non_empty(
                entry_map.get("interface_name"),
                f"ingestion.wifi_sources[{idx}].interface_name",
            )
            access_point_id = _require_non_empty(
                entry_map.get("access_point_id"),
                f"ingestion.wifi_sources[{idx}].access_point_id",
            )
            adapters.append(
                LocalWiFiCaptureAdapter(
                    LocalWiFiCaptureConfig(
                        interface_name=interface_name,
                        access_point_id=access_point_id,
                        target_bssid=_optional_str(entry_map.get("target_bssid")),
                        target_ssid=_optional_str(entry_map.get("target_ssid")),
                        scan_timeout_seconds=_require_float(
                            entry_map.get("scan_timeout_seconds", 2.0),
                            "wifi_source.scan_timeout_seconds",
                        ),
                        scan_command=_optional_command(
                            entry_map.get("scan_command"),
                            "wifi_source.scan_command",
                        ),
                        csi_command=_optional_command(
                            entry_map.get("csi_command"),
                            "wifi_source.csi_command",
                        ),
                        csi_timeout_seconds=_require_float(
                            entry_map.get("csi_timeout_seconds", 1.0),
                            "wifi_source.csi_timeout_seconds",
                        ),
                        clock_offset_seconds=_require_float(
                            entry_map.get("clock_offset_seconds", 0.0),
                            "wifi_source.clock_offset_seconds",
                        ),
                        source_name=str(entry_map.get("source_name", "local_wifi")),
                        source_metadata=_require_mapping(
                            entry_map.get("source_metadata", {}),
                            "wifi_source.source_metadata",
                        ),
                        default_metadata=_require_mapping(
                            entry_map.get("default_metadata", {}),
                            "wifi_source.default_metadata",
                        ),
                    ),
                    sensor_config,
                )
            )
        else:
            raise ValueError(f"Unsupported Wi-Fi source type: {source_type}")
    if not adapters:
        return None
    return _MultiWiFiSource(adapters)


def _parse_vision_sources(
    payload: Sequence[object],
    sensor_config: SensorConfig,
) -> Optional[_MultiVisionSource]:
    adapters = []
    for idx, entry in enumerate(payload):
        entry_map = _require_mapping(entry, f"ingestion.vision_sources[{idx}]")
        source_type = str(entry_map.get("type", "http"))
        if source_type == "http":
            endpoint_url = _require_non_empty(
                entry_map.get("endpoint_url"),
                f"ingestion.vision_sources[{idx}].endpoint_url",
            )
            adapters.append(
                HTTPVisionExporterAdapter(
                    HTTPVisionExporterConfig(
                        endpoint_url=endpoint_url,
                        timeout_seconds=_require_float(
                            entry_map.get("timeout_seconds", 2.0),
                            "vision_source.timeout_seconds",
                        ),
                        max_retries=int(entry_map.get("max_retries", 2)),
                        retry_backoff_seconds=_require_float(
                            entry_map.get("retry_backoff_seconds", 0.5),
                            "vision_source.retry_backoff_seconds",
                        ),
                        default_camera_id=entry_map.get("default_camera_id"),
                        clock_offset_seconds=_require_float(
                            entry_map.get("clock_offset_seconds", 0.0),
                            "vision_source.clock_offset_seconds",
                        ),
                        clock_drift_tolerance_seconds=_require_float(
                            entry_map.get("clock_drift_tolerance_seconds", 2.0),
                            "vision_source.clock_drift_tolerance_seconds",
                        ),
                        max_clock_offset_seconds=_require_float(
                            entry_map.get("max_clock_offset_seconds", 300.0),
                            "vision_source.max_clock_offset_seconds",
                        ),
                        drift_smoothing=_require_float(
                            entry_map.get("drift_smoothing", 0.25),
                            "vision_source.drift_smoothing",
                        ),
                        source_name=str(entry_map.get("source_name", "http_vision_exporter")),
                        source_metadata=_require_mapping(
                            entry_map.get("source_metadata", {}),
                            "vision_source.source_metadata",
                        ),
                        default_metadata=_require_mapping(
                            entry_map.get("default_metadata", {}),
                            "vision_source.default_metadata",
                        ),
                    ),
                    sensor_config,
                )
            )
        elif source_type == "process":
            command = entry_map.get("command")
            command_seq = _require_sequence(command, "vision_source.command")
            adapters.append(
                ProcessVisionExporterAdapter(
                    ProcessVisionExporterConfig(
                        command=[str(item) for item in command_seq],
                        timeout_seconds=_require_float(
                            entry_map.get("timeout_seconds", 3.0),
                            "vision_source.timeout_seconds",
                        ),
                        default_camera_id=entry_map.get("default_camera_id"),
                        clock_offset_seconds=_require_float(
                            entry_map.get("clock_offset_seconds", 0.0),
                            "vision_source.clock_offset_seconds",
                        ),
                        clock_drift_tolerance_seconds=_require_float(
                            entry_map.get("clock_drift_tolerance_seconds", 2.0),
                            "vision_source.clock_drift_tolerance_seconds",
                        ),
                        max_clock_offset_seconds=_require_float(
                            entry_map.get("max_clock_offset_seconds", 300.0),
                            "vision_source.max_clock_offset_seconds",
                        ),
                        drift_smoothing=_require_float(
                            entry_map.get("drift_smoothing", 0.25),
                            "vision_source.drift_smoothing",
                        ),
                        source_name=str(
                            entry_map.get("source_name", "process_vision_exporter")
                        ),
                        source_metadata=_require_mapping(
                            entry_map.get("source_metadata", {}),
                            "vision_source.source_metadata",
                        ),
                        default_metadata=_require_mapping(
                            entry_map.get("default_metadata", {}),
                            "vision_source.default_metadata",
                        ),
                    ),
                    sensor_config,
                )
            )
        else:
            raise ValueError(f"Unsupported vision source type: {source_type}")
    if not adapters:
        return None
    return _MultiVisionSource(adapters)


def _parse_mmwave_sources(payload: Sequence[object]) -> Optional[_MultiMmWaveSource]:
    adapters = []
    for idx, entry in enumerate(payload):
        entry_map = _require_mapping(entry, f"ingestion.mmwave_sources[{idx}]")
        source_type = str(entry_map.get("type", "http"))
        if source_type == "http":
            endpoint_url = _require_non_empty(
                entry_map.get("endpoint_url"),
                f"ingestion.mmwave_sources[{idx}].endpoint_url",
            )
            adapters.append(
                HTTPMmWaveExporterAdapter(
                    HTTPMmWaveExporterConfig(
                        endpoint_url=endpoint_url,
                        default_sensor_id=entry_map.get("default_sensor_id"),
                        timeout_seconds=_require_float(
                            entry_map.get("timeout_seconds", 2.0),
                            "mmwave_source.timeout_seconds",
                        ),
                        max_retries=int(entry_map.get("max_retries", 2)),
                        retry_backoff_seconds=_require_float(
                            entry_map.get("retry_backoff_seconds", 0.5),
                            "mmwave_source.retry_backoff_seconds",
                        ),
                        clock_offset_seconds=_require_float(
                            entry_map.get("clock_offset_seconds", 0.0),
                            "mmwave_source.clock_offset_seconds",
                        ),
                        clock_drift_tolerance_seconds=_require_float(
                            entry_map.get("clock_drift_tolerance_seconds", 2.0),
                            "mmwave_source.clock_drift_tolerance_seconds",
                        ),
                        max_clock_offset_seconds=_require_float(
                            entry_map.get("max_clock_offset_seconds", 300.0),
                            "mmwave_source.max_clock_offset_seconds",
                        ),
                        drift_smoothing=_require_float(
                            entry_map.get("drift_smoothing", 0.25),
                            "mmwave_source.drift_smoothing",
                        ),
                        source_name=str(
                            entry_map.get("source_name", "http_mmwave_exporter")
                        ),
                        source_metadata=_require_mapping(
                            entry_map.get("source_metadata", {}),
                            "mmwave_source.source_metadata",
                        ),
                        default_metadata=_require_mapping(
                            entry_map.get("default_metadata", {}),
                            "mmwave_source.default_metadata",
                        ),
                    )
                )
            )
        elif source_type == "serial":
            port = _require_non_empty(
                entry_map.get("port"),
                f"ingestion.mmwave_sources[{idx}].port",
            )
            adapters.append(
                SerialMmWaveAdapter(
                    SerialMmWaveConfig(
                        port=port,
                        baudrate=int(entry_map.get("baudrate", 115200)),
                        timeout_seconds=_require_float(
                            entry_map.get("timeout_seconds", 0.5),
                            "mmwave_source.timeout_seconds",
                        ),
                        max_lines=int(entry_map.get("max_lines", 50)),
                        default_sensor_id=entry_map.get("default_sensor_id"),
                        clock_offset_seconds=_require_float(
                            entry_map.get("clock_offset_seconds", 0.0),
                            "mmwave_source.clock_offset_seconds",
                        ),
                        source_name=str(entry_map.get("source_name", "serial_mmwave")),
                        source_metadata=_require_mapping(
                            entry_map.get("source_metadata", {}),
                            "mmwave_source.source_metadata",
                        ),
                        default_metadata=_require_mapping(
                            entry_map.get("default_metadata", {}),
                            "mmwave_source.default_metadata",
                        ),
                    )
                )
            )
        else:
            raise ValueError(f"Unsupported mmWave source type: {source_type}")
    if not adapters:
        return None
    return _MultiMmWaveSource(adapters)


def _parse_ble_sources(payload: Mapping[str, object]) -> Optional[_MultiBleSource]:
    source_payload = _require_sequence(
        payload.get("ble_sources", []), "ingestion.ble_sources"
    )
    adapters = []
    for idx, entry in enumerate(source_payload):
        entry_map = _require_mapping(entry, f"ingestion.ble_sources[{idx}]")
        source_type = str(entry_map.get("type", "static"))
        scan_interval_seconds = _require_float(
            entry_map.get("scan_interval_seconds", 1.0),
            "ble_source.scan_interval_seconds",
        )
        adapter_name = str(entry_map.get("adapter_name", f"ble_scanner_{idx}"))
        if source_type == "static":
            raw_measurements = _require_sequence(
                entry_map.get("measurements", []),
                "ble_source.measurements",
            )
            normalized_measurements = [
                _require_mapping(item, f"ble_source.measurements[{item_idx}]")
                for item_idx, item in enumerate(raw_measurements)
            ]
            adapters.append(
                _BleStaticSource(
                    normalized_measurements,
                    scan_interval_seconds=scan_interval_seconds,
                    adapter_name=adapter_name,
                )
            )
        elif source_type == "bleak":
            adapter_settings = _require_mapping(
                entry_map.get("adapter_settings", {}),
                "ble_source.adapter_settings",
            )
            offline_payloads = _require_sequence(
                adapter_settings.get("offline_payloads", []),
                "ble_source.adapter_settings.offline_payloads",
            )
            normalized_offline_payloads = [
                _require_mapping(item, f"ble_source.adapter_settings.offline_payloads[{item_idx}]")
                for item_idx, item in enumerate(offline_payloads)
            ]
            resolved_adapter_name = str(
                adapter_settings.get("adapter_name", adapter_name)
            )
            adapter_config = BleakScannerConfig(
                adapter_name=resolved_adapter_name,
                scan_timeout_seconds=_require_float(
                    adapter_settings.get("scan_timeout_seconds", 2.0),
                    "ble_source.adapter_settings.scan_timeout_seconds",
                ),
                offline=bool(adapter_settings.get("offline", False)),
                offline_payloads=normalized_offline_payloads,
                include_hashed_identifier=bool(
                    adapter_settings.get("include_hashed_identifier", True)
                ),
            )
            adapters.append(
                _BleScannerSource(
                    BleakScannerAdapter(adapter_config),
                    scan_interval_seconds=scan_interval_seconds,
                    adapter_name=resolved_adapter_name,
                )
            )
        else:
            raise ValueError(f"Unsupported BLE source type: {source_type}")
    if not adapters:
        return None
    return _MultiBleSource(adapters)


def _emit_ndjson(updates: Iterable[TrackState]) -> None:
    for update in updates:
        payload = asdict(update)
        print(json.dumps(payload), flush=True)


def _latest_timestamp(items: Sequence[object]) -> Optional[float]:
    timestamps = [getattr(item, "timestamp", None) for item in items]
    valid = [value for value in timestamps if isinstance(value, (float, int))]
    if not valid:
        return None
    return float(max(valid))


def _aggregate_ble_emitters(
    measurements: Sequence[BLEMeasurement],
) -> list[dict[str, object]]:
    emitters: dict[str, dict[str, object]] = {}
    for measurement in measurements:
        emitter_key = measurement.device_id or measurement.hashed_identifier
        if emitter_key is None:
            continue
        existing = emitters.get(emitter_key)
        existing_last_seen = existing.get("last_seen") if existing else None
        if existing is None or measurement.timestamp >= float(existing_last_seen or 0.0):
            entry: dict[str, object] = {
                "rssi": measurement.rssi,
                "last_seen": measurement.timestamp,
            }
            if measurement.device_id is not None:
                entry["device_id"] = measurement.device_id
            else:
                entry["emitter_id"] = measurement.hashed_identifier
            emitters[emitter_key] = entry
    return [emitters[key] for key in sorted(emitters)]


def _aggregate_wifi_band_summary(
    measurements: Sequence[WiFiMeasurement],
) -> dict[str, int]:
    summary = {"2.4ghz": 0, "5ghz": 0, "6ghz": 0}
    for measurement in measurements:
        band = _resolve_wifi_band(measurement)
        if band in summary:
            summary[band] += 1
    return summary


def _resolve_wifi_band(measurement: WiFiMeasurement) -> Optional[str]:
    if measurement.band:
        return measurement.band
    if measurement.channel is not None:
        band = _band_from_channel(measurement.channel)
        if band is not None:
            return band
    metadata = measurement.metadata
    if isinstance(metadata, Mapping):
        frequency = metadata.get("frequency_mhz")
        if isinstance(frequency, (int, float)):
            return _band_from_frequency(float(frequency))
    return None


def _band_from_channel(channel: int) -> Optional[str]:
    if 1 <= channel <= 14:
        return "2.4ghz"
    if 32 <= channel <= 177:
        return "5ghz"
    return None


def _band_from_frequency(frequency_mhz: float) -> Optional[str]:
    if 2400 <= frequency_mhz <= 2500:
        return "2.4ghz"
    if 5925 <= frequency_mhz <= 7125:
        return "6ghz"
    if 5000 <= frequency_mhz < 5925:
        return "5ghz"
    return None


def _build_sensor_health(batch: SyncBatch) -> list[dict[str, object]]:
    status = batch.status
    return [
        {
            "label": "wifi",
            "status": "online" if not status.wifi_stale else "offline",
            "last_seen": _latest_timestamp(batch.fusion_input.wifi),
        },
        {
            "label": "vision",
            "status": "online" if not status.vision_stale else "offline",
            "last_seen": _latest_timestamp(batch.fusion_input.vision),
        },
        {
            "label": "mmwave",
            "status": "online" if not status.mmwave_stale else "offline",
            "last_seen": _latest_timestamp(batch.fusion_input.mmwave),
        },
        {
            "label": "ble",
            "status": "online" if not status.ble_stale else "offline",
            "last_seen": _latest_timestamp(batch.fusion_input.ble),
        },
    ]


def _emit_tick_ndjson(
    updates: Sequence[TrackState],
    batch: SyncBatch,
    *,
    camera_frame: Optional[str] = None,
) -> None:
    payload: dict[str, object] = {
        "tracks": [asdict(update) for update in updates],
        "emitters": _aggregate_ble_emitters(batch.fusion_input.ble),
        "sensor_health": _build_sensor_health(batch),
        "band_summary": _aggregate_wifi_band_summary(batch.fusion_input.wifi),
    }
    if camera_frame is not None:
        payload["camera_frame"] = camera_frame
    print(json.dumps(payload), flush=True)


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _parse_audit_config(
    payload: Mapping[str, object],
) -> tuple[Optional[AuditLogger], bool]:
    audit_enabled = bool(payload.get("enabled", False))
    if not audit_enabled:
        return None, False
    audit_logger = AuditLogger()
    consent_entries = _require_sequence(payload.get("consent_records", []), "audit.consent_records")
    for idx, entry in enumerate(consent_entries):
        entry_map = _require_mapping(entry, f"audit.consent_records[{idx}]")
        status = _require_non_empty(entry_map.get("status"), "audit.consent_records.status")
        participant_id = _optional_str(entry_map.get("participant_id"))
        session_id = _optional_str(entry_map.get("session_id"))
        audit_logger.record_consent(
            status=status,
            participant_id=participant_id,
            session_id=session_id,
        )
    require_consent = bool(payload.get("require_consent", False))
    return audit_logger, require_consent


def _build_pipeline(config: Mapping[str, object]) -> tuple[FusionPipeline, IngestionOrchestrator]:
    space_payload = _require_mapping(config.get("space", {}), "space")
    sensors_payload = _require_mapping(config.get("sensors", {}), "sensors")
    ingestion_payload = _require_mapping(config.get("ingestion", {}), "ingestion")
    sync_payload = _require_mapping(config.get("synchronization", {}), "synchronization")
    retention_payload = _require_mapping(config.get("retention", {}), "retention")
    audit_payload = _require_mapping(config.get("audit", {}), "audit")

    space_config = _parse_space_config(space_payload)
    sensor_config = _parse_sensor_config(sensors_payload)
    sync_buffer = _parse_sync_config(sync_payload)
    retention_config = _parse_retention_config(retention_payload)
    audit_logger, require_consent = _parse_audit_config(audit_payload)

    wifi_sources = _parse_wifi_sources(
        _require_sequence(ingestion_payload.get("wifi_sources", []), "ingestion.wifi_sources"),
        sensor_config,
    )
    vision_sources = _parse_vision_sources(
        _require_sequence(
            ingestion_payload.get("vision_sources", []), "ingestion.vision_sources"
        ),
        sensor_config,
    )
    mmwave_sources = _parse_mmwave_sources(
        _require_sequence(
            ingestion_payload.get("mmwave_sources", []), "ingestion.mmwave_sources"
        )
    )
    ble_sources = _parse_ble_sources(ingestion_payload)

    retention_scheduler = RetentionScheduler(
        retention_config=retention_config,
        buffer=sync_buffer,
        audit_logger=audit_logger,
    )
    pipeline = FusionPipeline(
        sensor_config=sensor_config,
        space_config=space_config,
        audit_logger=audit_logger,
        require_consent=require_consent,
        retention_scheduler=retention_scheduler,
    )
    orchestrator = IngestionOrchestrator(
        wifi_source=wifi_sources,
        vision_source=vision_sources,
        mmwave_source=mmwave_sources,
        ble_source=ble_sources,
        sync_buffer=sync_buffer,
    )
    return pipeline, orchestrator


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the Sandevistan fusion pipeline with live ingestion adapters."
    )
    parser.add_argument(
        "--config",
        required=True,
        help="Path to a JSON configuration file.",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=0.2,
        help="Seconds to wait between ingestion polls (default: 0.2).",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=0,
        help="Stop after N iterations (0 = run forever).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level (default: INFO).",
    )
    parser.add_argument(
        "--emit-legacy-tracks",
        action="store_true",
        help="Emit bare track updates per line for legacy consumers.",
    )
    args = parser.parse_args(argv)

    _configure_logging(args.log_level)

    config_path = Path(args.config)
    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")
    config = _load_config(config_path)
    config_map = _require_mapping(config, "config")

    pipeline, orchestrator = _build_pipeline(config_map)
    pipeline.retention_scheduler.start()

    poll_interval = max(args.poll_interval, 0.0)
    max_iterations = max(args.max_iterations, 0)
    iterations = 0

    try:
        while True:
            reference_time = time.time()
            batch = orchestrator.poll(reference_time=reference_time)
            if batch is None:
                time.sleep(poll_interval)
                iterations += 1
            else:
                updates = pipeline.fuse(
                    batch.fusion_input,
                    aligned=True,
                    reference_time=batch.status.reference_time,
                )
                if args.emit_legacy_tracks:
                    if updates:
                        _emit_ndjson(updates)
                else:
                    _emit_tick_ndjson(updates, batch)
                if pipeline.retention_scheduler:
                    pipeline.retention_scheduler.run_once(
                        reference_time=batch.status.reference_time,
                        now=datetime.utcnow(),
                    )
                iterations += 1
            if max_iterations and iterations >= max_iterations:
                break
    except KeyboardInterrupt:
        return 0
    finally:
        pipeline.retention_scheduler.stop()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
