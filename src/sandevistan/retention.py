from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import threading
import time
from typing import Optional

from .audit import AuditLogger
from .config import RetentionConfig
from .sync import SynchronizationBuffer


@dataclass
class RetentionScheduler:
    retention_config: RetentionConfig
    buffer: Optional[SynchronizationBuffer] = None
    audit_logger: Optional[AuditLogger] = None
    _stop_event: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _thread: Optional[threading.Thread] = field(default=None, init=False, repr=False)

    def start(self) -> None:
        if not self.retention_config.is_enabled():
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="sandevistan-retention",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout_seconds: float = 1.0) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=timeout_seconds)

    def run_once(
        self,
        *,
        reference_time: Optional[float] = None,
        now: Optional[datetime] = None,
    ) -> dict[str, int]:
        deleted_measurements = 0
        deleted_logs = 0
        if self.buffer and self.retention_config.measurement_ttl_seconds:
            wifi_deleted, vision_deleted, mmwave_deleted, ble_deleted = self.buffer.prune_history(
                ttl_seconds=self.retention_config.measurement_ttl_seconds,
                reference_time=reference_time,
            )
            deleted_measurements = (
                wifi_deleted + vision_deleted + mmwave_deleted + ble_deleted
            )
        if self.audit_logger and self.retention_config.log_ttl_seconds:
            sensor_deleted, track_deleted = self.audit_logger.prune_logs(
                ttl_seconds=self.retention_config.log_ttl_seconds,
                now=now,
            )
            deleted_logs = sensor_deleted + track_deleted
        return {
            "deleted_measurements": deleted_measurements,
            "deleted_logs": deleted_logs,
        }

    def _run(self) -> None:
        interval = max(self.retention_config.cleanup_interval_seconds, 0.1)
        while not self._stop_event.wait(interval):
            reference_time = time.time()
            self.run_once(reference_time=reference_time, now=datetime.utcnow())
