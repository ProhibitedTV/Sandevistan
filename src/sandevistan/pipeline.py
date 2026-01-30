from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import math
import time
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .audit import AuditLogger
from .config import MmWaveCalibration, SensorConfig, SpaceConfig
from .models import BLEMeasurement, FusionInput, MmWaveMeasurement, TrackState, WiFiMeasurement
from .retention import RetentionScheduler


@dataclass
class _TrackMemory:
    track_id: str
    timestamp: float
    state: Tuple[float, float, float, float]
    covariance: List[List[float]]
    position: Tuple[float, float]
    velocity: Optional[Tuple[float, float]]
    uncertainty: Tuple[float, float]
    confidence: float
    status: str
    hits: int
    misses: int


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
    audit_logger: Optional[AuditLogger] = None
    require_consent: bool = True
    retention_scheduler: Optional[RetentionScheduler] = None
    _tracks: Dict[str, _TrackMemory] = field(default_factory=dict, init=False, repr=False)
    _next_track_id: int = field(default=1, init=False, repr=False)
    _confirm_hits: int = field(default=2, init=False, repr=False)
    _lost_misses: int = field(default=2, init=False, repr=False)
    _terminate_misses: int = field(default=4, init=False, repr=False)

    def fuse(self, measurements: FusionInput) -> List[TrackState]:
        """
        Fuse Wi-Fi and vision measurements into track states.

        This method is intentionally minimal; real implementations should include
        synchronization, filtering, and track association.
        """
        if (
            not measurements.wifi
            and not measurements.vision
            and not measurements.mmwave
            and not measurements.ble
        ):
            return []

        synced_wifi, synced_vision, synced_mmwave, synced_ble, reference_time = self._synchronize(
            measurements.wifi,
            measurements.vision,
            measurements.mmwave,
            measurements.ble,
        )
        return self._fuse_aligned(
            synced_wifi,
            synced_vision,
            synced_mmwave,
            synced_ble,
            reference_time,
        )

    def fuse_aligned(self, measurements: FusionInput, reference_time: float) -> List[TrackState]:
        """
        Fuse already-aligned measurements using the provided reference time.
        """
        if (
            not measurements.wifi
            and not measurements.vision
            and not measurements.mmwave
            and not measurements.ble
        ):
            return []
        return self._fuse_aligned(
            measurements.wifi,
            measurements.vision,
            measurements.mmwave,
            measurements.ble,
            reference_time,
        )

    def _fuse_aligned(
        self,
        wifi: Sequence,
        vision: Sequence,
        mmwave: Sequence,
        ble: Sequence,
        reference_time: float,
    ) -> List[TrackState]:
        alert_tier = self._classify_alert_tier(
            wifi,
            vision,
            mmwave,
            ble,
        )
        sources = self._collect_sources(
            wifi,
            vision,
            mmwave,
            ble,
        )
        candidates = self._build_candidates(
            wifi, vision, mmwave, reference_time
        )
        assignments, unassigned_tracks, unassigned_candidates = self._associate_tracks(
            candidates, reference_time
        )

        updated_tracks: List[TrackState] = []
        for track_id, candidate in assignments:
            updated = self._update_track(track_id, candidate)
            if updated.status != "terminated":
                updated_tracks.append(self._to_track_state(updated, alert_tier))

        for track_id in unassigned_tracks:
            updated = self._mark_missed(track_id, reference_time)
            if updated and updated.status != "terminated":
                updated_tracks.append(self._to_track_state(updated, alert_tier))

        for candidate in unassigned_candidates:
            updated = self._initialize_track(candidate)
            updated_tracks.append(self._to_track_state(updated, alert_tier))

        if self.audit_logger and updated_tracks:
            if self.require_consent:
                self.audit_logger.require_consent()
            for update in updated_tracks:
                self.audit_logger.log_sensor_provenance(
                    track_id=update.track_id,
                    timestamp=update.timestamp,
                    sources=sources,
                )
                self.audit_logger.log_track_update(
                    track_id=update.track_id,
                    timestamp=update.timestamp,
                    sources=sources,
                )

        return updated_tracks

    def _synchronize(
        self,
        wifi: Sequence,
        vision: Sequence,
        mmwave: Sequence,
        ble: Sequence,
        window_seconds: float = 0.5,
    ) -> Tuple[Sequence, Sequence, Sequence, Sequence, float]:
        reference_time = 0.0
        if wifi:
            reference_time = max(reference_time, max(m.timestamp for m in wifi))
        if vision:
            reference_time = max(reference_time, max(m.timestamp for m in vision))
        if mmwave:
            reference_time = max(reference_time, max(m.timestamp for m in mmwave))
        if ble:
            reference_time = max(reference_time, max(m.timestamp for m in ble))

        def _filter(seq: Sequence) -> Sequence:
            if not seq:
                return seq
            aligned = [m for m in seq if abs(m.timestamp - reference_time) <= window_seconds]
            if aligned:
                return aligned
            latest = max(seq, key=lambda m: m.timestamp)
            return [latest]

        return _filter(wifi), _filter(vision), _filter(mmwave), _filter(ble), reference_time

    def _collect_sources(
        self,
        wifi: Sequence,
        vision: Sequence,
        mmwave: Sequence[MmWaveMeasurement],
        ble: Sequence[BLEMeasurement],
    ) -> List[str]:
        sources: List[str] = []
        seen = set()
        for measurement in wifi:
            source = f"wifi:{measurement.access_point_id}"
            if source not in seen:
                sources.append(source)
                seen.add(source)
        for detection in vision:
            source = f"vision:{detection.camera_id}"
            if source not in seen:
                sources.append(source)
                seen.add(source)
        for measurement in mmwave:
            source = f"mmwave:{measurement.sensor_id}"
            if source not in seen:
                sources.append(source)
                seen.add(source)
        for measurement in ble:
            identifier = measurement.device_id or measurement.hashed_identifier or "unknown"
            source = f"ble:{identifier}"
            if source not in seen:
                sources.append(source)
                seen.add(source)
        return sources

    def _build_candidates(
        self,
        wifi: Sequence,
        vision: Sequence,
        mmwave: Sequence[MmWaveMeasurement],
        reference_time: float,
    ) -> List[_MeasurementCandidate]:
        wifi_position, wifi_confidence = self._estimate_wifi_position(wifi)
        wifi_uncertainty = (
            (1.5, 1.5) if wifi_position else (2.5, 2.5)
        )
        mmwave_position, mmwave_confidence, mmwave_uncertainty = self._estimate_mmwave_position(
            mmwave
        )
        candidates: List[_MeasurementCandidate] = []

        if vision:
            for detection in vision:
                vision_position = self._estimate_vision_position(detection)
                measurement_bundle = [
                    (vision_position, (0.8, 0.8), detection.confidence)
                ]
                if wifi_position:
                    measurement_bundle.append(
                        (wifi_position, wifi_uncertainty, wifi_confidence)
                    )
                if mmwave_position:
                    measurement_bundle.append(
                        (mmwave_position, mmwave_uncertainty, mmwave_confidence)
                    )
                fused_position, uncertainty, fused_confidence = self._blend_measurements(
                    measurement_bundle
                )
                candidates.append(
                    _MeasurementCandidate(
                        timestamp=reference_time,
                        position=fused_position,
                        uncertainty=uncertainty,
                        confidence=fused_confidence,
                    )
                )
        elif wifi_position or mmwave_position:
            measurement_bundle = []
            if wifi_position:
                measurement_bundle.append((wifi_position, wifi_uncertainty, wifi_confidence))
            if mmwave_position:
                measurement_bundle.append(
                    (mmwave_position, mmwave_uncertainty, mmwave_confidence)
                )
            fused_position, uncertainty, fused_confidence = self._blend_measurements(
                measurement_bundle
            )
            candidates.append(
                _MeasurementCandidate(
                    timestamp=reference_time,
                    position=fused_position,
                    uncertainty=uncertainty,
                    confidence=fused_confidence,
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
        calibration = self.sensor_config.cameras.get(detection.camera_id)
        if calibration and calibration.homography:
            projected = self._apply_homography((center_x, y_max), calibration.homography)
            if projected is not None:
                return projected
        return self._fallback_bbox_position(center_x, center_y)

    def _apply_homography(
        self,
        point: Tuple[float, float],
        homography: Tuple[Tuple[float, float, float], ...],
    ) -> Optional[Tuple[float, float]]:
        x_img, y_img = point
        h00, h01, h02 = homography[0]
        h10, h11, h12 = homography[1]
        h20, h21, h22 = homography[2]
        denominator = h20 * x_img + h21 * y_img + h22
        if abs(denominator) < 1e-6:
            return None
        x_world = (h00 * x_img + h01 * y_img + h02) / denominator
        y_world = (h10 * x_img + h11 * y_img + h12) / denominator
        return (x_world, y_world)

    def _fallback_bbox_position(self, center_x: float, center_y: float) -> Tuple[float, float]:
        origin_x, origin_y = self.space_config.coordinate_origin
        if 0.0 <= center_x <= 1.0 and 0.0 <= center_y <= 1.0:
            return (
                origin_x + center_x * self.space_config.width_meters,
                origin_y + center_y * self.space_config.height_meters,
            )
        return (center_x, center_y)

    def _estimate_mmwave_position(
        self,
        mmwave: Sequence[MmWaveMeasurement],
    ) -> Tuple[Optional[Tuple[float, float]], float, Tuple[float, float]]:
        best_position: Optional[Tuple[float, float]] = None
        best_confidence = 0.0
        best_uncertainty = (2.0, 2.0)

        for measurement in mmwave:
            calibration = self.sensor_config.mmwave_sensors.get(measurement.sensor_id)
            if calibration is None:
                continue
            position = self._mmwave_measurement_to_position(measurement, calibration)
            if position is None:
                continue
            uncertainty_scale = 1.0
            if measurement.range_meters is None or measurement.angle_radians is None:
                uncertainty_scale = 1.5
            uncertainty = (
                calibration.position_uncertainty_meters * uncertainty_scale,
                calibration.position_uncertainty_meters * uncertainty_scale,
            )
            if measurement.confidence >= best_confidence:
                best_position = position
                best_confidence = measurement.confidence
                best_uncertainty = uncertainty

        return best_position, best_confidence, best_uncertainty

    def _mmwave_measurement_to_position(
        self,
        measurement: MmWaveMeasurement,
        calibration: MmWaveCalibration,
    ) -> Optional[Tuple[float, float]]:
        if measurement.range_meters is None or measurement.angle_radians is None:
            return calibration.position
        adjusted_range = measurement.range_meters + calibration.range_bias_meters
        adjusted_angle = (
            measurement.angle_radians
            + calibration.angle_bias_radians
            + calibration.rotation_radians
        )
        return (
            calibration.position[0] + adjusted_range * math.cos(adjusted_angle),
            calibration.position[1] + adjusted_range * math.sin(adjusted_angle),
        )

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

    def _blend_measurements(
        self,
        measurements: Sequence[Tuple[Tuple[float, float], Tuple[float, float], float]],
    ) -> Tuple[Tuple[float, float], Tuple[float, float], float]:
        if not measurements:
            return (0.0, 0.0), (2.5, 2.5), 0.0
        total_confidence = sum(confidence for _, _, confidence in measurements)
        total_confidence = max(total_confidence, 1e-3)
        weighted_x = sum(position[0] * confidence for position, _, confidence in measurements)
        weighted_y = sum(position[1] * confidence for position, _, confidence in measurements)
        weighted_uncertainty_x = sum(
            uncertainty[0] * confidence for _, uncertainty, confidence in measurements
        )
        weighted_uncertainty_y = sum(
            uncertainty[1] * confidence for _, uncertainty, confidence in measurements
        )
        position = (weighted_x / total_confidence, weighted_y / total_confidence)
        uncertainty = (
            weighted_uncertainty_x / total_confidence,
            weighted_uncertainty_y / total_confidence,
        )
        fused_confidence = min(
            1.0, sum(confidence for _, _, confidence in measurements) / len(measurements)
        )
        return position, uncertainty, fused_confidence

    def _associate_tracks(
        self,
        candidates: List[_MeasurementCandidate],
        reference_time: float,
        max_distance: float = 3.0,
    ) -> Tuple[
        List[Tuple[str, _MeasurementCandidate]],
        List[str],
        List[_MeasurementCandidate],
    ]:
        if not self._tracks:
            return [], [], candidates

        track_ids = list(self._tracks.keys())
        if not candidates:
            return [], track_ids, []

        cost_matrix: List[List[float]] = []
        distance_matrix: List[List[float]] = []
        gating_cost = max_distance * 10.0

        for track_id in track_ids:
            track = self._tracks[track_id]
            predicted_position, _, _ = self._predict_state(track, reference_time)
            row_costs: List[float] = []
            row_distances: List[float] = []
            for candidate in candidates:
                distance = self._distance(predicted_position, candidate.position)
                row_distances.append(distance)
                row_costs.append(distance if distance <= max_distance else gating_cost)
            cost_matrix.append(row_costs)
            distance_matrix.append(row_distances)

        assignments = self._hungarian_assign(cost_matrix)
        matched: List[Tuple[str, _MeasurementCandidate]] = []
        assigned_tracks = set()
        assigned_candidates = set()
        for row, col in assignments:
            if row >= len(track_ids) or col >= len(candidates):
                continue
            distance = distance_matrix[row][col]
            if distance > max_distance:
                continue
            track_id = track_ids[row]
            matched.append((track_id, candidates[col]))
            assigned_tracks.add(track_id)
            assigned_candidates.add(col)

        unassigned_tracks = [tid for tid in track_ids if tid not in assigned_tracks]
        unassigned_candidates = [
            candidate for idx, candidate in enumerate(candidates) if idx not in assigned_candidates
        ]
        return matched, unassigned_tracks, unassigned_candidates

    def _update_track(self, track_id: str, candidate: _MeasurementCandidate) -> _TrackMemory:
        existing = self._tracks.get(track_id)
        if existing is None:
            return self._initialize_track(candidate, track_id=track_id)

        _, predicted_state, predicted_covariance = self._predict_state(
            existing, candidate.timestamp
        )
        updated_state, updated_covariance = self._kalman_update(
            predicted_state,
            predicted_covariance,
            candidate.position,
            candidate.uncertainty,
        )
        hits = existing.hits + 1
        misses = 0
        status = existing.status
        if status in {"init", "lost"} and hits >= self._confirm_hits:
            status = "confirmed"
        elif status == "init":
            status = "init"

        updated_confidence = min(
            1.0, 0.7 * existing.confidence + 0.3 * candidate.confidence
        )
        updated = self._make_track_memory(
            track_id=track_id,
            timestamp=candidate.timestamp,
            state=updated_state,
            covariance=updated_covariance,
            confidence=updated_confidence,
            status=status,
            hits=hits,
            misses=misses,
        )
        self._tracks[track_id] = updated
        return updated

    def _kalman_update(
        self,
        predicted_state: Tuple[float, float, float, float],
        predicted_covariance: List[List[float]],
        measurement: Tuple[float, float],
        measurement_uncertainty: Tuple[float, float],
    ) -> Tuple[Tuple[float, float, float, float], List[List[float]]]:
        h_matrix = [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
        ]
        measurement_noise = [
            [measurement_uncertainty[0] ** 2, 0.0],
            [0.0, measurement_uncertainty[1] ** 2],
        ]
        projected_covariance = self._mat_mult_2x4_4x4(
            h_matrix, predicted_covariance
        )
        residual_covariance = self._mat_add_2x2(
            self._mat_mult_2x4_4x2(projected_covariance, self._transpose_2x4(h_matrix)),
            measurement_noise,
        )
        residual_covariance_inv = self._invert_2x2(residual_covariance)
        kalman_gain = self._mat_mult_4x4_4x2(
            predicted_covariance,
            self._mat_mult_4x2_2x2(
                self._transpose_2x4(h_matrix),
                residual_covariance_inv,
            ),
        )

        residual = [
            measurement[0] - predicted_state[0],
            measurement[1] - predicted_state[1],
        ]
        updated_state = list(predicted_state)
        for i in range(4):
            updated_state[i] += kalman_gain[i][0] * residual[0] + kalman_gain[i][1] * residual[1]

        identity = self._identity_4x4()
        kh = self._mat_mult_4x2_2x4(kalman_gain, h_matrix)
        updated_covariance = self._mat_mult_4x4_4x4(
            self._mat_sub_4x4(identity, kh),
            predicted_covariance,
        )
        return (updated_state[0], updated_state[1], updated_state[2], updated_state[3]), updated_covariance

    def _predict_state(
        self, track: _TrackMemory, timestamp: float
    ) -> Tuple[
        Tuple[float, float],
        Tuple[float, float, float, float],
        List[List[float]],
    ]:
        dt = max(timestamp - track.timestamp, 0.0)
        transition = [
            [1.0, 0.0, dt, 0.0],
            [0.0, 1.0, 0.0, dt],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ]
        process_noise = self._process_noise(dt, 0.5)
        predicted_state = self._mat_vec_mult_4x4(transition, track.state)
        predicted_covariance = self._mat_add_4x4(
            self._mat_mult_4x4_4x4(
                self._mat_mult_4x4_4x4(transition, track.covariance),
                self._transpose_4x4(transition),
            ),
            process_noise,
        )
        position = (predicted_state[0], predicted_state[1])
        return position, (
            predicted_state[0],
            predicted_state[1],
            predicted_state[2],
            predicted_state[3],
        ), predicted_covariance

    def _mark_missed(self, track_id: str, timestamp: float) -> Optional[_TrackMemory]:
        track = self._tracks.get(track_id)
        if track is None:
            return None
        position, predicted_state, predicted_covariance = self._predict_state(track, timestamp)
        misses = track.misses + 1
        status = track.status
        if misses >= self._terminate_misses:
            status = "terminated"
        elif misses >= self._lost_misses:
            status = "lost"
        updated_confidence = max(0.0, track.confidence * 0.85)
        updated = self._make_track_memory(
            track_id=track_id,
            timestamp=timestamp,
            state=predicted_state,
            covariance=predicted_covariance,
            confidence=updated_confidence,
            status=status,
            hits=track.hits,
            misses=misses,
        )
        if status == "terminated":
            self._tracks.pop(track_id, None)
        else:
            self._tracks[track_id] = updated
        return updated

    def _initialize_track(
        self, candidate: _MeasurementCandidate, track_id: Optional[str] = None
    ) -> _TrackMemory:
        if track_id is None:
            track_id = self._new_track_id()
        position = candidate.position
        state = (position[0], position[1], 0.0, 0.0)
        covariance = [
            [candidate.uncertainty[0] ** 2, 0.0, 0.0, 0.0],
            [0.0, candidate.uncertainty[1] ** 2, 0.0, 0.0],
            [0.0, 0.0, 4.0, 0.0],
            [0.0, 0.0, 0.0, 4.0],
        ]
        updated = self._make_track_memory(
            track_id=track_id,
            timestamp=candidate.timestamp,
            state=state,
            covariance=covariance,
            confidence=candidate.confidence,
            status="init",
            hits=1,
            misses=0,
        )
        self._tracks[track_id] = updated
        return updated

    def _make_track_memory(
        self,
        track_id: str,
        timestamp: float,
        state: Tuple[float, float, float, float],
        covariance: List[List[float]],
        confidence: float,
        status: str,
        hits: int,
        misses: int,
    ) -> _TrackMemory:
        position = (state[0], state[1])
        velocity = (state[2], state[3])
        uncertainty = (
            math.sqrt(max(covariance[0][0], 0.0)),
            math.sqrt(max(covariance[1][1], 0.0)),
        )
        return _TrackMemory(
            track_id=track_id,
            timestamp=timestamp,
            state=state,
            covariance=covariance,
            position=position,
            velocity=velocity,
            uncertainty=uncertainty,
            confidence=confidence,
            status=status,
            hits=hits,
            misses=misses,
        )

    def _to_track_state(self, track: _TrackMemory, alert_tier: str) -> TrackState:
        return TrackState(
            track_id=track.track_id,
            timestamp=track.timestamp,
            position=track.position,
            velocity=track.velocity,
            uncertainty=track.uncertainty,
            confidence=track.confidence,
            alert_tier=alert_tier,
        )

    def _classify_alert_tier(
        self,
        wifi: Sequence[WiFiMeasurement],
        vision: Sequence,
        mmwave: Sequence[MmWaveMeasurement],
        ble: Sequence[BLEMeasurement],
    ) -> str:
        mmwave_present = bool(mmwave)
        vision_present = bool(vision)
        wifi_anomaly = self._has_wifi_anomaly(wifi)
        ble_present = bool(ble)

        if mmwave_present and vision_present:
            return "red"
        if mmwave_present and wifi_anomaly:
            return "orange"
        if mmwave_present:
            return "yellow"
        if wifi_anomaly:
            return "orange"
        if ble_present:
            return "blue"
        return "none"

    def _has_wifi_anomaly(self, wifi: Sequence[WiFiMeasurement]) -> bool:
        for measurement in wifi:
            if not measurement.metadata:
                continue
            metadata = measurement.metadata
            if metadata.get("anomaly") is True or metadata.get("is_anomaly") is True:
                return True
            score = metadata.get("anomaly_score", metadata.get("anomaly_confidence"))
            if isinstance(score, (int, float)) and score >= 0.7:
                return True
        return False

    def _distance(self, left: Tuple[float, float], right: Tuple[float, float]) -> float:
        return math.hypot(left[0] - right[0], left[1] - right[1])

    def _new_track_id(self) -> str:
        track_id = f"track-{self._next_track_id}"
        self._next_track_id += 1
        return track_id

    def _rssi_to_confidence(self, rssi: float) -> float:
        normalized = max(min((rssi + 100.0) / 60.0, 1.0), 0.0)
        return 0.2 + 0.8 * normalized

    def _hungarian_assign(self, cost_matrix: List[List[float]]) -> List[Tuple[int, int]]:
        if not cost_matrix or not cost_matrix[0]:
            return []
        row_count = len(cost_matrix)
        col_count = len(cost_matrix[0])
        size = max(row_count, col_count)
        padded_cost = [row + [max(map(max, cost_matrix)) + 1.0] * (size - col_count) for row in cost_matrix]
        for _ in range(size - row_count):
            padded_cost.append([max(map(max, cost_matrix)) + 1.0] * size)

        cost = [row[:] for row in padded_cost]
        for i in range(size):
            row_min = min(cost[i])
            for j in range(size):
                cost[i][j] -= row_min
        for j in range(size):
            col_min = min(cost[i][j] for i in range(size))
            for i in range(size):
                cost[i][j] -= col_min

        star = [[False] * size for _ in range(size)]
        prime = [[False] * size for _ in range(size)]
        row_covered = [False] * size
        col_covered = [False] * size

        for i in range(size):
            for j in range(size):
                if cost[i][j] == 0 and not row_covered[i] and not col_covered[j]:
                    star[i][j] = True
                    row_covered[i] = True
                    col_covered[j] = True
        row_covered = [False] * size
        col_covered = [False] * size

        def cover_columns_with_star() -> None:
            for j in range(size):
                col_covered[j] = any(star[i][j] for i in range(size))

        cover_columns_with_star()

        while sum(col_covered) < size:
            zero = None
            while zero is None:
                for i in range(size):
                    if row_covered[i]:
                        continue
                    for j in range(size):
                        if col_covered[j]:
                            continue
                        if cost[i][j] == 0:
                            zero = (i, j)
                            break
                    if zero is not None:
                        break
                if zero is None:
                    min_uncovered = min(
                        cost[i][j]
                        for i in range(size)
                        if not row_covered[i]
                        for j in range(size)
                        if not col_covered[j]
                    )
                    for i in range(size):
                        for j in range(size):
                            if row_covered[i]:
                                cost[i][j] += min_uncovered
                            if not col_covered[j]:
                                cost[i][j] -= min_uncovered
            row, col = zero
            prime[row][col] = True
            star_col = next((j for j in range(size) if star[row][j]), None)
            if star_col is None:
                path = [(row, col)]
                while True:
                    star_row = next((i for i in range(size) if star[i][path[-1][1]]), None)
                    if star_row is None:
                        break
                    path.append((star_row, path[-1][1]))
                    prime_col = next(j for j in range(size) if prime[path[-1][0]][j])
                    path.append((path[-1][0], prime_col))
                for path_row, path_col in path:
                    star[path_row][path_col] = not star[path_row][path_col]
                prime = [[False] * size for _ in range(size)]
                row_covered = [False] * size
                col_covered = [False] * size
                cover_columns_with_star()
                zero = None
            else:
                row_covered[row] = True
                col_covered[star_col] = False
                zero = None

        results = []
        for i in range(size):
            for j in range(size):
                if star[i][j]:
                    results.append((i, j))
        return results

    def _process_noise(self, dt: float, noise_scale: float) -> List[List[float]]:
        dt2 = dt * dt
        dt3 = dt2 * dt
        dt4 = dt2 * dt2
        q = noise_scale
        return [
            [q * dt4 / 4.0, 0.0, q * dt3 / 2.0, 0.0],
            [0.0, q * dt4 / 4.0, 0.0, q * dt3 / 2.0],
            [q * dt3 / 2.0, 0.0, q * dt2, 0.0],
            [0.0, q * dt3 / 2.0, 0.0, q * dt2],
        ]

    def _mat_vec_mult_4x4(
        self, matrix: List[List[float]], vector: Tuple[float, float, float, float]
    ) -> Tuple[float, float, float, float]:
        return (
            matrix[0][0] * vector[0]
            + matrix[0][1] * vector[1]
            + matrix[0][2] * vector[2]
            + matrix[0][3] * vector[3],
            matrix[1][0] * vector[0]
            + matrix[1][1] * vector[1]
            + matrix[1][2] * vector[2]
            + matrix[1][3] * vector[3],
            matrix[2][0] * vector[0]
            + matrix[2][1] * vector[1]
            + matrix[2][2] * vector[2]
            + matrix[2][3] * vector[3],
            matrix[3][0] * vector[0]
            + matrix[3][1] * vector[1]
            + matrix[3][2] * vector[2]
            + matrix[3][3] * vector[3],
        )

    def _mat_mult_4x4_4x4(
        self, left: List[List[float]], right: List[List[float]]
    ) -> List[List[float]]:
        result = [[0.0] * 4 for _ in range(4)]
        for i in range(4):
            for j in range(4):
                result[i][j] = sum(left[i][k] * right[k][j] for k in range(4))
        return result

    def _mat_mult_4x4_4x2(
        self, left: List[List[float]], right: List[List[float]]
    ) -> List[List[float]]:
        result = [[0.0] * 2 for _ in range(4)]
        for i in range(4):
            for j in range(2):
                result[i][j] = sum(left[i][k] * right[k][j] for k in range(4))
        return result

    def _mat_mult_4x2_2x4(
        self, left: List[List[float]], right: List[List[float]]
    ) -> List[List[float]]:
        result = [[0.0] * 4 for _ in range(4)]
        for i in range(4):
            for j in range(4):
                result[i][j] = sum(left[i][k] * right[k][j] for k in range(2))
        return result

    def _mat_mult_4x2_2x2(
        self, left: List[List[float]], right: List[List[float]]
    ) -> List[List[float]]:
        result = [[0.0] * 2 for _ in range(4)]
        for i in range(4):
            for j in range(2):
                result[i][j] = sum(left[i][k] * right[k][j] for k in range(2))
        return result

    def _mat_mult_2x4_4x4(
        self, left: List[List[float]], right: List[List[float]]
    ) -> List[List[float]]:
        result = [[0.0] * 4 for _ in range(2)]
        for i in range(2):
            for j in range(4):
                result[i][j] = sum(left[i][k] * right[k][j] for k in range(4))
        return result

    def _mat_mult_2x4_4x2(
        self, left: List[List[float]], right: List[List[float]]
    ) -> List[List[float]]:
        result = [[0.0] * 2 for _ in range(2)]
        for i in range(2):
            for j in range(2):
                result[i][j] = sum(left[i][k] * right[k][j] for k in range(4))
        return result

    def _mat_add_4x4(
        self, left: List[List[float]], right: List[List[float]]
    ) -> List[List[float]]:
        return [
            [left[i][j] + right[i][j] for j in range(4)]
            for i in range(4)
        ]

    def _mat_sub_4x4(
        self, left: List[List[float]], right: List[List[float]]
    ) -> List[List[float]]:
        return [
            [left[i][j] - right[i][j] for j in range(4)]
            for i in range(4)
        ]

    def _mat_add_2x2(
        self, left: List[List[float]], right: List[List[float]]
    ) -> List[List[float]]:
        return [
            [left[i][j] + right[i][j] for j in range(2)]
            for i in range(2)
        ]

    def _transpose_4x4(self, matrix: List[List[float]]) -> List[List[float]]:
        return [[matrix[j][i] for j in range(4)] for i in range(4)]

    def _transpose_2x4(self, matrix: List[List[float]]) -> List[List[float]]:
        return [[matrix[j][i] for j in range(2)] for i in range(4)]

    def _invert_2x2(self, matrix: List[List[float]]) -> List[List[float]]:
        det = matrix[0][0] * matrix[1][1] - matrix[0][1] * matrix[1][0]
        if abs(det) < 1e-6:
            return [[0.0, 0.0], [0.0, 0.0]]
        inv_det = 1.0 / det
        return [
            [matrix[1][1] * inv_det, -matrix[0][1] * inv_det],
            [-matrix[1][0] * inv_det, matrix[0][0] * inv_det],
        ]

    def _identity_4x4(self) -> List[List[float]]:
        return [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ]

    def stream(self, inputs: Iterable[FusionInput]) -> Iterable[List[TrackState]]:
        for measurement in inputs:
            updates = self.fuse(measurement)
            if self.retention_scheduler:
                reference_time = self._reference_time_from_input(measurement)
                self.retention_scheduler.run_once(
                    reference_time=reference_time,
                    now=datetime.utcnow(),
                )
            yield updates

    def _reference_time_from_input(self, measurements: FusionInput) -> float:
        reference_time = 0.0
        if measurements.wifi:
            reference_time = max(reference_time, max(m.timestamp for m in measurements.wifi))
        if measurements.vision:
            reference_time = max(reference_time, max(m.timestamp for m in measurements.vision))
        if measurements.mmwave:
            reference_time = max(
                reference_time, max(m.timestamp for m in measurements.mmwave)
            )
        if measurements.ble:
            reference_time = max(reference_time, max(m.timestamp for m in measurements.ble))
        return reference_time or time.time()
