# Sandevistan (Research Prototype)

This repository contains an early-stage prototype framework inspired by the *Sandevistan* concept from Cyberpunk 2077. The intent is to explore **multi-sensor fusion** for indoor localization using Wi-Fi signal data and camera-based detections to estimate human movement within a space. This is **not** a consumer-ready application and must be developed with strict privacy, legal, and ethical constraints.

## Project goals
- Build a modular data pipeline for signal ingestion, synchronization, and fusion.
- Provide a clear interface for integrating Wi-Fi and vision sources.
- Support track estimation with transparent confidence metrics.

## Non-goals
- This project does **not** enable clandestine or non-consensual surveillance.
- This project does **not** provide “X-ray vision.” Results are probabilistic and bounded by sensor limitations.

## Repository layout
- `docs/requirements.md`: Product requirements and performance targets.
- `docs/architecture.md`: System architecture and data flow.
- `docs/ethics-policy.md`: Ethics and permissible use policy.
- `docs/display.md`: Live tracker display consumer instructions.
- `src/sandevistan/`: Prototype Python scaffolding for the pipeline.

## Quick start (prototype only)
This repository is a scaffold. The modules include interfaces and placeholders for actual sensor integrations.

### Fusion CLI (real environment)
The `sandevistan-cli` entrypoint runs ingestion adapters, synchronization, and fusion, and emits
track updates as NDJSON (one JSON object per track update).

1. Create a JSON config file:
   ```json
   {
     "space": {
       "width_meters": 10.0,
       "height_meters": 6.0,
       "coordinate_origin": [0.0, 0.0]
     },
     "sensors": {
       "wifi_access_points": {
         "ap-lobby-01": {
           "position": [2.5, 1.0],
           "position_uncertainty_meters": 0.4
         }
       },
       "cameras": {
         "cam-01": {
           "intrinsics": {
             "focal_length": [1200.0, 1200.0],
             "principal_point": [960.0, 540.0],
             "skew": 0.0
           },
           "extrinsics": {
             "translation": [1.2, 4.5],
             "rotation_radians": 0.0
           }
         }
       }
     },
     "ingestion": {
       "wifi_sources": [
         {
           "type": "http",
           "endpoint_url": "http://10.0.0.5:8080/wifi/telemetry",
           "access_point_id": "ap-lobby-01"
         }
       ],
       "vision_sources": [
         {
           "type": "http",
           "endpoint_url": "http://10.0.0.6:8081/vision/detections",
           "default_camera_id": "cam-01"
         }
       ]
     },
     "synchronization": {
       "window_seconds": 0.25,
       "max_latency_seconds": 0.25,
       "strategy": "nearest"
     },
     "retention": {
       "enabled": false
     }
   }
   ```

2. Run the CLI:
   ```bash
   sandevistan-cli --config path/to/config.json
   ```

3. Consume NDJSON output (for example, pipe to the live display):
   ```bash
   sandevistan-cli --config path/to/config.json | python -m sandevistan.display
   ```

### Live tracker display
The repository includes a minimal CLI renderer that consumes tracker output updates and displays
a live list + floor-plan placeholder. See `docs/display.md` for launch and piping instructions.

## Ethics and legal compliance
Please read and comply with `docs/ethics-policy.md` before any development or deployment.
