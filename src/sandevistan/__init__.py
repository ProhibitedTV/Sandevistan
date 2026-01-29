"""Research prototype scaffolding for Sandevistan-inspired sensor fusion."""

from .audit import AuditLogger, ConsentError, ConsentStatus, InMemoryConsentStore
from .config import SensorConfig, SpaceConfig
from .models import Detection, FusionInput, TrackState, WiFiMeasurement
from .pipeline import FusionPipeline
from .sync import SyncBatch, SyncStatus, SynchronizationBuffer

__all__ = [
    "SensorConfig",
    "SpaceConfig",
    "AuditLogger",
    "ConsentError",
    "ConsentStatus",
    "InMemoryConsentStore",
    "Detection",
    "FusionInput",
    "TrackState",
    "WiFiMeasurement",
    "FusionPipeline",
    "SyncBatch",
    "SyncStatus",
    "SynchronizationBuffer",
]
