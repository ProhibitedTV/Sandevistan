import io
import math

from sandevistan.ingestion import SerialMmWaveAdapter, SerialMmWaveConfig


def test_serial_mmwave_adapter_parses_lines() -> None:
    stream = io.StringIO(
        "\n".join(
            [
                '{"timestamp_ms": 1700000000000, "sensor_id": "mm1",'
                ' "event_type": "presence", "confidence": 0.9, "range_meters": 2.5}',
                "1700000005000,mm2,motion,45,3.1,90",
                "sensor_id=mm3,event_type=presence,confidence=1,timestamp=1700000006",
                "",
            ]
        )
    )
    adapter = SerialMmWaveAdapter(
        SerialMmWaveConfig(
            port="/dev/ttyUSB0",
            source_metadata={"vendor": "acme"},
            default_metadata={"room": "lab"},
        ),
        stream=stream,
    )

    measurements = adapter.fetch()

    assert [measurement.sensor_id for measurement in measurements] == ["mm1", "mm2", "mm3"]
    assert math.isclose(measurements[0].timestamp, 1700000000.0, rel_tol=0.0)
    assert math.isclose(measurements[1].timestamp, 1700000005.0, rel_tol=0.0)
    assert math.isclose(measurements[2].timestamp, 1700000006.0, rel_tol=0.0)
    assert math.isclose(measurements[1].confidence, 0.45, rel_tol=1e-6)
    assert measurements[1].event_type == "motion"
    assert math.isclose(measurements[1].range_meters or 0.0, 3.1, rel_tol=1e-6)
    assert math.isclose(measurements[1].angle_radians or 0.0, math.pi / 2, rel_tol=1e-6)
    assert measurements[0].metadata == {
        "source": "serial_mmwave",
        "port": "/dev/ttyUSB0",
        "vendor": "acme",
        "room": "lab",
    }
