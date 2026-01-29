from __future__ import annotations

import argparse
import json
import logging
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping, MutableMapping, Optional, Sequence

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
from .pipeline import FusionPipeline
from .retention import RetentionScheduler
from .sync import SynchronizationBuffer

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


def _optional_command(value: object, label: str) -> Optional[Sequence[str]]:
    if value is None:
        return None
    command = _require_sequence(value, label)
    if not command:
        raise ValueError(f"{label} must not be empty.")
    return [str(item) for item in command]


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
        source_type = str(entry_map.get("type", "http"))
        if source_type == "http":
            adapters.append(
                HTTPWiFiExporterAdapter(
                    HTTPWiFiExporterConfig(
                        endpoint_url=str(entry_map.get("endpoint_url")),
                        access_point_id=str(entry_map.get("access_point_id")),
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
            adapters.append(
                LocalWiFiCaptureAdapter(
                    LocalWiFiCaptureConfig(
                        interface_name=str(entry_map.get("interface_name")),
                        access_point_id=str(entry_map.get("access_point_id")),
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
            adapters.append(
                HTTPVisionExporterAdapter(
                    HTTPVisionExporterConfig(
                        endpoint_url=str(entry_map.get("endpoint_url")),
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
            adapters.append(
                HTTPMmWaveExporterAdapter(
                    HTTPMmWaveExporterConfig(
                        endpoint_url=str(entry_map.get("endpoint_url")),
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
            adapters.append(
                SerialMmWaveAdapter(
                    SerialMmWaveConfig(
                        port=str(entry_map.get("port")),
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


def _parse_ble_sources(payload: Sequence[object]) -> Optional[_MultiBleSource]:
    adapters = []
    for idx, entry in enumerate(payload):
        entry_map = _require_mapping(entry, f"ingestion.ble_sources[{idx}]")
        source_type = str(entry_map.get("type", "static"))
        if source_type != "static":
            raise ValueError(f"Unsupported BLE source type: {source_type}")
        scan_interval_seconds = _require_float(
            entry_map.get("scan_interval_seconds", 1.0),
            "ble_source.scan_interval_seconds",
        )
        adapter_name = str(entry_map.get("adapter_name", f"ble_scanner_{idx}"))
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
    if not adapters:
        return None
    return _MultiBleSource(adapters)


def _emit_ndjson(updates: Iterable[TrackState]) -> None:
    for update in updates:
        payload = asdict(update)
        print(json.dumps(payload), flush=True)


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _build_pipeline(config: Mapping[str, object]) -> tuple[FusionPipeline, IngestionOrchestrator]:
    space_payload = _require_mapping(config.get("space", {}), "space")
    sensors_payload = _require_mapping(config.get("sensors", {}), "sensors")
    ingestion_payload = _require_mapping(config.get("ingestion", {}), "ingestion")
    sync_payload = _require_mapping(config.get("synchronization", {}), "synchronization")
    retention_payload = _require_mapping(config.get("retention", {}), "retention")

    space_config = _parse_space_config(space_payload)
    sensor_config = _parse_sensor_config(sensors_payload)
    sync_buffer = _parse_sync_config(sync_payload)
    retention_config = _parse_retention_config(retention_payload)

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
    ble_sources = _parse_ble_sources(
        _require_sequence(ingestion_payload.get("ble_sources", []), "ingestion.ble_sources")
    )

    retention_scheduler = RetentionScheduler(
        retention_config=retention_config,
        buffer=sync_buffer,
        audit_logger=None,
    )
    pipeline = FusionPipeline(
        sensor_config=sensor_config,
        space_config=space_config,
        audit_logger=None,
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
                updates = pipeline.fuse(batch.fusion_input)
                if updates:
                    _emit_ndjson(updates)
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
