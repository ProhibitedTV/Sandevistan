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


@dataclass
class LiveTrackerDisplay:
    space_config: SpaceConfig
    grid_width: int = 40
    grid_height: int = 16
    max_age_seconds: float = 4.0
    _tracks: Dict[str, TrackSnapshot] = field(default_factory=dict, init=False)

    def ingest(self, update: TrackState) -> None:
        self._tracks[update.track_id] = TrackSnapshot(
            track_id=update.track_id,
            timestamp=update.timestamp,
            position=update.position,
            velocity=update.velocity,
            uncertainty=update.uncertainty,
        )

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
        self.prune()
        header = "Live Tracker View"
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        lines = [header, f"Updated: {timestamp}", ""]
        lines.extend(self._render_track_list())
        lines.append("")
        lines.extend(self._render_floor_plan())
        return "\n".join(lines)

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
                "uncertainty=({ux:.2f}, {uy:.2f})".format(
                    track_id=snapshot.track_id,
                    x=snapshot.position[0],
                    y=snapshot.position[1],
                    velocity=velocity_text,
                    ux=ux,
                    uy=uy,
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


def _iter_updates(stream: Iterable[str]) -> Iterable[TrackState]:
    for line in stream:
        line = line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if isinstance(payload, list):
            for item in payload:
                yield _parse_track_state(item)
        else:
            yield _parse_track_state(payload)


def render_from_stream(
    updates: Iterable[TrackState],
    space_config: SpaceConfig,
    refresh_every: int = 1,
) -> None:
    display = LiveTrackerDisplay(space_config=space_config)
    count = 0
    for update in updates:
        display.ingest(update)
        count += 1
        if count % max(refresh_every, 1) == 0:
            _print_frame(display.render())


def _print_frame(content: str) -> None:
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.write(content)
    sys.stdout.write("\n")
    sys.stdout.flush()


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
