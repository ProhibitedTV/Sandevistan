from __future__ import annotations

import math

import pytest

from sandevistan.config import AccessPointCalibration, SensorConfig
from sandevistan.ingestion.ble import parse_ble_measurements
from sandevistan.ingestion.mmwave import MmWaveIngestionError, parse_mmwave_measurements
from sandevistan.ingestion.wifi import WiFiIngestionError, parse_wifi_measurements


def _sensor_config() -> SensorConfig:
    return SensorConfig(
        wifi_access_points={
            "ap-1": AccessPointCalibration(
                position=(1.0, 2.0), position_uncertainty_meters=0.4
            )
        },
        cameras={},
        mmwave_sensors={},
    )


def test_parse_ble_measurements_from_bleak_payload() -> None:
    raw_payloads = [
        {
            "timestamp": 1720000000.0,
            "rssi": -58,
            "device_id": "AA:BB:CC:DD:EE:FF",
            "hashed_identifier": "ble-hash-001",
            "channel": 37,
            "manufacturer_data": b"\x02\x01\x06\x03\x03\xaa\xfe",
        }
    ]

    measurements = parse_ble_measurements(raw_payloads)

    assert len(measurements) == 1
    measurement = measurements[0]
    assert measurement.device_id == "AA:BB:CC:DD:EE:FF"
    assert measurement.hashed_identifier == "ble-hash-001"
    assert measurement.rssi == -58.0
    assert measurement.channel == 37
    assert measurement.manufacturer_data == {"raw_hex": "0201060303aafe"}


def test_parse_mmwave_measurements_from_serial_payload() -> None:
    raw_payloads = [
        {
            "timestamp": 1700000000.25,
            "sensor_id": "mmwave-1",
            "event_type": "presence",
            "confidence": 0.92,
            "range_meters": 2.4,
            "angle_degrees": 45.0,
            "metadata": {"source": "serial_mmwave", "port": "/dev/ttyUSB0"},
        }
    ]

    measurements = parse_mmwave_measurements(raw_payloads)

    assert len(measurements) == 1
    measurement = measurements[0]
    assert measurement.sensor_id == "mmwave-1"
    assert measurement.event_type == "presence"
    assert measurement.confidence == 0.92
    assert measurement.range_meters == 2.4
    assert math.isclose(measurement.angle_radians or 0.0, math.pi / 4, rel_tol=1e-6)
    assert measurement.metadata == {"source": "serial_mmwave", "port": "/dev/ttyUSB0"}


def test_parse_wifi_measurements_from_http_payload() -> None:
    raw_payloads = [
        {
            "timestamp": 1700000001.5,
            "access_point_id": "ap-1",
            "rssi": -47,
            "csi": [0.12, 0.34, 0.56],
            "metadata": {"source": "http_exporter", "endpoint": "http://ap"},
        }
    ]

    measurements = parse_wifi_measurements(raw_payloads, _sensor_config())

    assert len(measurements) == 1
    measurement = measurements[0]
    assert measurement.access_point_id == "ap-1"
    assert measurement.rssi == -47.0
    assert measurement.csi == [0.12, 0.34, 0.56]
    assert measurement.metadata == {"source": "http_exporter", "endpoint": "http://ap"}


def test_parse_mmwave_measurements_rejects_invalid_confidence() -> None:
    raw_payloads = [
        {
            "timestamp": 1700000000.5,
            "sensor_id": "mmwave-2",
            "event_type": "motion",
            "confidence": "high",
        }
    ]

    with pytest.raises(MmWaveIngestionError, match="Invalid or missing 'confidence'"):
        parse_mmwave_measurements(raw_payloads)


def test_parse_wifi_measurements_rejects_bad_metadata() -> None:
    raw_payloads = [
        {
            "timestamp": 1700000002.0,
            "access_point_id": "ap-1",
            "rssi": -52,
            "metadata": "not-a-mapping",
        }
    ]

    with pytest.raises(WiFiIngestionError, match="metadata must be a mapping"):
        parse_wifi_measurements(raw_payloads, _sensor_config())
