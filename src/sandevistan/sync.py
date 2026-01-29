from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Iterable, List, Optional, Sequence, Tuple

from .models import Detection, FusionInput, WiFiMeasurement


@dataclass(frozen=True)
class SyncStatus:
    reference_time: float
    wifi_stale: bool
    vision_stale: bool
    dropped_wifi: int
    dropped_vision: int
    window_seconds: float
    max_latency_seconds: float
    strategy: str


@dataclass(frozen=True)
class SyncBatch:
    fusion_input: FusionInput
    status: SyncStatus


@dataclass
class SynchronizationBuffer:
    """Buffer Wi-Fi and vision measurements and emit aligned FusionInput batches."""

    window_seconds: float = 0.25
    max_latency_seconds: float = 0.25
    strategy: str = "nearest"
    _wifi: List[WiFiMeasurement] = field(default_factory=list, init=False, repr=False)
    _vision: List[Detection] = field(default_factory=list, init=False, repr=False)

    def add_wifi(self, measurements: Iterable[WiFiMeasurement]) -> None:
        self._wifi.extend(measurements)
        self._wifi.sort(key=lambda item: item.timestamp)
        self._prune_window(self._wifi)

    def add_vision(self, detections: Iterable[Detection]) -> None:
        self._vision.extend(detections)
        self._vision.sort(key=lambda item: item.timestamp)
        self._prune_window(self._vision)

    def emit(self, reference_time: Optional[float] = None) -> Optional[SyncBatch]:
        if not self._wifi and not self._vision:
            return None

        reference_time = reference_time or self._latest_timestamp()
        dropped_wifi = self._drop_stale(self._wifi, reference_time)
        dropped_vision = self._drop_stale(self._vision, reference_time)

        wifi_aligned, wifi_stale = self._align_wifi(reference_time)
        vision_aligned, vision_stale = self._align_vision(reference_time)

        if not wifi_aligned and not vision_aligned:
            return None

        status = SyncStatus(
            reference_time=reference_time,
            wifi_stale=wifi_stale,
            vision_stale=vision_stale,
            dropped_wifi=dropped_wifi,
            dropped_vision=dropped_vision,
            window_seconds=self.window_seconds,
            max_latency_seconds=self.max_latency_seconds,
            strategy=self.strategy,
        )
        return SyncBatch(
            fusion_input=FusionInput(wifi=wifi_aligned, vision=vision_aligned),
            status=status,
        )

    def _latest_timestamp(self) -> float:
        latest = 0.0
        if self._wifi:
            latest = max(latest, self._wifi[-1].timestamp)
        if self._vision:
            latest = max(latest, self._vision[-1].timestamp)
        return latest

    def prune_history(
        self,
        *,
        ttl_seconds: float,
        reference_time: Optional[float] = None,
    ) -> Tuple[int, int]:
        if ttl_seconds <= 0:
            return 0, 0
        if reference_time is None:
            latest = self._latest_timestamp()
            reference_time = latest or time.time()
        cutoff = reference_time - ttl_seconds
        wifi_deleted = self._drop_before(self._wifi, cutoff)
        vision_deleted = self._drop_before(self._vision, cutoff)
        return wifi_deleted, vision_deleted

    def _prune_window(self, items: List) -> None:
        if not items:
            return
        latest_timestamp = items[-1].timestamp
        cutoff = latest_timestamp - self.window_seconds
        self._drop_before(items, cutoff)

    def _drop_stale(self, items: List, reference_time: float) -> int:
        cutoff = reference_time - self.max_latency_seconds
        return self._drop_before(items, cutoff)

    @staticmethod
    def _drop_before(items: List, cutoff: float) -> int:
        dropped = 0
        while items and items[0].timestamp < cutoff:
            items.pop(0)
            dropped += 1
        return dropped

    def _align_wifi(self, reference_time: float) -> Tuple[List[WiFiMeasurement], bool]:
        if not self._wifi:
            return [], True
        grouped: dict[str, List[WiFiMeasurement]] = {}
        for measurement in self._wifi:
            grouped.setdefault(measurement.access_point_id, []).append(measurement)

        aligned: List[WiFiMeasurement] = []
        for access_point_id, measurements in grouped.items():
            match = self._match_measurement(
                measurements,
                reference_time,
                access_point_id=access_point_id,
            )
            if match is not None:
                aligned.append(match)

        latest_timestamp = self._wifi[-1].timestamp if self._wifi else 0.0
        stale = reference_time - latest_timestamp > self.max_latency_seconds
        return aligned, stale

    def _align_vision(self, reference_time: float) -> Tuple[List[Detection], bool]:
        if not self._vision:
            return [], True
        grouped: dict[str, List[Detection]] = {}
        for detection in self._vision:
            grouped.setdefault(detection.camera_id, []).append(detection)

        aligned: List[Detection] = []
        for camera_id, detections in grouped.items():
            match = self._match_detection(detections, reference_time, camera_id=camera_id)
            if match is not None:
                aligned.append(match)

        latest_timestamp = self._vision[-1].timestamp if self._vision else 0.0
        stale = reference_time - latest_timestamp > self.max_latency_seconds
        return aligned, stale

    def _match_measurement(
        self,
        measurements: Sequence[WiFiMeasurement],
        reference_time: float,
        access_point_id: str,
    ) -> Optional[WiFiMeasurement]:
        if self.strategy == "interpolate":
            interpolated = self._interpolate_wifi(measurements, reference_time, access_point_id)
            if interpolated is not None:
                return interpolated
        return self._nearest_wifi(measurements, reference_time)

    def _match_detection(
        self,
        detections: Sequence[Detection],
        reference_time: float,
        camera_id: str,
    ) -> Optional[Detection]:
        if self.strategy == "interpolate":
            interpolated = self._interpolate_detection(detections, reference_time, camera_id)
            if interpolated is not None:
                return interpolated
        return self._nearest_detection(detections, reference_time)

    def _nearest_wifi(
        self,
        measurements: Sequence[WiFiMeasurement],
        reference_time: float,
    ) -> Optional[WiFiMeasurement]:
        nearest = min(measurements, key=lambda item: abs(item.timestamp - reference_time))
        if abs(nearest.timestamp - reference_time) > self.window_seconds:
            return None
        return nearest

    def _nearest_detection(
        self,
        detections: Sequence[Detection],
        reference_time: float,
    ) -> Optional[Detection]:
        nearest = min(detections, key=lambda item: abs(item.timestamp - reference_time))
        if abs(nearest.timestamp - reference_time) > self.window_seconds:
            return None
        return nearest

    def _interpolate_wifi(
        self,
        measurements: Sequence[WiFiMeasurement],
        reference_time: float,
        access_point_id: str,
    ) -> Optional[WiFiMeasurement]:
        before, after = self._bracket_measurements(measurements, reference_time)
        if before is None or after is None:
            return None
        if before.timestamp == after.timestamp:
            return before
        if (
            abs(before.timestamp - reference_time) > self.window_seconds
            or abs(after.timestamp - reference_time) > self.window_seconds
        ):
            return None
        ratio = (reference_time - before.timestamp) / (after.timestamp - before.timestamp)
        rssi = self._lerp(before.rssi, after.rssi, ratio)
        csi = self._lerp_sequence(before.csi, after.csi, ratio)
        return WiFiMeasurement(
            timestamp=reference_time,
            access_point_id=access_point_id,
            rssi=rssi,
            csi=csi,
            metadata=None,
        )

    def _interpolate_detection(
        self,
        detections: Sequence[Detection],
        reference_time: float,
        camera_id: str,
    ) -> Optional[Detection]:
        before, after = self._bracket_measurements(detections, reference_time)
        if before is None or after is None:
            return None
        if before.timestamp == after.timestamp:
            return before
        if (
            abs(before.timestamp - reference_time) > self.window_seconds
            or abs(after.timestamp - reference_time) > self.window_seconds
        ):
            return None
        ratio = (reference_time - before.timestamp) / (after.timestamp - before.timestamp)
        bbox = tuple(
            self._lerp(before.bbox[idx], after.bbox[idx], ratio) for idx in range(4)
        )
        confidence = self._lerp(before.confidence, after.confidence, ratio)
        keypoints = self._lerp_keypoints(before.keypoints, after.keypoints, ratio)
        return Detection(
            timestamp=reference_time,
            camera_id=camera_id,
            bbox=bbox,
            confidence=confidence,
            keypoints=keypoints,
        )

    def _bracket_measurements(self, items: Sequence, reference_time: float) -> Tuple:
        before = None
        after = None
        for item in items:
            if item.timestamp <= reference_time:
                before = item
            if item.timestamp >= reference_time:
                after = item
                if before is not None:
                    break
        return before, after

    def _lerp(self, left: float, right: float, ratio: float) -> float:
        return left + (right - left) * ratio

    def _lerp_sequence(
        self,
        left: Optional[Sequence[float]],
        right: Optional[Sequence[float]],
        ratio: float,
    ) -> Optional[Sequence[float]]:
        if left is None or right is None or len(left) != len(right):
            return None
        return [self._lerp(left[idx], right[idx], ratio) for idx in range(len(left))]

    def _lerp_keypoints(
        self,
        left: Optional[Sequence[Tuple[float, float]]],
        right: Optional[Sequence[Tuple[float, float]]],
        ratio: float,
    ) -> Optional[Sequence[Tuple[float, float]]]:
        if left is None or right is None or len(left) != len(right):
            return None
        interpolated = []
        for idx in range(len(left)):
            interpolated.append(
                (
                    self._lerp(left[idx][0], right[idx][0], ratio),
                    self._lerp(left[idx][1], right[idx][1], ratio),
                )
            )
        return interpolated
