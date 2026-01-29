# Requirements

## Scope
This project targets **indoor localization and tracking** of consenting participants by fusing:
- Wi-Fi signal metrics (e.g., RSSI/CSI) from known access points.
- Camera-based detections from fixed-position cameras.
- mmWave presence/motion events from short-range sensors.

## Inputs
- Wi-Fi measurements: timestamped signal strength / channel state information.
- Vision detections: timestamped bounding boxes and optional pose/keypoint data.
- mmWave events: timestamped presence/motion indicators with optional range/angle metadata.
- Spatial configuration: a coordinate system, floor plan dimensions, and sensor placements.

## Outputs
- Track estimates for detected participants in a shared coordinate system.
- Confidence metrics for each track (e.g., covariance / uncertainty bounds).
- An auditable log of sensor provenance for each track update.

## Performance targets (initial)
- Latency: <= 250ms per frame for fusion updates.
- Localization accuracy: 1–2 meters median error in controlled environments.
- Reliability: stable tracking for 90% of frames in a short test run.

## Constraints
- All processing must be on-device or within a trusted local network.
- Data retention must be minimized and configurable.
- Clear opt-in consent is required for all tracked participants.
- mmWave sensors may provide coarse range/angle estimates and can be impacted by multipath
  reflections or occlusions; treat mmWave signals as corroborating evidence rather than a
  precise localization source.

## Data retention defaults
- Retention is **disabled by default** and must be explicitly enabled.
- When enabled, configure separate TTLs for measurements and audit logs.
- Scheduled cleanup runs on a configurable interval; defaults to 60 seconds.
