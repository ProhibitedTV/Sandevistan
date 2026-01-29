import math

from sandevistan.config import (
    AccessPointCalibration,
    CameraCalibration,
    CameraExtrinsics,
    CameraIntrinsics,
    SensorConfig,
    SpaceConfig,
)
from sandevistan.models import Detection, FusionInput, WiFiMeasurement
from sandevistan.pipeline import FusionPipeline


def _make_pipeline() -> FusionPipeline:
    sensor_config = SensorConfig(
        wifi_access_points={
            "ap-1": AccessPointCalibration(position=(0.0, 0.0), position_uncertainty_meters=0.5),
            "ap-2": AccessPointCalibration(position=(5.0, 0.0), position_uncertainty_meters=0.5),
            "ap-3": AccessPointCalibration(position=(0.0, 5.0), position_uncertainty_meters=0.5),
        },
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


def _make_wifi(timestamp: float, access_point_id: str, rssi: float) -> WiFiMeasurement:
    return WiFiMeasurement(
        timestamp=timestamp,
        access_point_id=access_point_id,
        rssi=rssi,
        csi=None,
        metadata=None,
    )


def _closest_track_id(tracks, position: tuple[float, float]) -> str:
    return min(
        tracks,
        key=lambda track: math.hypot(
            track.position[0] - position[0], track.position[1] - position[1]
        ),
    ).track_id


def _to_space(position: tuple[float, float]) -> tuple[float, float]:
    return (position[0] * 10.0, position[1] * 10.0)


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


def test_multi_target_overlap_keeps_consistent_ids() -> None:
    pipeline = _make_pipeline()
    timestamps = [0.0, 0.2, 0.4, 0.6]
    target_a = [(0.3, 0.3), (0.4, 0.4), (0.48, 0.52), (0.4, 0.4)]
    target_b = [(0.7, 0.7), (0.6, 0.6), (0.52, 0.48), (0.6, 0.6)]

    initial_tracks = pipeline.fuse(
        FusionInput(
            wifi=[],
            vision=[
                _make_detection(timestamps[0], target_a[0]),
                _make_detection(timestamps[0], target_b[0]),
            ],
        )
    )
    assert len(initial_tracks) == 2
    target_a_id = _closest_track_id(initial_tracks, _to_space(target_a[0]))
    target_b_id = _closest_track_id(initial_tracks, _to_space(target_b[0]))
    assert target_a_id != target_b_id

    for idx in range(1, len(timestamps)):
        detections = [
            _make_detection(timestamps[idx], target_a[idx]),
            _make_detection(timestamps[idx], target_b[idx]),
        ]
        tracks = pipeline.fuse(FusionInput(wifi=[], vision=detections))
        assert len(tracks) == 2
        assert _closest_track_id(tracks, _to_space(target_a[idx])) == target_a_id
        assert _closest_track_id(tracks, _to_space(target_b[idx])) == target_b_id


def test_track_persists_through_occlusion() -> None:
    pipeline = _make_pipeline()
    timestamps = [0.0, 0.2, 0.4, 0.6]
    target_a = [(0.2, 0.2), (0.25, 0.25), (0.3, 0.3), (0.35, 0.35)]
    target_b = [(0.8, 0.2), (0.75, 0.25), (0.7, 0.3), (0.65, 0.35)]

    initial_tracks = pipeline.fuse(
        FusionInput(
            wifi=[],
            vision=[
                _make_detection(timestamps[0], target_a[0]),
                _make_detection(timestamps[0], target_b[0]),
            ],
        )
    )
    assert len(initial_tracks) == 2
    target_b_id = _closest_track_id(initial_tracks, _to_space(target_b[0]))

    tracks = pipeline.fuse(
        FusionInput(
            wifi=[],
            vision=[
                _make_detection(timestamps[1], target_a[1]),
                _make_detection(timestamps[1], target_b[1]),
            ],
        )
    )
    assert len(tracks) == 2

    occluded = pipeline.fuse(
        FusionInput(
            wifi=[],
            vision=[_make_detection(timestamps[2], target_a[2])],
        )
    )
    assert len(occluded) == 2
    assert target_b_id in {track.track_id for track in occluded}

    reappeared = pipeline.fuse(
        FusionInput(
            wifi=[],
            vision=[
                _make_detection(timestamps[3], target_a[3]),
                _make_detection(timestamps[3], target_b[3]),
            ],
        )
    )
    assert len(reappeared) == 2
    assert _closest_track_id(reappeared, _to_space(target_b[3])) == target_b_id
