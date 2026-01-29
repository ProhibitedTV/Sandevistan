# Deployment Guide

## Runtime requirements
- Python 3.10+ (prototype runtime).
- Access to Wi-Fi telemetry sources (RSSI/CSI exporters) and fixed camera feeds.
- Local storage for short-lived logs and metrics (in-memory by default; optional TTL-based retention).
- Time synchronization across sensor hosts (NTP or equivalent) to keep timestamps aligned.

## Environment variables
This prototype does not hardcode environment variables, but deployments typically use the following to
standardize runtime behavior. Treat these as **recommended conventions** to keep environments
consistent:

- `SANDEVISTAN_LOG_LEVEL`: `DEBUG`, `INFO`, `WARNING`, `ERROR`.
- `SANDEVISTAN_RETENTION_ENABLED`: `true` or `false` to gate in-memory retention.
- `SANDEVISTAN_MEASUREMENT_TTL_SECONDS`: float seconds for measurement TTL.
- `SANDEVISTAN_LOG_TTL_SECONDS`: float seconds for audit log TTL.
- `SANDEVISTAN_CLEANUP_INTERVAL_SECONDS`: float seconds between retention cleanup sweeps.
- `SANDEVISTAN_SPACE_WIDTH_METERS`: float width of the tracked space.
- `SANDEVISTAN_SPACE_HEIGHT_METERS`: float height of the tracked space.
- `SANDEVISTAN_COORD_ORIGIN`: `x,y` tuple for the coordinate origin (meters).

If you already manage configuration via files or a secret store, map those settings into the
corresponding runtime configuration objects before starting the pipeline.

## Local network constraints
- **On-prem only**: All processing must stay within a trusted local network. Avoid internet egress for
  raw sensor data.
- **Low latency**: Keep Wi-Fi and camera ingestion on the same LAN as the fusion process to minimize
  jitter and timestamp skew.
- **Isolated VLANs**: Prefer segregated VLANs for sensor traffic to reduce exposure and simplify
  access control.
- **Clock discipline**: Ensure consistent NTP sources across sensor hosts and the fusion runtime.
- **Bandwidth planning**: Camera streams can saturate links quickly. Use hardware-accelerated
  encoding and downsample as needed to maintain <250ms fusion latency.

## Deployment checklist
1. Confirm consent and ethics policy alignment before enabling any capture.
2. Validate that all sensors are inside the trusted local network boundary.
3. Establish a shared coordinate system and document sensor placements.
4. Configure retention defaults (disabled unless explicitly enabled).
5. Run a short calibration pass and compare track output against ground truth markers.
