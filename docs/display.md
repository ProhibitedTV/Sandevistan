# Live Tracker Display

The tracker display is a lightweight CLI renderer that consumes tracker output updates
(`{timestamp, track_id, position, velocity?, uncertainty}`) as newline-delimited JSON and
renders a live list + floor-plan placeholder.

## UI overview

Each refresh includes the following sections:

- **Alert tiers**: A quick count of active tracks in red, yellow, and blue tiers (orange
  counts toward red). This is derived from each track update’s `alert_tier` field.
- **Active tracks**: Track position, velocity, uncertainty, and the current alert tier.
- **Sensor health**: Status lines for each sensor (for example, mmWave or cameras),
  including last-seen ages when provided.
- **Active emitters**: A list of detected emitters with RSSI values and a simple trend
  arrow (↑/↓/→/·) based on the most recent change.
- **Floor-plan**: A placeholder grid with current track positions.

## Usage notes

- Lines can be **track-only** payloads (as before) or richer objects that include
  `tracks`, `sensor_health`, and/or `emitters` fields.
- The display is resilient to missing sensor data; omit `sensor_health` or mark a sensor
  as `offline` to represent unavailable sources.
- RSSI trends are computed per emitter from the previous value received in the stream.

## Connect it to the pipeline

The display expects one JSON object per line. Each line can be either a single
track update or a list of track updates. The object format should match the
tracker output schema in `docs/architecture.md`.

Example producer piped into the display (prints JSON lines from the fusion pipeline):

```bash
python - <<'PY'
import json
import time

from sandevistan import (
    AccessPointCalibration,
    Detection,
    FusionInput,
    FusionPipeline,
    SensorConfig,
    SpaceConfig,
)

sensor_config = SensorConfig(
    wifi_access_points={
        "ap-1": AccessPointCalibration(position=(0.0, 0.0), position_uncertainty_meters=0.5)
    },
    cameras={},
)
space_config = SpaceConfig(width_meters=10.0, height_meters=6.0)
pipeline = FusionPipeline(sensor_config=sensor_config, space_config=space_config)

for step in range(5):
    now = time.time()
    measurement = FusionInput(
        wifi=[],
        vision=[
            Detection(
                timestamp=now,
                camera_id="cam-1",
                bbox=(0.1 + step * 0.1, 0.2, 0.2 + step * 0.1, 0.4),
                confidence=0.9,
            )
        ],
    )
    tracks = pipeline.fuse(measurement)
    print(json.dumps([track.__dict__ for track in tracks]))
    time.sleep(0.5)
PY
| python -m sandevistan.display --space-width 10 --space-height 6
```

### Example with sensor health and emitters

```bash
python - <<'PY'
import json
import time

now = time.time()
payload = {
    "tracks": [
        {
            "track_id": "track-1",
            "timestamp": now,
            "position": [2.0, 1.5],
            "velocity": [0.1, 0.0],
            "uncertainty": [0.4, 0.3],
            "alert_tier": "yellow",
        }
    ],
    "sensor_health": {
        "mmwave-1": {"status": "offline", "last_seen": now - 12.3},
        "cam-1": {"status": "online", "last_seen": now - 0.2},
    },
    "emitters": [
        {"emitter_id": "ble:tag-7", "rssi": -54.2, "last_seen": now - 0.4},
        {"emitter_id": "ble:tag-9", "rssi": -61.8, "last_seen": now - 1.1},
    ],
}
print(json.dumps(payload))
PY
| python -m sandevistan.display --space-width 10 --space-height 6
```
