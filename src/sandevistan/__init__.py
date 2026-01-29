"""Research prototype scaffolding for Sandevistan-inspired sensor fusion."""

from .audit import AuditLogger, ConsentError, ConsentStatus, InMemoryConsentStore
from .config import RetentionConfig, SensorConfig, SpaceConfig
from .models import Detection, FusionInput, TrackState, WiFiMeasurement
from .pipeline import FusionPipeline
from .retention import RetentionScheduler
from .sync import SyncBatch, SyncStatus, SynchronizationBuffer

__all__ = [
    "SensorConfig",
    "SpaceConfig",
    "RetentionConfig",
    "AuditLogger",
    "ConsentError",
    "ConsentStatus",
    "InMemoryConsentStore",
    "Detection",
    "FusionInput",
    "TrackState",
    "WiFiMeasurement",
    "FusionPipeline",
    "RetentionScheduler",
    "SyncBatch",
    "SyncStatus",
    "SynchronizationBuffer",
]
