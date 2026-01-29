import statistics
import time

from sandevistan.config import (
    CameraCalibration,
    CameraExtrinsics,
    CameraIntrinsics,
    SensorConfig,
    SpaceConfig,
)
from sandevistan.models import Detection, FusionInput
from sandevistan.pipeline import FusionPipeline


def _make_pipeline() -> FusionPipeline:
    sensor_config = SensorConfig(
        wifi_access_points={},
        cameras={
            "cam-1": CameraCalibration(
                intrinsics=CameraIntrinsics(
                    focal_length=(1.0, 1.0),
                    principal_point=(0.0, 0.0),
                ),
                extrinsics=CameraExtrinsics(translation=(0.0, 0.0), rotation_radians=0.0),
            )
        },
    )
    space_config = SpaceConfig(width_meters=10.0, height_meters=10.0)
    return FusionPipeline(sensor_config=sensor_config, space_config=space_config)


def _make_detection(timestamp: float, center: tuple[float, float]) -> Detection:
    x, y = center
    bbox = (
        max(0.0, x - 0.05),
        max(0.0, y - 0.05),
        min(1.0, x + 0.05),
        min(1.0, y + 0.05),
    )
    return Detection(
        timestamp=timestamp,
        camera_id="cam-1",
        bbox=bbox,
        confidence=0.9,
        keypoints=None,
    )


def test_latency_budget_per_frame() -> None:
    pipeline = _make_pipeline()
    inputs = [
        FusionInput(
            wifi=[],
            vision=[_make_detection(idx * 0.05, (0.5, 0.5))],
        )
        for idx in range(200)
    ]

    start = time.perf_counter()
    for measurement in inputs:
        pipeline.fuse(measurement)
    elapsed = time.perf_counter() - start

    per_frame = elapsed / len(inputs)
    assert per_frame <= 0.25


def test_localization_accuracy_median_error() -> None:
    pipeline = _make_pipeline()
    ground_truth = [(0.2 + 0.01 * idx, 0.3 + 0.01 * idx) for idx in range(40)]

    errors = []
    for idx, center in enumerate(ground_truth):
        detection = _make_detection(idx * 0.1, center)
        outputs = pipeline.fuse(FusionInput(wifi=[], vision=[detection]))
        assert outputs
        position = outputs[0].position
        truth = (center[0] * 10.0, center[1] * 10.0)
        error = ((position[0] - truth[0]) ** 2 + (position[1] - truth[1]) ** 2) ** 0.5
        errors.append(error)

    median_error = statistics.median(errors)
    assert median_error <= 2.0


def test_tracking_reliability_ratio() -> None:
    pipeline = _make_pipeline()
    total_frames = 30
    stable_frames = 0
    baseline_id = None

    for idx in range(total_frames):
        detection = _make_detection(idx * 0.1, (0.5, 0.5))
        outputs = pipeline.fuse(FusionInput(wifi=[], vision=[detection]))
        if outputs:
            if baseline_id is None:
                baseline_id = outputs[0].track_id
            if outputs[0].track_id == baseline_id:
                stable_frames += 1

    ratio = stable_frames / total_frames
    assert ratio >= 0.9
