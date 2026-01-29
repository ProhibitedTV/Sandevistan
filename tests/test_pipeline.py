import math

from sandevistan.config import SensorConfig, SpaceConfig
from sandevistan.models import Detection, FusionInput, WiFiMeasurement
from sandevistan.pipeline import FusionPipeline


def _make_pipeline() -> FusionPipeline:
    sensor_config = SensorConfig(
        wifi_access_points={
            "ap-1": (0.0, 0.0),
            "ap-2": (5.0, 0.0),
            "ap-3": (0.0, 5.0),
        },
        cameras={"cam-1": (0.0, 0.0)},
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


def _make_wifi(timestamp: float, access_point_id: str, rssi: float) -> WiFiMeasurement:
    return WiFiMeasurement(
        timestamp=timestamp,
        access_point_id=access_point_id,
        rssi=rssi,
        csi=None,
        metadata=None,
    )


def test_fuse_empty_input_returns_empty_list() -> None:
    pipeline = _make_pipeline()

    result = pipeline.fuse(FusionInput(wifi=[], vision=[]))

    assert result == []


def test_track_continuity_across_frames() -> None:
    pipeline = _make_pipeline()
    timestamps = [0.0, 0.1, 0.2, 0.3, 0.4]
    centers = [(0.5 + 0.01 * idx, 0.5 + 0.005 * idx) for idx in range(len(timestamps))]

    track_ids = []
    for timestamp, center in zip(timestamps, centers):
        detection = _make_detection(timestamp, center)
        wifi = [_make_wifi(timestamp, "ap-1", rssi=-45.0)]
        outputs = pipeline.fuse(FusionInput(wifi=wifi, vision=[detection]))
        assert len(outputs) == 1
        track_ids.append(outputs[0].track_id)

    assert len(set(track_ids)) == 1


def test_track_position_updates_smoothly() -> None:
    pipeline = _make_pipeline()
    timestamps = [0.0, 0.2, 0.4]
    centers = [(0.4, 0.4), (0.45, 0.45), (0.5, 0.5)]

    positions = []
    for timestamp, center in zip(timestamps, centers):
        detection = _make_detection(timestamp, center)
        outputs = pipeline.fuse(FusionInput(wifi=[], vision=[detection]))
        assert outputs
        positions.append(outputs[0].position)

    distances = [
        math.hypot(
            positions[idx + 1][0] - positions[idx][0],
            positions[idx + 1][1] - positions[idx][1],
        )
        for idx in range(len(positions) - 1)
    ]
    assert all(distance < 1.0 for distance in distances)
