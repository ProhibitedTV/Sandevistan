# Configuration Guide

## Overview
Sandevistan’s prototype configuration defines the **space**, **sensors**, and **retention policy**.
Configuration objects live in `src/sandevistan/config.py` and should be instantiated by the hosting
application.

## Space configuration
Use `SpaceConfig` to describe the tracked area:

- `width_meters`: Physical width of the space (X-axis).
- `height_meters`: Physical height of the space (Y-axis).
- `coordinate_origin`: `(x, y)` tuple that defines where `(0, 0)` lives within the space.

### Coordinate system conventions
- Coordinates are **meters** in a 2D plane.
- The **X-axis** increases to the right when viewing the floor plan.
- The **Y-axis** increases upward (north) when viewing the floor plan.
- The origin should align to a fixed, physically marked point (e.g., southwest corner of the room).

Document the coordinate system visually (annotated floor plan) so all teams use the same reference.

## Sensor configuration
Use `SensorConfig` to map sensors to fixed coordinates:

- `wifi_access_points`: `{access_point_id: (x, y)}` mapping in meters.
- `cameras`: `{camera_id: (x, y)}` mapping in meters.

### Sensor calibration steps
1. **Survey the space**: mark permanent fiducials (tape crosses or wall markers) that can be measured
   repeatedly.
2. **Measure placements**: record each access point and camera position relative to the coordinate
   origin. Use a laser measure for accuracy.
3. **Align camera frames**: record camera mounting height, tilt, and heading to support later
   projection from image coordinates into the shared 2D plane.
4. **Validate line-of-sight**: confirm camera coverage and Wi-Fi propagation lines are consistent
   with the floor plan (avoid moving metal structures during calibration).
5. **Recalibrate on change**: any camera move, access point relocation, or significant furniture
   change requires re-measurement.

### Coordinate system alignment notes
- All sensor coordinates must be in the **same** coordinate system defined by `SpaceConfig`.
- If you maintain 3D camera extrinsics, project down to the 2D plane using the floor height as the
  reference `z=0` plane.

## Wi-Fi ingestion adapters
Sandevistan ships with an HTTP exporter adapter that can pull RSSI/CSI telemetry from routers or
APs that expose a JSON endpoint. Register each AP in `SensorConfig` and then configure the adapter
with the endpoint URL and the matching access point ID.

### HTTP exporter example
```python
from sandevistan.config import SensorConfig
from sandevistan.ingestion import HTTPWiFiExporterAdapter, HTTPWiFiExporterConfig

sensor_config = SensorConfig(
    wifi_access_points={
        "ap-lobby-01": (2.5, 1.0),
        "ap-lab-02": (8.0, 3.5),
    },
    cameras={},
)

adapter = HTTPWiFiExporterAdapter(
    HTTPWiFiExporterConfig(
        endpoint_url="http://10.0.0.5:8080/wifi/telemetry",
        access_point_id="ap-lobby-01",
        timeout_seconds=2.0,
        default_metadata={"hardware": "OpenWRT exporter", "room": "lobby"},
    ),
    sensor_config,
)

wifi_measurements = adapter.fetch()
```

Expected exporter payload (list of JSON objects):
```json
[
  {
    "timestamp": 1702577012.431,
    "rssi": -42.1,
    "csi": [0.12, -0.08, 0.07],
    "metadata": {"channel": 36, "band": "5ghz"}
  }
]
```
Notes:
- `access_point_id` can be omitted when the adapter is configured with it.
- Use `timestamp_ms` if the exporter reports epoch milliseconds (the adapter converts to seconds).

## Retention configuration
Use `RetentionConfig` for in-memory retention policies:

- Retention is **disabled by default**; set `enabled=True` and provide TTL values to activate.
- `measurement_ttl_seconds` and `log_ttl_seconds` can be set independently.
- `cleanup_interval_seconds` controls how often in-memory cleanup runs (defaults to 60 seconds).

## Recommended configuration workflow
1. Define the coordinate system with a floor plan and known origin.
2. Populate `SpaceConfig` with measured dimensions.
3. Register all sensors with `SensorConfig` mappings.
4. Enable retention only when explicitly required and document the TTL settings.
