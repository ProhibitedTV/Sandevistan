#!/usr/bin/env python3
"""Emit demo vision detections for the process vision exporter adapter."""

from __future__ import annotations

import json
import math
import time


def _build_detections() -> list[dict[str, object]]:
    now = time.time()
    phase = now % 6.0
    x_center = 0.25 + 0.1 * math.sin(phase)
    y_center = 0.35 + 0.1 * math.cos(phase)
    width = 0.18
    height = 0.28
    bbox_main = [
        x_center - width / 2.0,
        y_center - height / 2.0,
        x_center + width / 2.0,
        y_center + height / 2.0,
    ]

    return [
        {
            "camera_id": "demo-cam-1",
            "timestamp": now,
            "confidence": 0.92,
            "bbox": bbox_main,
            "metadata": {"label": "person"},
        },
        {
            "camera_id": "demo-cam-1",
            "timestamp": now,
            "confidence": 0.81,
            "bbox": [0.05, 0.08, 0.16, 0.22],
            "metadata": {"label": "bag"},
        },
    ]


def main() -> None:
    print(json.dumps(_build_detections()))


if __name__ == "__main__":
    main()
