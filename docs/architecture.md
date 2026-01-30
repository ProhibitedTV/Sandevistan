# Architecture Overview

## Modules
1. **Wi-Fi Ingestion**
   - Collects RSSI/CSI data from known access points.
   - Normalizes and timestamps measurements.
   - Supports HTTP JSON exporters that emit the Wi-Fi measurement schema.
2. **Vision Ingestion**
   - Accepts camera detections (boxes, keypoints) with timestamps.
   - Optionally performs camera-to-world transforms.
   - When a camera homography is configured, the fusion pipeline projects the
     detection’s bottom-center image point (bbox center X, bbox max Y) into world
     space using the 3×3 homography matrix.
   - When homography is missing but camera height + tilt are configured, the
     pipeline uses a ground-plane projection (pinhole intrinsics + pitch/yaw)
     to intersect the detection ray with the floor.
3. **mmWave Ingestion**
   - Accepts presence/motion events from mmWave sensors.
   - Normalizes timestamp, confidence, and optional range/angle metadata.
   - Uses configured sensor placement metadata (position/orientation) to project range/angle
     events into world coordinates for fusion.
4. **Synchronization Layer**
   - Aligns multi-sensor measurements to a shared time window.
   - Buffers and interpolates as needed.
5. **Fusion Engine**
   - Combines Wi-Fi, vision, and mmWave measurements into a shared state estimate.
   - Computes uncertainty and confidence bounds.
6. **Tracker**
   - Maintains identity over time (track association).
   - Emits track updates to downstream consumers.

## Data flow (wearable-centric MVP)
```
Pi-local sensors                         Optional router / LAN
-----------------                        ----------------------
Wi-Fi RSSI/CSI  -> Wi-Fi Ingestion  ->          |
Camera frames   -> Vision Ingestion ->          |
mmWave events   -> mmWave Ingestion ->          |
BLE adverts     -> BLE Ingestion    ->          |
                                      -> Sync -> Fusion -> Tracker -> Outputs
                                               |
                                          (buffered export)
```

## Interfaces
- **Wi-Fi measurement schema**: `{timestamp, ap_id, rssi, csi?, metadata}`
- **Vision detection schema**: `{timestamp, camera_id, bbox, confidence, keypoints?}`
- **mmWave event schema**: `{timestamp, sensor_id, confidence, event_type, range_meters?, angle_radians?}`
- **Fusion output**: `{timestamp, track_id, position, velocity?, uncertainty, alert_tier}`
- **Audit log schema**
  - **Sensor provenance log**: `{track_id, timestamp, sources, captured_at}`
  - **Track update log**: `{track_id, timestamp, sources, captured_at}`
  - **Consent record**: `{participant_id?, session_id?, status, timestamp}`

## Alert tiers
The fusion pipeline assigns an `alert_tier` to each track update using recent signal context:
- **red**: mmWave presence plus a corroborating vision detection.
- **orange**: Wi-Fi anomaly flagged (optionally alongside mmWave presence).
- **yellow**: mmWave presence without vision confirmation.
- **blue**: BLE emitter detected without higher-priority triggers.
- **none**: No alert triggers detected.

## MVP assumptions
- Fixed sensor positions with known calibration.
- Small, controlled test space (single room or corridor).
- Limited number of participants with consent.

## Camera calibration notes
- Camera calibration entries may include an optional `homography` matrix: a
  3×3 array that maps image coordinates to world coordinates on the ground
  plane. For normalized bounding boxes, configure the homography to operate on
  normalized image coordinates (0–1). If the homography is missing or invalid,
  the system attempts a ground-plane projection using `camera_height_meters`
  (camera height above the floor), `tilt_radians` (pitch downward from the
  horizontal), intrinsics, and the camera extrinsics (translation + yaw). The
  intrinsics must use the same units as the detection bounding boxes
  (normalized 0–1 or pixel coordinates). If those parameters are missing, the
  system falls back to the normalized-bbox mapping into the `space` dimensions.
