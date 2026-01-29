# Architecture Overview

## Modules
1. **Wi-Fi Ingestion**
   - Collects RSSI/CSI data from known access points.
   - Normalizes and timestamps measurements.
2. **Vision Ingestion**
   - Accepts camera detections (boxes, keypoints) with timestamps.
   - Optionally performs camera-to-world transforms.
3. **Synchronization Layer**
   - Aligns multi-sensor measurements to a shared time window.
   - Buffers and interpolates as needed.
4. **Fusion Engine**
   - Combines Wi-Fi and vision measurements into a shared state estimate.
   - Computes uncertainty and confidence bounds.
5. **Tracker**
   - Maintains identity over time (track association).
   - Emits track updates to downstream consumers.

## Data flow (MVP)
```
Wi-Fi measurements   ->  Wi-Fi Ingestion  ->
                                             -> Sync -> Fusion -> Tracker -> Outputs
Camera detections    -> Vision Ingestion ->
```

## Interfaces
- **Wi-Fi measurement schema**: `{timestamp, ap_id, rssi, csi?, metadata}`
- **Vision detection schema**: `{timestamp, camera_id, bbox, confidence, keypoints?}`
- **Fusion output**: `{timestamp, track_id, position, velocity?, uncertainty}`
- **Audit log schema**
  - **Sensor provenance log**: `{track_id, timestamp, sources, captured_at}`
  - **Track update log**: `{track_id, timestamp, sources, captured_at}`
  - **Consent record**: `{participant_id?, session_id?, status, timestamp}`

## MVP assumptions
- Fixed sensor positions with known calibration.
- Small, controlled test space (single room or corridor).
- Limited number of participants with consent.
