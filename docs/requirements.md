# Requirements

## Scope
This project targets **indoor localization and tracking** of consenting participants by fusing:
- Wi-Fi signal metrics (e.g., RSSI/CSI) from known access points.
- Camera-based detections from fixed-position cameras.
- mmWave presence/motion events from short-range sensors.
- BLE advertisement beacons from nearby devices when available.

## Inputs
- Wi-Fi measurements: timestamped signal strength / channel state information.
- Vision detections: timestamped bounding boxes and optional pose/keypoint data.
- mmWave events: timestamped presence/motion indicators with optional range/angle metadata.
- BLE advertisements: timestamped RSSI measurements with optional device identifiers and
  manufacturer metadata.
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
- Wi-Fi-based motion detection is opportunistic and highly environment-dependent; expect degraded
  performance in crowded RF environments, when access point geometry is poor, or when CSI/RSSI
  sampling rates are low.
- Wi-Fi motion cues generally cannot distinguish multiple people in close proximity without
  additional sensors and should not be treated as a reliable identity signal.
- mmWave sensors may provide coarse range/angle estimates and can be impacted by multipath
  reflections or occlusions; treat mmWave signals as corroborating evidence rather than a
  precise localization source.
- BLE scans are passive and only observe broadcast advertisements; they do not establish
  connections, and measurements are limited to nearby devices advertising on channels
  37–39. RSSI values can fluctuate due to interference, body absorption, and antenna
  orientation, so BLE data should be treated as a coarse proximity signal.
- BLE emitter location is only approximate; room-scale proximity is typical, and precise
  positioning generally requires dense receiver placement, frequent advertisements, and
  favorable RF conditions.

## Data retention defaults
- Retention is **disabled by default** and must be explicitly enabled.
- When enabled, configure separate TTLs for measurements and audit logs.
- Scheduled cleanup runs on a configurable interval; defaults to 60 seconds.

## CLI configuration (BLE sources)
When using the fusion CLI, BLE scanners are configured under `ingestion.ble_sources` in the JSON
config file. The CLI accepts BLE source entries with a `type`, `adapter_name`, and
`scan_interval_seconds` to control how often a scanner should emit advertisements:

```json
{
  "ingestion": {
    "ble_sources": [
      {
        "type": "static",
        "adapter_name": "ble-scanner-01",
        "scan_interval_seconds": 1.0
      }
    ]
  }
}
```
