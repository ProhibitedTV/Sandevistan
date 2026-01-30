from __future__ import annotations

import argparse
import base64
import io
import json
import queue
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence, Tuple

from .models import TrackState


@dataclass
class DeviceSnapshot:
    device_id: str
    rssi: Optional[float]
    last_seen: Optional[float]
    status: Optional[str] = None


@dataclass
class SensorHealthSnapshot:
    label: str
    status: str
    last_seen: Optional[float] = None
    detail: Optional[str] = None


@dataclass
class HudUpdate:
    tracks: List[TrackState] = field(default_factory=list)
    devices: List[DeviceSnapshot] = field(default_factory=list)
    sensor_health: List[SensorHealthSnapshot] = field(default_factory=list)
    mmwave_status: Optional[SensorHealthSnapshot] = None
    camera_bytes: Optional[bytes] = None
    waveform: Optional[Sequence[float]] = None
    waveform_timestamp: Optional[float] = None
    waveform_sample_rate: Optional[float] = None


@dataclass
class HudState:
    max_age_seconds: float = 4.0
    tracks: dict[str, TrackState] = field(default_factory=dict)
    devices: dict[str, DeviceSnapshot] = field(default_factory=dict)
    sensor_health: dict[str, SensorHealthSnapshot] = field(default_factory=dict)
    mmwave_status: Optional[SensorHealthSnapshot] = None
    camera_surface: Optional[object] = None
    camera_updated_at: Optional[float] = None
    waveform: Optional[Sequence[float]] = None
    waveform_timestamp: Optional[float] = None
    waveform_sample_rate: Optional[float] = None
    waveform_updated_at: Optional[float] = None

    def ingest_update(self, update: HudUpdate, pygame_module: object) -> None:
        for track in update.tracks:
            self.tracks[track.track_id] = track
        for device in update.devices:
            self.devices[device.device_id] = device
        for sensor in update.sensor_health:
            self.sensor_health[sensor.label] = sensor
        if update.mmwave_status is not None:
            self.mmwave_status = update.mmwave_status
        if update.camera_bytes is not None:
            surface = _decode_camera_frame(update.camera_bytes, pygame_module)
            if surface is not None:
                self.camera_surface = surface
                self.camera_updated_at = time.time()
        if update.waveform is not None:
            self.waveform = update.waveform
            self.waveform_timestamp = update.waveform_timestamp
            self.waveform_sample_rate = update.waveform_sample_rate
            self.waveform_updated_at = time.time()

    def prune(self, now: Optional[float] = None) -> None:
        if now is None:
            now = time.time()
        stale = [
            track_id
            for track_id, snapshot in self.tracks.items()
            if now - snapshot.timestamp > self.max_age_seconds
        ]
        for track_id in stale:
            self.tracks.pop(track_id, None)
        if (
            self.waveform_updated_at is not None
            and now - self.waveform_updated_at > self.max_age_seconds
        ):
            self.waveform = None
            self.waveform_timestamp = None
            self.waveform_sample_rate = None
            self.waveform_updated_at = None


def _decode_camera_frame(payload: bytes, pygame_module: object) -> Optional[object]:
    try:
        buffer = io.BytesIO(payload)
        surface = pygame_module.image.load(buffer)
        return surface.convert()
    except Exception:
        return None


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
    return f"{age:.1f}s"


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


def _parse_devices(raw: object) -> List[DeviceSnapshot]:
    if raw is None:
        return []
    entries: List[DeviceSnapshot] = []
    if isinstance(raw, dict):
        for device_id, value in raw.items():
            if isinstance(value, dict):
                rssi = _optional_float(value.get("rssi"))
                last_seen = _optional_float(value.get("last_seen") or value.get("timestamp"))
                status = value.get("status")
            else:
                rssi = _optional_float(value)
                last_seen = None
                status = None
            entries.append(
                DeviceSnapshot(
                    device_id=str(device_id),
                    rssi=rssi,
                    last_seen=last_seen,
                    status=str(status) if status is not None else None,
                )
            )
    elif isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            device_id = _first_string(
                item,
                ("device_id", "emitter_id", "id", "hashed_identifier"),
            )
            if device_id is None:
                continue
            rssi = _optional_float(item.get("rssi"))
            last_seen = _optional_float(item.get("last_seen") or item.get("timestamp"))
            status = item.get("status")
            entries.append(
                DeviceSnapshot(
                    device_id=device_id,
                    rssi=rssi,
                    last_seen=last_seen,
                    status=str(status) if status is not None else None,
                )
            )
    return entries


def _select_mmwave_status(entries: List[SensorHealthSnapshot]) -> Optional[SensorHealthSnapshot]:
    for entry in entries:
        if "mmwave" in entry.label.lower():
            return entry
    return None


def _parse_mmwave_status(payload: dict) -> Optional[SensorHealthSnapshot]:
    direct = payload.get("mmwave_status") or payload.get("mmwave")
    if isinstance(direct, dict):
        return SensorHealthSnapshot(
            label=str(direct.get("label", "mmwave")),
            status=str(direct.get("status", "unknown")),
            last_seen=_optional_float(direct.get("last_seen") or direct.get("timestamp")),
            detail=str(direct.get("detail")) if direct.get("detail") is not None else None,
        )
    sensors = _parse_sensor_health(payload.get("sensor_health") or payload.get("sensors"))
    return _select_mmwave_status(sensors)


def _parse_waveform(payload: dict) -> Tuple[Optional[List[float]], Optional[float], Optional[float]]:
    raw = payload.get("waveform") or payload.get("audio_waveform")
    if raw is None:
        return None, None, None
    if not isinstance(raw, list):
        return None, None, None
    samples: List[float] = []
    for value in raw:
        try:
            sample = float(value)
        except (TypeError, ValueError):
            continue
        if sample < -1.0:
            sample = -1.0
        elif sample > 1.0:
            sample = 1.0
        samples.append(sample)
    if not samples:
        return None, None, None
    timestamp = _optional_float(
        payload.get("waveform_timestamp")
        or payload.get("audio_waveform_timestamp")
        or payload.get("waveform_time")
    )
    sample_rate = _optional_float(
        payload.get("waveform_sample_rate")
        or payload.get("audio_sample_rate")
        or payload.get("sample_rate")
    )
    return samples, timestamp, sample_rate


def _extract_camera_bytes(payload: dict) -> Optional[bytes]:
    camera_frame = payload.get("camera_frame")
    if isinstance(camera_frame, str):
        return _decode_base64(camera_frame)
    camera = payload.get("camera")
    if isinstance(camera, dict):
        for key in ("frame", "image_base64", "frame_base64"):
            value = camera.get(key)
            if isinstance(value, str):
                return _decode_base64(value)
    return None


def _decode_base64(value: str) -> Optional[bytes]:
    try:
        return base64.b64decode(value)
    except (ValueError, TypeError):
        return None


def _parse_hud_update(payload: object) -> HudUpdate:
    if isinstance(payload, list):
        return HudUpdate(tracks=[_parse_track_state(item) for item in payload])
    if not isinstance(payload, dict):
        return HudUpdate()

    tracks: List[TrackState] = []
    if "tracks" in payload:
        raw_tracks = payload.get("tracks")
        if isinstance(raw_tracks, list):
            tracks.extend(_parse_track_state(item) for item in raw_tracks)
        elif isinstance(raw_tracks, dict):
            tracks.append(_parse_track_state(raw_tracks))
    elif "track_id" in payload:
        tracks.append(_parse_track_state(payload))

    devices = _parse_devices(payload.get("emitters") or payload.get("devices"))
    sensor_health = _parse_sensor_health(payload.get("sensor_health") or payload.get("sensors"))
    mmwave_status = _parse_mmwave_status(payload)
    if mmwave_status is not None and mmwave_status.label not in {
        sensor.label for sensor in sensor_health
    }:
        sensor_health.append(mmwave_status)
    camera_bytes = _extract_camera_bytes(payload)
    waveform, waveform_timestamp, waveform_sample_rate = _parse_waveform(payload)

    return HudUpdate(
        tracks=tracks,
        devices=devices,
        sensor_health=sensor_health,
        mmwave_status=mmwave_status,
        camera_bytes=camera_bytes,
        waveform=waveform,
        waveform_timestamp=waveform_timestamp,
        waveform_sample_rate=waveform_sample_rate,
    )


def _stream_updates(
    stream: Iterable[str],
    output_queue: "queue.Queue[HudUpdate]",
    stop_event: threading.Event,
) -> None:
    for line in stream:
        if stop_event.is_set():
            break
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        output_queue.put(_parse_hud_update(payload))


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


def _count_alert_tiers(tracks: Iterable[TrackState]) -> Tuple[int, int, int]:
    tiers = [track.alert_tier for track in tracks]
    red_count = sum(tier in {"red", "orange"} for tier in tiers)
    yellow_count = sum(tier == "yellow" for tier in tiers)
    blue_count = sum(tier == "blue" for tier in tiers)
    return red_count, yellow_count, blue_count


def _draw_text(
    pygame_module: object,
    surface: object,
    text: str,
    font: object,
    color: Tuple[int, int, int],
    position: Tuple[int, int],
) -> None:
    text_surface = font.render(text, True, color)
    surface.blit(text_surface, position)


def _render_hud(
    pygame_module: object,
    screen: object,
    state: HudState,
    font: object,
    small_font: object,
) -> None:
    screen_width, screen_height = screen.get_size()
    now = time.time()
    state.prune(now)

    background = (10, 12, 18)
    panel = (24, 28, 38)
    accent = (57, 62, 76)
    text_color = (220, 224, 232)
    muted_text = (160, 168, 180)

    screen.fill(background)
    margin = 24
    top_bar_height = 72
    content_top = margin + top_bar_height
    content_height = screen_height - content_top - margin
    content_width = screen_width - 2 * margin

    top_rect = pygame_module.Rect(margin, margin, content_width, top_bar_height)
    pygame_module.draw.rect(screen, panel, top_rect, border_radius=10)

    red_count, yellow_count, blue_count = _count_alert_tiers(state.tracks.values())
    _draw_text(
        pygame_module,
        screen,
        "Alert tiers",
        font,
        text_color,
        (top_rect.x + 18, top_rect.y + 18),
    )
    badge_y = top_rect.y + 18
    badge_x = top_rect.x + 210
    for label, count, color in (
        ("RED", red_count, (220, 76, 86)),
        ("YELLOW", yellow_count, (240, 192, 90)),
        ("BLUE", blue_count, (92, 162, 224)),
    ):
        pygame_module.draw.circle(screen, color, (badge_x, badge_y + 12), 10)
        _draw_text(
            pygame_module,
            screen,
            f"{label}: {count}",
            small_font,
            text_color,
            (badge_x + 18, badge_y + 2),
        )
        badge_x += 140

    total_tracks = len(state.tracks)
    _draw_text(
        pygame_module,
        screen,
        f"Tracks: {total_tracks}",
        small_font,
        muted_text,
        (top_rect.right - 160, badge_y + 2),
    )

    camera_width = int(content_width * 0.68)
    camera_rect = pygame_module.Rect(margin, content_top, camera_width, content_height)
    info_rect = pygame_module.Rect(
        margin + camera_width + margin,
        content_top,
        content_width - camera_width - margin,
        content_height,
    )

    pygame_module.draw.rect(screen, panel, camera_rect, border_radius=12)
    pygame_module.draw.rect(screen, panel, info_rect, border_radius=12)

    if state.camera_surface is not None:
        surface = state.camera_surface
        surface_rect = surface.get_rect()
        scale = min(
            (camera_rect.width - 20) / surface_rect.width,
            (camera_rect.height - 20) / surface_rect.height,
        )
        scaled_size = (
            max(int(surface_rect.width * scale), 1),
            max(int(surface_rect.height * scale), 1),
        )
        scaled = pygame_module.transform.smoothscale(surface, scaled_size)
        target_rect = scaled.get_rect(center=camera_rect.center)
        screen.blit(scaled, target_rect)
    else:
        _draw_text(
            pygame_module,
            screen,
            "Waiting for camera feed...",
            font,
            muted_text,
            (camera_rect.x + 24, camera_rect.y + 24),
        )

    camera_age = (
        _format_age(now, state.camera_updated_at)
        if state.camera_updated_at is not None
        else "n/a"
    )
    _draw_text(
        pygame_module,
        screen,
        f"Camera updated: {camera_age}",
        small_font,
        muted_text,
        (camera_rect.x + 24, camera_rect.bottom - 36),
    )

    info_x = info_rect.x + 20
    info_y = info_rect.y + 20

    _draw_text(
        pygame_module,
        screen,
        "Sensor status",
        font,
        text_color,
        (info_x, info_y),
    )
    info_y += 36
    sensor_entries = list(state.sensor_health.values())
    if not sensor_entries and state.mmwave_status is not None:
        sensor_entries.append(state.mmwave_status)
    if not sensor_entries:
        _draw_text(
            pygame_module,
            screen,
            "No sensor data",
            small_font,
            muted_text,
            (info_x, info_y),
        )
        info_y += 28
    else:
        sensor_entries = sorted(sensor_entries, key=lambda item: item.label)
        for sensor in sensor_entries:
            status = sensor.status
            status_color = (
                (106, 210, 134) if status.lower() == "online" else (220, 76, 86)
            )
            last_seen = _format_age(now, sensor.last_seen)
            detail = f" ({sensor.detail})" if sensor.detail else ""
            _draw_text(
                pygame_module,
                screen,
                f"{sensor.label}: {status}{detail}",
                small_font,
                status_color,
                (info_x, info_y),
            )
            info_y += 20
            _draw_text(
                pygame_module,
                screen,
                f"Last seen: {last_seen}",
                small_font,
                muted_text,
                (info_x, info_y),
            )
            info_y += 24
            if info_y > info_rect.bottom - 120:
                break
        info_y += 6

    pygame_module.draw.line(
        screen,
        accent,
        (info_rect.x + 16, info_y),
        (info_rect.right - 16, info_y),
        2,
    )
    info_y += 20

    _draw_text(
        pygame_module,
        screen,
        "Device list",
        font,
        text_color,
        (info_x, info_y),
    )
    info_y += 36
    if not state.devices:
        _draw_text(
            pygame_module,
            screen,
            "No devices",
            small_font,
            muted_text,
            (info_x, info_y),
        )
    else:
        devices = sorted(
            state.devices.values(),
            key=lambda item: (item.rssi is None, -(item.rssi or -999.0)),
        )
        for device in devices[:10]:
            rssi = f"{device.rssi:.1f} dBm" if device.rssi is not None else "n/a"
            age = _format_age(now, device.last_seen)
            status = f" ({device.status})" if device.status else ""
            _draw_text(
                pygame_module,
                screen,
                f"{device.device_id}: {rssi} · {age}{status}",
                small_font,
                muted_text,
                (info_x, info_y),
            )
            info_y += 22
            if info_y > info_rect.bottom - 24:
                break


def render_from_stream(
    stream: Iterable[str],
    max_age_seconds: float,
    fps: int,
    windowed: bool,
    window_size: Tuple[int, int],
) -> None:
    import pygame

    pygame.init()
    pygame.display.set_caption("Sandevistan HUD")
    flags = pygame.FULLSCREEN
    if windowed:
        flags = 0
    screen = pygame.display.set_mode(window_size if windowed else (0, 0), flags)
    clock = pygame.time.Clock()
    font = pygame.font.Font(None, 36)
    small_font = pygame.font.Font(None, 24)

    state = HudState(max_age_seconds=max_age_seconds)
    updates_queue: "queue.Queue[HudUpdate]" = queue.Queue()
    stop_event = threading.Event()
    reader = threading.Thread(
        target=_stream_updates,
        args=(stream, updates_queue, stop_event),
        daemon=True,
    )
    reader.start()

    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False

        while True:
            try:
                update = updates_queue.get_nowait()
            except queue.Empty:
                break
            state.ingest_update(update, pygame)

        _render_hud(pygame, screen, state, font, small_font)
        pygame.display.flip()
        clock.tick(max(fps, 1))

    stop_event.set()
    pygame.quit()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Sandevistan full-screen HUD consumer.")
    parser.add_argument(
        "--max-age",
        type=float,
        default=4.0,
        help="Seconds before a track is considered stale (default: 4.0).",
    )
    parser.add_argument(
        "--fps",
        type=int,
        default=30,
        help="Frame rate for the HUD refresh (default: 30).",
    )
    parser.add_argument(
        "--windowed",
        action="store_true",
        help="Run in a window instead of full screen.",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=1280,
        help="Window width when --windowed is set (default: 1280).",
    )
    parser.add_argument(
        "--height",
        type=int,
        default=720,
        help="Window height when --windowed is set (default: 720).",
    )
    args = parser.parse_args(argv)

    render_from_stream(
        sys.stdin,
        max_age_seconds=args.max_age,
        fps=args.fps,
        windowed=args.windowed,
        window_size=(args.width, args.height),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
