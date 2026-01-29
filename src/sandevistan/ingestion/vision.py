from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Mapping, Optional, Sequence, Tuple

from ..config import SensorConfig
from ..models import Detection


@dataclass(frozen=True)
class DetectionIngestionError(ValueError):
    message: str

    def __str__(self) -> str:
        return self.message


def parse_detections(
    raw_detections: Iterable[Mapping[str, object]],
    sensor_config: SensorConfig,
) -> List[Detection]:
    """Parse raw camera payloads into Detection objects.

    Normalizes camera-local coordinates into world coordinates using sensor metadata.
    """
    detections: List[Detection] = []
    last_timestamp_by_camera: dict[str, float] = {}

    for idx, raw in enumerate(raw_detections):
        camera_id = _require_str(raw, "camera_id", idx)
        timestamp = _require_float(raw, "timestamp", idx, camera_id)
        confidence = _require_float(raw, "confidence", idx, camera_id, timestamp)
        bbox = _require_bbox(raw, "bbox", idx, camera_id, timestamp)

        camera_origin = sensor_config.cameras.get(camera_id)
        if camera_origin is None:
            raise DetectionIngestionError(
                _format_message(
                    "Unknown camera; update SensorConfig before ingestion.",
                    camera_id,
                    timestamp,
                )
            )

        last_timestamp = last_timestamp_by_camera.get(camera_id)
        if last_timestamp is not None and timestamp < last_timestamp:
            raise DetectionIngestionError(
                _format_message(
                    (
                        "Timestamp out of order for detection; "
                        f"previous timestamp was {last_timestamp:.3f}."
                    ),
                    camera_id,
                    timestamp,
                )
            )
        last_timestamp_by_camera[camera_id] = timestamp

        normalized_bbox = _normalize_bbox(bbox, camera_origin)
        keypoints = _optional_keypoints(raw.get("keypoints"), camera_id, timestamp)
        if keypoints is not None:
            keypoints = [
                (point[0] + camera_origin[0], point[1] + camera_origin[1])
                for point in keypoints
            ]

        detections.append(
            Detection(
                timestamp=timestamp,
                camera_id=camera_id,
                bbox=normalized_bbox,
                confidence=confidence,
                keypoints=keypoints,
            )
        )

    return detections


def _require_str(raw: Mapping[str, object], field: str, idx: int) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or not value:
        raise DetectionIngestionError(
            f"Detection #{idx} missing required field '{field}'."
        )
    return value


def _require_float(
    raw: Mapping[str, object],
    field: str,
    idx: int,
    camera_id: Optional[str] = None,
    timestamp: Optional[float] = None,
) -> float:
    value = raw.get(field)
    try:
        return float(value)
    except (TypeError, ValueError):
        sensor_label = camera_id or "unknown"
        timestamp_label = "unknown" if timestamp is None else f"{timestamp:.3f}"
        raise DetectionIngestionError(
            _format_message(
                f"Invalid or missing '{field}' field; received {value!r}.",
                sensor_label,
                timestamp_label,
            )
        )


def _require_bbox(
    raw: Mapping[str, object],
    field: str,
    idx: int,
    camera_id: str,
    timestamp: float,
) -> Tuple[float, float, float, float]:
    value = raw.get(field)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise DetectionIngestionError(
            _format_message(
                f"{field} must be a 4-value sequence.",
                camera_id,
                timestamp,
            )
        )
    if len(value) != 4:
        raise DetectionIngestionError(
            _format_message(
                f"{field} must contain 4 values; received {len(value)}.",
                camera_id,
                timestamp,
            )
        )
    try:
        x_min, y_min, x_max, y_max = (float(item) for item in value)
    except (TypeError, ValueError):
        raise DetectionIngestionError(
            _format_message(
                f"{field} contains non-numeric values.",
                camera_id,
                timestamp,
            )
        )
    if x_min > x_max or y_min > y_max:
        raise DetectionIngestionError(
            _format_message(
                f"{field} min values exceed max values.",
                camera_id,
                timestamp,
            )
        )
    return x_min, y_min, x_max, y_max


def _optional_keypoints(
    value: object,
    camera_id: str,
    timestamp: float,
) -> Optional[Sequence[Tuple[float, float]]]:
    if value is None:
        return None
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes)):
        raise DetectionIngestionError(
            _format_message(
                "keypoints must be a sequence of (x, y) tuples when provided.",
                camera_id,
                timestamp,
            )
        )
    keypoints: List[Tuple[float, float]] = []
    for point in value:
        if not isinstance(point, Sequence) or isinstance(point, (str, bytes)):
            raise DetectionIngestionError(
                _format_message(
                    "keypoints must contain (x, y) sequences.",
                    camera_id,
                    timestamp,
                )
            )
        if len(point) != 2:
            raise DetectionIngestionError(
                _format_message(
                    "keypoints must contain 2 values per point.",
                    camera_id,
                    timestamp,
                )
            )
        try:
            keypoints.append((float(point[0]), float(point[1])))
        except (TypeError, ValueError):
            raise DetectionIngestionError(
                _format_message(
                    "keypoints contain non-numeric values.",
                    camera_id,
                    timestamp,
                )
            )
    return keypoints


def _normalize_bbox(
    bbox: Tuple[float, float, float, float],
    camera_origin: Tuple[float, float],
) -> Tuple[float, float, float, float]:
    return (
        bbox[0] + camera_origin[0],
        bbox[1] + camera_origin[1],
        bbox[2] + camera_origin[0],
        bbox[3] + camera_origin[1],
    )


def _format_message(message: str, camera_id: object, timestamp: object) -> str:
    return (
        f"Vision ingestion error: {message} "
        f"(sensor_id={camera_id}, timestamp={timestamp})."
    )
