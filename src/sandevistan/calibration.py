from __future__ import annotations

import math
from typing import Iterable, Sequence, Tuple

from .config import AccessPointCalibration, CameraCalibration


def require_camera_calibration(
    calibration: CameraCalibration | None, camera_id: str
) -> CameraCalibration:
    if calibration is None:
        raise ValueError(
            f"Missing calibration for camera '{camera_id}'. "
            "Update SensorConfig before ingestion."
        )
    return calibration


def require_access_point_calibration(
    calibration: AccessPointCalibration | None, access_point_id: str
) -> AccessPointCalibration:
    if calibration is None:
        raise ValueError(
            f"Missing calibration for access point '{access_point_id}'. "
            "Update SensorConfig before ingestion."
        )
    return calibration


def transform_point_to_world(
    point: Tuple[float, float],
    calibration: CameraCalibration,
) -> Tuple[float, float]:
    x_local, y_local = point
    translation = calibration.extrinsics.translation
    rotation = calibration.extrinsics.rotation_radians
    cos_r = math.cos(rotation)
    sin_r = math.sin(rotation)
    x_world = x_local * cos_r - y_local * sin_r + translation[0]
    y_world = x_local * sin_r + y_local * cos_r + translation[1]
    return (x_world, y_world)


def transform_points_to_world(
    points: Iterable[Tuple[float, float]],
    calibration: CameraCalibration,
) -> list[Tuple[float, float]]:
    return [transform_point_to_world(point, calibration) for point in points]


def transform_bbox_to_world(
    bbox: Sequence[float],
    calibration: CameraCalibration,
) -> Tuple[float, float, float, float]:
    if len(bbox) != 4:
        raise ValueError("bbox must contain 4 values.")
    x_min, y_min, x_max, y_max = bbox
    points = (
        (x_min, y_min),
        (x_max, y_min),
        (x_max, y_max),
        (x_min, y_max),
    )
    transformed = transform_points_to_world(points, calibration)
    xs = [point[0] for point in transformed]
    ys = [point[1] for point in transformed]
    return (min(xs), min(ys), max(xs), max(ys))
