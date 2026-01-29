from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Optional, Protocol, Sequence

from ..models import Detection, MmWaveMeasurement, WiFiMeasurement
from ..sync import SyncBatch, SynchronizationBuffer


class WiFiSource(Protocol):
    def fetch(self) -> Sequence[WiFiMeasurement]: ...


class VisionSource(Protocol):
    def fetch(self) -> Sequence[Detection]: ...


class MmWaveSource(Protocol):
    def fetch(self) -> Sequence[MmWaveMeasurement]: ...


@dataclass
class IngestionOrchestrator:
    """Coordinate Wi-Fi, vision, and mmWave ingestion and emit aligned FusionInput batches."""

    wifi_source: Optional[WiFiSource] = None
    vision_source: Optional[VisionSource] = None
    mmwave_source: Optional[MmWaveSource] = None
    sync_buffer: SynchronizationBuffer = field(default_factory=SynchronizationBuffer)

    def poll(self, reference_time: Optional[float] = None) -> Optional[SyncBatch]:
        wifi_measurements: Sequence[WiFiMeasurement] = []
        vision_detections: Sequence[Detection] = []
        mmwave_measurements: Sequence[MmWaveMeasurement] = []

        if self.wifi_source is not None:
            wifi_measurements = self.wifi_source.fetch()
            if wifi_measurements:
                self.sync_buffer.add_wifi(wifi_measurements)

        if self.vision_source is not None:
            vision_detections = self.vision_source.fetch()
            if vision_detections:
                self.sync_buffer.add_vision(vision_detections)

        if self.mmwave_source is not None:
            mmwave_measurements = self.mmwave_source.fetch()
            if mmwave_measurements:
                self.sync_buffer.add_mmwave(mmwave_measurements)

        if not wifi_measurements and not vision_detections and not mmwave_measurements:
            return None

        if reference_time is None:
            reference_time = time.time()

        return self.sync_buffer.emit(reference_time=reference_time)

    def emit_latest(self) -> Optional[SyncBatch]:
        return self.sync_buffer.emit()
