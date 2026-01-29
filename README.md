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

### Live tracker display
The repository includes a minimal CLI renderer that consumes tracker output updates and displays
a live list + floor-plan placeholder. See `docs/display.md` for launch and piping instructions.

## Ethics and legal compliance
Please read and comply with `docs/ethics-policy.md` before any development or deployment.
