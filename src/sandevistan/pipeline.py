from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List

from .config import SensorConfig, SpaceConfig
from .models import FusionInput, TrackState


@dataclass
class FusionPipeline:
    sensor_config: SensorConfig
    space_config: SpaceConfig

    def fuse(self, measurements: FusionInput) -> List[TrackState]:
        """
        Fuse Wi-Fi and vision measurements into track states.

        This method is intentionally minimal; real implementations should include
        synchronization, filtering, and track association.
        """
        if not measurements.wifi and not measurements.vision:
            return []

        raise NotImplementedError(
            "Fusion logic is not implemented yet."
        )

    def stream(self, inputs: Iterable[FusionInput]) -> Iterable[List[TrackState]]:
        for measurement in inputs:
            yield self.fuse(measurement)
