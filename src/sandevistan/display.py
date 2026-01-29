from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

from .config import SpaceConfig
from .models import TrackState


@dataclass
class TrackSnapshot:
    track_id: str
    timestamp: float
    position: Tuple[float, float]
    velocity: Optional[Tuple[float, float]]
    uncertainty: Tuple[float, float]
    alert_tier: str


@dataclass
class SensorHealthSnapshot:
    label: str
    status: str
    last_seen: Optional[float] = None
    detail: Optional[str] = None


@dataclass
class EmitterSnapshot:
    emitter_id: str
    rssi: Optional[float]
    last_seen: Optional[float] = None
    previous_rssi: Optional[float] = None


@dataclass
class DisplayUpdate:
    tracks: List[TrackState] = field(default_factory=list)
    sensor_health: List[SensorHealthSnapshot] = field(default_factory=list)
    emitters: List[EmitterSnapshot] = field(default_factory=list)


@dataclass
class LiveTrackerDisplay:
    space_config: SpaceConfig
    grid_width: int = 40
    grid_height: int = 16
    max_age_seconds: float = 4.0
    _tracks: Dict[str, TrackSnapshot] = field(default_factory=dict, init=False)
    _sensor_health: Dict[str, SensorHealthSnapshot] = field(default_factory=dict, init=False)
    _emitters: Dict[str, EmitterSnapshot] = field(default_factory=dict, init=False)

    def ingest(self, update: TrackState) -> None:
        self._tracks[update.track_id] = TrackSnapshot(
            track_id=update.track_id,
            timestamp=update.timestamp,
            position=update.position,
            velocity=update.velocity,
            uncertainty=update.uncertainty,
            alert_tier=update.alert_tier,
        )

    def ingest_update(self, update: DisplayUpdate) -> None:
        for track in update.tracks:
            self.ingest(track)
        for sensor in update.sensor_health:
            self._sensor_health[sensor.label] = sensor
        for emitter in update.emitters:
            current = self._emitters.get(emitter.emitter_id)
            emitter.previous_rssi = current.rssi if current is not None else None
            self._emitters[emitter.emitter_id] = emitter

    def prune(self, now: Optional[float] = None) -> None:
        if now is None:
            now = time.time()
        stale = [
            track_id
            for track_id, snapshot in self._tracks.items()
            if now - snapshot.timestamp > self.max_age_seconds
        ]
        for track_id in stale:
            self._tracks.pop(track_id, None)

    def render(self) -> str:
        now = time.time()
        self.prune(now)
        header = "Live Tracker View"
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
        lines = [header, f"Updated: {timestamp}", ""]
        lines.extend(self._render_alert_tiers())
        lines.append("")
        lines.extend(self._render_track_list())
        lines.append("")
        lines.extend(self._render_sensor_health(now))
        lines.append("")
        lines.extend(self._render_emitters(now))
        lines.append("")
        lines.extend(self._render_floor_plan())
        return "\n".join(lines)

    def _render_alert_tiers(self) -> List[str]:
        tiers = [snapshot.alert_tier for snapshot in self._tracks.values()]
        red_count = sum(tier in {"red", "orange"} for tier in tiers)
        yellow_count = sum(tier == "yellow" for tier in tiers)
        blue_count = sum(tier == "blue" for tier in tiers)
        if not any([red_count, yellow_count, blue_count]):
            return ["Alert tiers: none"]
        return [
            "Alert tiers: 🔴 {red} | 🟡 {yellow} | 🔵 {blue}".format(
                red=red_count,
                yellow=yellow_count,
                blue=blue_count,
            )
        ]

    def _render_track_list(self) -> List[str]:
        if not self._tracks:
            return ["No active tracks."]
        lines = ["Active tracks:"]
        for snapshot in sorted(self._tracks.values(), key=lambda item: item.track_id):
            vx, vy = snapshot.velocity if snapshot.velocity is not None else (None, None)
            velocity_text = (
                f"({vx:.2f}, {vy:.2f}) m/s" if vx is not None and vy is not None else "n/a"
            )
            ux, uy = snapshot.uncertainty
            lines.append(
                "- {track_id}: pos=({x:.2f}, {y:.2f}) m, vel={velocity}, "
                "uncertainty=({ux:.2f}, {uy:.2f}), alert={alert}".format(
                    track_id=snapshot.track_id,
                    x=snapshot.position[0],
                    y=snapshot.position[1],
                    velocity=velocity_text,
                    ux=ux,
                    uy=uy,
                    alert=snapshot.alert_tier,
                )
            )
        return lines

    def _render_sensor_health(self, now: float) -> List[str]:
        if not self._sensor_health:
            return ["Sensor health: no data"]
        lines = ["Sensor health:"]
        for sensor in sorted(self._sensor_health.values(), key=lambda item: item.label):
            last_seen_text = (
                _format_age(now, sensor.last_seen) if sensor.last_seen is not None else "n/a"
            )
            detail = f" ({sensor.detail})" if sensor.detail else ""
            lines.append(
                "- {label}: {status} (last seen {last_seen}){detail}".format(
                    label=sensor.label,
                    status=sensor.status,
                    last_seen=last_seen_text,
                    detail=detail,
                )
            )
        return lines

    def _render_emitters(self, now: float) -> List[str]:
        if not self._emitters:
            return ["Active emitters: none"]
        lines = ["Active emitters (RSSI trends):"]
        emitters = sorted(
            self._emitters.values(),
            key=lambda item: (item.rssi is None, -(item.rssi or -999.0)),
        )
        for emitter in emitters:
            trend_symbol, delta = _format_rssi_trend(emitter.previous_rssi, emitter.rssi)
            rssi_text = f"{emitter.rssi:.1f} dBm" if emitter.rssi is not None else "n/a"
            delta_text = f" {delta:+.1f} dB" if delta is not None else ""
            last_seen_text = (
                _format_age(now, emitter.last_seen) if emitter.last_seen is not None else "n/a"
            )
            lines.append(
                "- {emitter_id}: {rssi} {trend}{delta} (last seen {last_seen})".format(
                    emitter_id=emitter.emitter_id,
                    rssi=rssi_text,
                    trend=trend_symbol,
                    delta=delta_text,
                    last_seen=last_seen_text,
                )
            )
        return lines

    def _render_floor_plan(self) -> List[str]:
        grid = [["·" for _ in range(self.grid_width)] for _ in range(self.grid_height)]
        origin_x, origin_y = self.space_config.coordinate_origin
        width = max(self.space_config.width_meters, 1e-3)
        height = max(self.space_config.height_meters, 1e-3)
        for snapshot in self._tracks.values():
            rel_x = (snapshot.position[0] - origin_x) / width
            rel_y = (snapshot.position[1] - origin_y) / height
            col = min(max(int(rel_x * (self.grid_width - 1)), 0), self.grid_width - 1)
            row = min(max(int(rel_y * (self.grid_height - 1)), 0), self.grid_height - 1)
            grid[self.grid_height - 1 - row][col] = "●"
        lines = ["Floor-plan (top-down placeholder):"]
        lines.extend("".join(row) for row in grid)
        return lines


def _parse_track_state(payload: dict) -> TrackState:
    return TrackState(
        track_id=payload["track_id"],
        timestamp=float(payload["timestamp"]),
        position=tuple(payload["position"]),
        velocity=tuple(payload["velocity"]) if payload.get("velocity") is not None else None,
        uncertainty=tuple(payload["uncertainty"]),
        confidence=float(payload.get("confidence", 1.0)),
        alert_tier=str(payload.get("alert_tier", "none")),
    )


def _parse_sensor_health(raw: object) -> List[SensorHealthSnapshot]:
    if raw is None:
        return []
    entries: List[SensorHealthSnapshot] = []
    if isinstance(raw, dict):
        for label, value in raw.items():
            if isinstance(value, dict):
                status = str(value.get("status", "unknown"))
                last_seen = _optional_float(value.get("last_seen"))
                detail = value.get("detail")
            else:
                status = str(value)
                last_seen = None
                detail = None
            entries.append(
                SensorHealthSnapshot(
                    label=str(label),
                    status=status,
                    last_seen=last_seen,
                    detail=str(detail) if detail is not None else None,
                )
            )
    elif isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            label = _sensor_label(item)
            status = str(item.get("status", "unknown"))
            last_seen = _optional_float(item.get("last_seen") or item.get("timestamp"))
            detail = item.get("detail")
            entries.append(
                SensorHealthSnapshot(
                    label=label,
                    status=status,
                    last_seen=last_seen,
                    detail=str(detail) if detail is not None else None,
                )
            )
    return entries


def _parse_emitters(raw: object) -> List[EmitterSnapshot]:
    if raw is None:
        return []
    entries: List[EmitterSnapshot] = []
    if isinstance(raw, dict):
        for emitter_id, value in raw.items():
            if isinstance(value, dict):
                rssi = _optional_float(value.get("rssi"))
                last_seen = _optional_float(value.get("last_seen") or value.get("timestamp"))
            else:
                rssi = _optional_float(value)
                last_seen = None
            entries.append(
                EmitterSnapshot(
                    emitter_id=str(emitter_id),
                    rssi=rssi,
                    last_seen=last_seen,
                )
            )
    elif isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            emitter_id = _first_string(
                item,
                ("emitter_id", "id", "device_id", "hashed_identifier"),
            )
            if emitter_id is None:
                continue
            rssi = _optional_float(item.get("rssi"))
            last_seen = _optional_float(item.get("last_seen") or item.get("timestamp"))
            entries.append(
                EmitterSnapshot(emitter_id=emitter_id, rssi=rssi, last_seen=last_seen)
            )
    return entries


def _parse_display_update(payload: object) -> DisplayUpdate:
    if isinstance(payload, list):
        return DisplayUpdate(tracks=[_parse_track_state(item) for item in payload])
    if not isinstance(payload, dict):
        return DisplayUpdate()

    tracks: List[TrackState] = []
    if "tracks" in payload:
        raw_tracks = payload.get("tracks")
        if isinstance(raw_tracks, list):
            tracks.extend(_parse_track_state(item) for item in raw_tracks)
        elif isinstance(raw_tracks, dict):
            tracks.append(_parse_track_state(raw_tracks))
    elif "track_id" in payload:
        tracks.append(_parse_track_state(payload))

    sensor_health = _parse_sensor_health(payload.get("sensor_health") or payload.get("sensors"))
    emitters = _parse_emitters(payload.get("emitters") or payload.get("active_emitters"))
    return DisplayUpdate(tracks=tracks, sensor_health=sensor_health, emitters=emitters)


def _iter_updates(stream: Iterable[str]) -> Iterable[DisplayUpdate]:
    for line in stream:
        line = line.strip()
        if not line:
            continue
        payload = json.loads(line)
        yield _parse_display_update(payload)


def render_from_stream(
    updates: Iterable[DisplayUpdate],
    space_config: SpaceConfig,
    refresh_every: int = 1,
) -> None:
    display = LiveTrackerDisplay(space_config=space_config)
    count = 0
    for update in updates:
        display.ingest_update(update)
        count += 1
        if count % max(refresh_every, 1) == 0:
            _print_frame(display.render())


def _print_frame(content: str) -> None:
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.write(content)
    sys.stdout.write("\n")
    sys.stdout.flush()


def _optional_float(value: object) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_age(now: float, timestamp: Optional[float]) -> str:
    if timestamp is None:
        return "n/a"
    age = max(now - timestamp, 0.0)
    return f"{age:.1f}s ago"


def _format_rssi_trend(
    previous: Optional[float], current: Optional[float]
) -> Tuple[str, Optional[float]]:
    if previous is None or current is None:
        return "·", None
    delta = current - previous
    if delta > 1.0:
        symbol = "↑"
    elif delta < -1.0:
        symbol = "↓"
    else:
        symbol = "→"
    return symbol, delta


def _first_string(payload: dict, keys: Tuple[str, ...]) -> Optional[str]:
    for key in keys:
        value = payload.get(key)
        if value is not None:
            return str(value)
    return None


def _sensor_label(payload: dict) -> str:
    label = payload.get("label")
    if label is not None:
        return str(label)
    sensor_type = payload.get("type")
    sensor_id = payload.get("sensor_id")
    if sensor_type and sensor_id:
        return f"{sensor_type}:{sensor_id}"
    if sensor_type:
        return str(sensor_type)
    if sensor_id:
        return str(sensor_id)
    return "unknown"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Live tracker display consumer.")
    parser.add_argument(
        "--space-width",
        type=float,
        default=10.0,
        help="Width of the space in meters (default: 10.0).",
    )
    parser.add_argument(
        "--space-height",
        type=float,
        default=6.0,
        help="Height of the space in meters (default: 6.0).",
    )
    parser.add_argument(
        "--origin-x",
        type=float,
        default=0.0,
        help="Origin x-coordinate for the space (default: 0.0).",
    )
    parser.add_argument(
        "--origin-y",
        type=float,
        default=0.0,
        help="Origin y-coordinate for the space (default: 0.0).",
    )
    parser.add_argument(
        "--refresh-every",
        type=int,
        default=1,
        help="Render after N updates (default: 1).",
    )
    args = parser.parse_args(argv)

    space = SpaceConfig(
        width_meters=args.space_width,
        height_meters=args.space_height,
        coordinate_origin=(args.origin_x, args.origin_y),
    )
    try:
        render_from_stream(_iter_updates(sys.stdin), space, refresh_every=args.refresh_every)
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
