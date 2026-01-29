from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Optional, Protocol, Sequence

from ..models import Detection, WiFiMeasurement
from ..sync import SyncBatch, SynchronizationBuffer


class WiFiSource(Protocol):
    def fetch(self) -> Sequence[WiFiMeasurement]: ...


class VisionSource(Protocol):
    def fetch(self) -> Sequence[Detection]: ...


@dataclass
class IngestionOrchestrator:
    """Coordinate Wi-Fi and vision ingestion and emit aligned FusionInput batches."""

    wifi_source: Optional[WiFiSource] = None
    vision_source: Optional[VisionSource] = None
    sync_buffer: SynchronizationBuffer = field(default_factory=SynchronizationBuffer)

    def poll(self, reference_time: Optional[float] = None) -> Optional[SyncBatch]:
        wifi_measurements: Sequence[WiFiMeasurement] = []
        vision_detections: Sequence[Detection] = []

        if self.wifi_source is not None:
            wifi_measurements = self.wifi_source.fetch()
            if wifi_measurements:
                self.sync_buffer.add_wifi(wifi_measurements)

        if self.vision_source is not None:
            vision_detections = self.vision_source.fetch()
            if vision_detections:
                self.sync_buffer.add_vision(vision_detections)

        if not wifi_measurements and not vision_detections:
            return None

        if reference_time is None:
            reference_time = time.time()

        return self.sync_buffer.emit(reference_time=reference_time)

    def emit_latest(self) -> Optional[SyncBatch]:
        return self.sync_buffer.emit()
