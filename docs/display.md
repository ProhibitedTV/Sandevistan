# Live Tracker Display

The tracker display is a lightweight CLI renderer that consumes tracker output updates
(`{timestamp, track_id, position, velocity?, uncertainty}`) as newline-delimited JSON and
renders a live list + floor-plan placeholder.

## Connect it to the pipeline

The display expects one JSON object per line. Each line can be either a single
track update or a list of track updates. The object format should match the
tracker output schema in `docs/architecture.md`.

Example producer piped into the display (prints JSON lines from the fusion pipeline):

```bash
python - <<'PY'
import json
import time

from sandevistan import Detection, FusionInput, FusionPipeline, SensorConfig, SpaceConfig

sensor_config = SensorConfig(wifi_access_points={"ap-1": (0.0, 0.0)}, cameras={})
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
