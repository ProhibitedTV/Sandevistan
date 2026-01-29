from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import logging
from typing import Iterable, List, Optional, Protocol, Sequence


class ConsentError(RuntimeError):
    """Raised when consent is missing or revoked."""


class ConsentStatus:
    GRANTED = "granted"
    REVOKED = "revoked"


@dataclass(frozen=True)
class ConsentRecord:
    status: str
    participant_id: Optional[str] = None
    session_id: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)


class ConsentStore(Protocol):
    def get_consent(
        self,
        *,
        participant_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Optional[ConsentRecord]:
        ...

    def set_consent(self, record: ConsentRecord) -> None:
        ...


class InMemoryConsentStore:
    def __init__(self) -> None:
        self._records: List[ConsentRecord] = []

    def get_consent(
        self,
        *,
        participant_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Optional[ConsentRecord]:
        for record in reversed(self._records):
            if participant_id and record.participant_id != participant_id:
                continue
            if session_id and record.session_id != session_id:
                continue
            return record
        return None

    def set_consent(self, record: ConsentRecord) -> None:
        self._records.append(record)


@dataclass(frozen=True)
class SensorProvenanceLog:
    track_id: str
    timestamp: float
    sources: Sequence[str]
    captured_at: datetime = field(default_factory=datetime.utcnow)


@dataclass(frozen=True)
class TrackUpdateLog:
    track_id: str
    timestamp: float
    sources: Sequence[str]
    captured_at: datetime = field(default_factory=datetime.utcnow)


class AuditLogger:
    def __init__(
        self,
        *,
        consent_store: ConsentStore | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._consent_store = consent_store or InMemoryConsentStore()
        self._logger = logger or logging.getLogger(__name__)
        self.sensor_provenance: List[SensorProvenanceLog] = []
        self.track_updates: List[TrackUpdateLog] = []

    def log_sensor_provenance(
        self, *, track_id: str, timestamp: float, sources: Iterable[str]
    ) -> SensorProvenanceLog:
        record = SensorProvenanceLog(
            track_id=track_id,
            timestamp=timestamp,
            sources=tuple(sources),
        )
        self.sensor_provenance.append(record)
        self._logger.info(
            "sensor_provenance",
            extra={
                "track_id": track_id,
                "timestamp": timestamp,
                "sources": list(record.sources),
            },
        )
        return record

    def log_track_update(
        self, *, track_id: str, timestamp: float, sources: Iterable[str]
    ) -> TrackUpdateLog:
        record = TrackUpdateLog(
            track_id=track_id,
            timestamp=timestamp,
            sources=tuple(sources),
        )
        self.track_updates.append(record)
        self._logger.info(
            "track_update",
            extra={
                "track_id": track_id,
                "timestamp": timestamp,
                "sources": list(record.sources),
            },
        )
        return record

    def record_consent(
        self,
        *,
        status: str,
        participant_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> ConsentRecord:
        if status not in {ConsentStatus.GRANTED, ConsentStatus.REVOKED}:
            raise ValueError(f"Unknown consent status: {status}")
        record = ConsentRecord(
            status=status,
            participant_id=participant_id,
            session_id=session_id,
        )
        self._consent_store.set_consent(record)
        self._logger.info(
            "consent_record",
            extra={
                "participant_id": participant_id,
                "session_id": session_id,
                "status": status,
                "timestamp": record.timestamp.isoformat(),
            },
        )
        return record

    def require_consent(
        self,
        *,
        participant_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> ConsentRecord:
        record = self._consent_store.get_consent(
            participant_id=participant_id,
            session_id=session_id,
        )
        if record is None:
            raise ConsentError("Consent record missing.")
        if record.status == ConsentStatus.REVOKED:
            raise ConsentError("Consent has been revoked.")
        return record
