from __future__ import annotations

from types import SimpleNamespace

from sandevistan.ingestion.ble import parse_ble_measurements
from sandevistan.ingestion.ble_scanner import BleakScannerAdapter, BleakScannerConfig


def test_ble_scanner_offline_payload_parses() -> None:
    config = BleakScannerConfig(
        adapter_name="offline-adapter",
        offline=True,
        offline_payloads=[
            {
                "timestamp": 1720000000.0,
                "rssi": -45,
                "device_id": "AA:BB:CC:DD:EE:FF",
                "manufacturer_data": {"company_id": 1234},
            }
        ],
    )
    adapter = BleakScannerAdapter(config)

    raw_payloads = adapter.scan()
    measurements = parse_ble_measurements(raw_payloads)

    assert len(measurements) == 1
    measurement = measurements[0]
    assert measurement.timestamp == 1720000000.0
    assert measurement.rssi == -45.0
    assert measurement.device_id == "AA:BB:CC:DD:EE:FF"
    assert measurement.hashed_identifier is not None
    assert measurement.manufacturer_data == {"company_id": 1234}


def test_ble_scanner_offline_payload_requires_identifier() -> None:
    config = BleakScannerConfig(
        adapter_name="offline-adapter",
        offline=True,
        offline_payloads=[{"timestamp": 1.0, "rssi": -80}],
    )
    adapter = BleakScannerAdapter(config)

    try:
        adapter.scan()
    except Exception as exc:
        assert "device_id" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("Expected adapter to reject missing device identifier")


def test_ble_scanner_offline_payload_accepts_hashed_identifier_only() -> None:
    config = BleakScannerConfig(
        adapter_name="offline-adapter",
        offline=True,
        offline_payloads=[
            {
                "timestamp": 1720000100.0,
                "rssi": -52,
                "hashed_identifier": "hash-only-device",
                "manufacturer_data": b"\x01\x02",
            }
        ],
        include_hashed_identifier=False,
    )
    adapter = BleakScannerAdapter(config)

    raw_payloads = adapter.scan()
    measurements = parse_ble_measurements(raw_payloads)

    assert len(measurements) == 1
    measurement = measurements[0]
    assert measurement.device_id is None
    assert measurement.hashed_identifier == "hash-only-device"
    assert measurement.rssi == -52.0
    assert measurement.manufacturer_data == {"raw_hex": "0102"}


def test_ble_scanner_discovery_raw_payload_normalizes() -> None:
    config = BleakScannerConfig(adapter_name="bleak-adapter")
    adapter = BleakScannerAdapter(config)
    device = SimpleNamespace(address="AA:BB:CC:DD:EE:FF", rssi=-60, metadata={})
    advertisement = SimpleNamespace(
        rssi=-60,
        manufacturer_data={0x004C: b"\x02\x15"},
        service_data={"180f": b"\x64"},
    )

    raw_payloads = adapter._normalize_discoveries([(device, advertisement)])
    measurements = parse_ble_measurements(raw_payloads)

    assert len(measurements) == 1
    assert measurements[0].manufacturer_data == {
        "raw_hex": "05ff4c00021504160f1864"
    }
