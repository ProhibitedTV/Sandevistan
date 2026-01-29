from sandevistan.models import Detection, WiFiMeasurement
from sandevistan.sync import SynchronizationBuffer


def _wifi(timestamp: float, access_point_id: str = "ap-1") -> WiFiMeasurement:
    return WiFiMeasurement(
        timestamp=timestamp,
        access_point_id=access_point_id,
        rssi=-40.0,
        csi=None,
        metadata=None,
    )


def _vision(timestamp: float, camera_id: str = "cam-1") -> Detection:
    return Detection(
        timestamp=timestamp,
        camera_id=camera_id,
        bbox=(0.4, 0.4, 0.6, 0.6),
        confidence=0.8,
        keypoints=None,
    )


def test_emit_empty_returns_none() -> None:
    buffer = SynchronizationBuffer()

    assert buffer.emit() is None


def test_latency_window_drops_stale_measurements() -> None:
    buffer = SynchronizationBuffer(window_seconds=0.2, max_latency_seconds=0.1)

    buffer.add_wifi([_wifi(0.0), _wifi(0.09), _wifi(0.11)])
    buffer.add_vision([_vision(0.02), _vision(0.18)])

    batch = buffer.emit(reference_time=0.2)

    assert batch is not None
    assert batch.status.dropped_wifi == 2
    assert batch.status.dropped_vision == 1
    assert len(batch.fusion_input.wifi) == 1
    assert len(batch.fusion_input.vision) == 1
    assert batch.fusion_input.wifi[0].timestamp == 0.11
    assert batch.fusion_input.vision[0].timestamp == 0.18
    assert batch.status.wifi_stale is False
    assert batch.status.vision_stale is False
