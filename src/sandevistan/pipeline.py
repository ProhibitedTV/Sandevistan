from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .config import SensorConfig, SpaceConfig
from .models import FusionInput, TrackState


@dataclass
class _TrackMemory:
    track_id: str
    timestamp: float
    position: Tuple[float, float]
    velocity: Optional[Tuple[float, float]]
    uncertainty: Tuple[float, float]
    confidence: float


@dataclass
class _MeasurementCandidate:
    timestamp: float
    position: Tuple[float, float]
    uncertainty: Tuple[float, float]
    confidence: float


@dataclass
class FusionPipeline:
    sensor_config: SensorConfig
    space_config: SpaceConfig
    _tracks: Dict[str, _TrackMemory] = field(default_factory=dict, init=False, repr=False)
    _next_track_id: int = field(default=1, init=False, repr=False)

    def fuse(self, measurements: FusionInput) -> List[TrackState]:
        """
        Fuse Wi-Fi and vision measurements into track states.

        This method is intentionally minimal; real implementations should include
        synchronization, filtering, and track association.
        """
        if not measurements.wifi and not measurements.vision:
            return []

        synced_wifi, synced_vision, reference_time = self._synchronize(
            measurements.wifi, measurements.vision
        )
        candidates = self._build_candidates(synced_wifi, synced_vision, reference_time)
        if not candidates:
            return []

        assignments = self._associate_tracks(candidates)
        updated_tracks: List[TrackState] = []
        for track_id, candidate in assignments:
            updated = self._update_track(track_id, candidate)
            updated_tracks.append(
                TrackState(
                    track_id=updated.track_id,
                    timestamp=updated.timestamp,
                    position=updated.position,
                    velocity=updated.velocity,
                    uncertainty=updated.uncertainty,
                    confidence=updated.confidence,
                )
            )

        return updated_tracks

    def _synchronize(
        self,
        wifi: Sequence,
        vision: Sequence,
        window_seconds: float = 0.5,
    ) -> Tuple[Sequence, Sequence, float]:
        reference_time = 0.0
        if wifi:
            reference_time = max(reference_time, max(m.timestamp for m in wifi))
        if vision:
            reference_time = max(reference_time, max(m.timestamp for m in vision))

        def _filter(seq: Sequence) -> Sequence:
            if not seq:
                return seq
            aligned = [m for m in seq if abs(m.timestamp - reference_time) <= window_seconds]
            if aligned:
                return aligned
            latest = max(seq, key=lambda m: m.timestamp)
            return [latest]

        return _filter(wifi), _filter(vision), reference_time

    def _build_candidates(
        self,
        wifi: Sequence,
        vision: Sequence,
        reference_time: float,
    ) -> List[_MeasurementCandidate]:
        wifi_position, wifi_confidence = self._estimate_wifi_position(wifi)
        wifi_uncertainty = (
            (1.5, 1.5) if wifi_position else (2.5, 2.5)
        )
        candidates: List[_MeasurementCandidate] = []

        if vision:
            for detection in vision:
                vision_position = self._estimate_vision_position(detection)
                if wifi_position:
                    fused_position = self._blend_positions(
                        vision_position,
                        wifi_position,
                        detection.confidence,
                        wifi_confidence,
                    )
                    fused_confidence = min(1.0, 0.5 * detection.confidence + 0.5 * wifi_confidence)
                    uncertainty = self._blend_uncertainty(
                        (0.8, 0.8),
                        wifi_uncertainty,
                        detection.confidence,
                        wifi_confidence,
                    )
                else:
                    fused_position = vision_position
                    fused_confidence = detection.confidence
                    uncertainty = (0.8, 0.8)
                candidates.append(
                    _MeasurementCandidate(
                        timestamp=reference_time,
                        position=fused_position,
                        uncertainty=uncertainty,
                        confidence=fused_confidence,
                    )
                )
        elif wifi_position:
            candidates.append(
                _MeasurementCandidate(
                    timestamp=reference_time,
                    position=wifi_position,
                    uncertainty=wifi_uncertainty,
                    confidence=wifi_confidence,
                )
            )

        return candidates

    def _estimate_wifi_position(
        self, wifi: Sequence
    ) -> Tuple[Optional[Tuple[float, float]], float]:
        if not wifi:
            return None, 0.0
        weighted_x = 0.0
        weighted_y = 0.0
        total_weight = 0.0
        confidences = []
        for measurement in wifi:
            calibration = self.sensor_config.wifi_access_points.get(measurement.access_point_id)
            if not calibration:
                continue
            weight = max(1.0, 100.0 + measurement.rssi)
            weighted_x += calibration.position[0] * weight
            weighted_y += calibration.position[1] * weight
            total_weight += weight
            confidences.append(self._rssi_to_confidence(measurement.rssi))
        if total_weight == 0.0:
            return None, 0.0
        position = (weighted_x / total_weight, weighted_y / total_weight)
        confidence = sum(confidences) / max(len(confidences), 1)
        return position, confidence

    def _estimate_vision_position(self, detection) -> Tuple[float, float]:
        x_min, y_min, x_max, y_max = detection.bbox
        center_x = (x_min + x_max) / 2.0
        center_y = (y_min + y_max) / 2.0
        origin_x, origin_y = self.space_config.coordinate_origin
        if 0.0 <= center_x <= 1.0 and 0.0 <= center_y <= 1.0:
            return (
                origin_x + center_x * self.space_config.width_meters,
                origin_y + center_y * self.space_config.height_meters,
            )
        return (center_x, center_y)

    def _blend_positions(
        self,
        vision_pos: Tuple[float, float],
        wifi_pos: Tuple[float, float],
        vision_confidence: float,
        wifi_confidence: float,
    ) -> Tuple[float, float]:
        total = max(vision_confidence + wifi_confidence, 1e-3)
        return (
            (vision_pos[0] * vision_confidence + wifi_pos[0] * wifi_confidence) / total,
            (vision_pos[1] * vision_confidence + wifi_pos[1] * wifi_confidence) / total,
        )

    def _blend_uncertainty(
        self,
        vision_uncertainty: Tuple[float, float],
        wifi_uncertainty: Tuple[float, float],
        vision_confidence: float,
        wifi_confidence: float,
    ) -> Tuple[float, float]:
        total = max(vision_confidence + wifi_confidence, 1e-3)
        return (
            (vision_uncertainty[0] * vision_confidence + wifi_uncertainty[0] * wifi_confidence)
            / total,
            (vision_uncertainty[1] * vision_confidence + wifi_uncertainty[1] * wifi_confidence)
            / total,
        )

    def _associate_tracks(
        self, candidates: List[_MeasurementCandidate], max_distance: float = 3.0
    ) -> List[Tuple[str, _MeasurementCandidate]]:
        if not self._tracks:
            return [(self._new_track_id(), candidate) for candidate in candidates]

        assignments: List[Tuple[str, _MeasurementCandidate]] = []
        available_tracks = dict(self._tracks)
        for candidate in candidates:
            best_track_id = None
            best_distance = float("inf")
            for track_id, track in available_tracks.items():
                predicted_pos = self._predict_position(track, candidate.timestamp)
                distance = self._distance(predicted_pos, candidate.position)
                if distance < best_distance:
                    best_distance = distance
                    best_track_id = track_id
            if best_track_id is not None and best_distance <= max_distance:
                assignments.append((best_track_id, candidate))
                available_tracks.pop(best_track_id, None)
            else:
                assignments.append((self._new_track_id(), candidate))
        return assignments

    def _update_track(self, track_id: str, candidate: _MeasurementCandidate) -> _TrackMemory:
        existing = self._tracks.get(track_id)
        if existing is None:
            updated = _TrackMemory(
                track_id=track_id,
                timestamp=candidate.timestamp,
                position=candidate.position,
                velocity=None,
                uncertainty=candidate.uncertainty,
                confidence=candidate.confidence,
            )
            self._tracks[track_id] = updated
            return updated

        dt = max(candidate.timestamp - existing.timestamp, 1e-3)
        predicted_pos = self._predict_position(existing, candidate.timestamp)
        predicted_uncertainty = (
            existing.uncertainty[0] + 0.25 * dt,
            existing.uncertainty[1] + 0.25 * dt,
        )
        updated_pos = self._kalman_update(
            predicted_pos,
            predicted_uncertainty,
            candidate.position,
            candidate.uncertainty,
        )
        velocity = (
            (updated_pos[0] - existing.position[0]) / dt,
            (updated_pos[1] - existing.position[1]) / dt,
        )
        updated_uncertainty = (
            min(predicted_uncertainty[0], candidate.uncertainty[0]),
            min(predicted_uncertainty[1], candidate.uncertainty[1]),
        )
        updated_confidence = min(
            1.0, 0.6 * existing.confidence + 0.4 * candidate.confidence
        )
        updated = _TrackMemory(
            track_id=track_id,
            timestamp=candidate.timestamp,
            position=updated_pos,
            velocity=velocity,
            uncertainty=updated_uncertainty,
            confidence=updated_confidence,
        )
        self._tracks[track_id] = updated
        return updated

    def _kalman_update(
        self,
        predicted: Tuple[float, float],
        predicted_uncertainty: Tuple[float, float],
        measurement: Tuple[float, float],
        measurement_uncertainty: Tuple[float, float],
    ) -> Tuple[float, float]:
        gain_x = predicted_uncertainty[0] / (
            predicted_uncertainty[0] + measurement_uncertainty[0]
        )
        gain_y = predicted_uncertainty[1] / (
            predicted_uncertainty[1] + measurement_uncertainty[1]
        )
        return (
            predicted[0] + gain_x * (measurement[0] - predicted[0]),
            predicted[1] + gain_y * (measurement[1] - predicted[1]),
        )

    def _predict_position(self, track: _TrackMemory, timestamp: float) -> Tuple[float, float]:
        if track.velocity is None:
            return track.position
        dt = max(timestamp - track.timestamp, 0.0)
        return (
            track.position[0] + track.velocity[0] * dt,
            track.position[1] + track.velocity[1] * dt,
        )

    def _distance(self, left: Tuple[float, float], right: Tuple[float, float]) -> float:
        return math.hypot(left[0] - right[0], left[1] - right[1])

    def _new_track_id(self) -> str:
        track_id = f"track-{self._next_track_id}"
        self._next_track_id += 1
        return track_id

    def _rssi_to_confidence(self, rssi: float) -> float:
        normalized = max(min((rssi + 100.0) / 60.0, 1.0), 0.0)
        return 0.2 + 0.8 * normalized

    def stream(self, inputs: Iterable[FusionInput]) -> Iterable[List[TrackState]]:
        for measurement in inputs:
            yield self.fuse(measurement)
