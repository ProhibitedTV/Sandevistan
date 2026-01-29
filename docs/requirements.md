# Requirements

## Scope
This project targets **indoor localization and tracking** of consenting participants by fusing:
- Wi-Fi signal metrics (e.g., RSSI/CSI) from known access points.
- Camera-based detections from fixed-position cameras.

## Inputs
- Wi-Fi measurements: timestamped signal strength / channel state information.
- Vision detections: timestamped bounding boxes and optional pose/keypoint data.
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
