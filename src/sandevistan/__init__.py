"""Research prototype scaffolding for Sandevistan-inspired sensor fusion."""

from .audit import AuditLogger, ConsentError, ConsentStatus, InMemoryConsentStore
from .config import (
    AccessPointCalibration,
    CameraCalibration,
    CameraExtrinsics,
    CameraIntrinsics,
    RetentionConfig,
    SensorConfig,
    SpaceConfig,
)
from .display import LiveTrackerDisplay, render_from_stream
from .models import (
    AlertTier,
    BLEMeasurement,
    Detection,
    FusionInput,
    MmWaveMeasurement,
    TrackState,
    WiFiMeasurement,
    validate_ble_measurement,
    validate_mmwave_measurement,
)
from .pipeline import FusionPipeline
from .retention import RetentionScheduler
from .sync import SyncBatch, SyncStatus, SynchronizationBuffer

__all__ = [
    "SensorConfig",
    "SpaceConfig",
    "CameraIntrinsics",
    "CameraExtrinsics",
    "CameraCalibration",
    "AccessPointCalibration",
    "RetentionConfig",
    "AuditLogger",
    "ConsentError",
    "ConsentStatus",
    "InMemoryConsentStore",
    "Detection",
    "FusionInput",
    "MmWaveMeasurement",
    "BLEMeasurement",
    "AlertTier",
    "TrackState",
    "WiFiMeasurement",
    "validate_ble_measurement",
    "validate_mmwave_measurement",
    "FusionPipeline",
    "RetentionScheduler",
    "SyncBatch",
    "SyncStatus",
    "SynchronizationBuffer",
    "LiveTrackerDisplay",
    "render_from_stream",
]
