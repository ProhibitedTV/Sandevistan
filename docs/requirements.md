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
- Spatial configuration: a coordinate system, floor plan dimensions, and sensor placements,
  including mmWave sensor positions/orientations for converting range/angle readings into
  world-space coordinates.

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
- Wearable operation must tolerate intermittent connectivity and power cycling; the system
  should resume local capture and fusion without relying on cloud services.
- Offline mode must preserve essential tracking behavior (local fusion + output buffering) and
  degrade gracefully when upstream network links or routers are unavailable.
- Wi-Fi-based motion detection is opportunistic and highly environment-dependent; expect degraded
  performance in crowded RF environments, when access point geometry is poor, or when CSI/RSSI
  sampling rates are low.
- Wi-Fi motion cues generally cannot distinguish multiple people in close proximity without
  additional sensors and should not be treated as a reliable identity signal.
- mmWave sensors may provide coarse range/angle estimates and can be impacted by multipath
  reflections or occlusions; treat mmWave signals as corroborating evidence rather than a
  precise localization source. Placement calibration is required to map mmWave range/angle
  readings into the shared coordinate system.
- BLE scans are passive and only observe broadcast advertisements; they do not establish
  connections, and measurements are limited to nearby devices advertising on channels
  37–39. RSSI values can fluctuate due to interference, body absorption, and antenna
  orientation, so BLE data should be treated as a coarse proximity signal.
- BLE emitter location is only approximate; room-scale proximity is typical, and precise
  positioning generally requires dense receiver placement, frequent advertisements, and
  favorable RF conditions.

## Wearable operation requirements
- The default deployment target is a wearable or backpack-mounted Raspberry Pi class device.
- The device must support local ingestion and fusion even when no external router is present.
- On-device storage must bound buffering (e.g., fixed-size ring buffer) to avoid exhausting
  flash storage during long offline sessions.
- Power constraints require configurable sampling rates and the ability to disable sensors
  dynamically when battery is low or the device is stationary.

## Sensor fusion constraints
- Synchronization windows must accommodate clock drift between local sensors and any optional
  upstream router timestamps; drift correction should be bounded and observable.
- Fusion should prefer co-located sensors (Pi-local) when external links introduce latency or
  dropouts.
- When only one modality is available (e.g., Wi-Fi without vision), fusion must emit lower
  confidence tracks and annotate missing modalities in provenance metadata.

## Linux BLE scanner capabilities
BLE scanning on Linux typically requires raw socket access provided by BlueZ. Ensure the
scanner process has sufficient permissions (or run as root) to access the Bluetooth
adapter. The recommended capabilities for a non-root process are:

- `cap_net_raw`: required to open raw Bluetooth sockets.
- `cap_net_admin`: required by some adapters to configure scan parameters.

To grant these to a Python virtualenv without running as root, set file capabilities on
the interpreter or the entrypoint binary (adjust the path to your venv):

```bash
sudo setcap 'cap_net_raw,cap_net_admin+eip' /path/to/venv/bin/python
```

Alternatively, add the service user to the `bluetooth` group if your distro gates access
via group permissions, but capabilities are still recommended for consistent access across
BlueZ versions.

## Local Wi-Fi capture requirements
Local Wi-Fi capture relies on Linux `nl80211` tooling and compatible NIC/driver support. The
default implementation uses `iw dev <iface> scan` to read RSSI values; ensure the interface is
enabled and has permission to perform active scans.

For CSI capture you **must** use a CSI-capable NIC/driver stack (for example, Intel 5300 CSI
Tool, Atheros CSI, or Nexmon/BCM4358-derived firmware). The CSI capture command should emit
numerical CSI values (for example, JSON with a `csi` array) and, optionally, timestamps. If the
driver/firmware does not expose CSI, only RSSI will be available.

Operational constraints:
- Requires Linux with `iw` and `nl80211` support.
- Interfaces may need monitor mode or elevated permissions (`cap_net_admin`) depending on the
  adapter/driver; NetworkManager or wpa_supplicant may need to release the interface for scans.
- CSI collection often requires patched firmware/drivers and is vendor-specific; verify support
  before deployment. Commonly supported chipsets include Intel 5300 (CSI Tool), Atheros 9k CSI,
  and Broadcom BCM43xx/Nexmon-derived stacks.
- Many commodity NICs (especially newer 802.11ax adapters) do **not** expose CSI or disable
  per-subcarrier data in their firmware; plan for hardware validation early.

## Data retention defaults
- Retention is **disabled by default** and must be explicitly enabled.
- When enabled, configure separate TTLs for measurements and audit logs.
- Scheduled cleanup runs on a configurable interval; defaults to 60 seconds.

## CLI configuration (BLE sources)
When using the fusion CLI, BLE scanners are configured under `ingestion.ble_sources` in the JSON
config file. Each BLE source entry includes a `type`, `adapter_name`, and
`scan_interval_seconds` (poll rate). Use `type: "static"` to emit from prerecorded payloads, or
`type: "bleak"` to scan using the Bleak adapter and an `adapter_settings` block:

Permissions and runtime notes:
- Linux BLE scanning typically relies on BlueZ and requires access to the Bluetooth adapter.
  Run with `cap_net_admin`/`cap_net_raw` or ensure the service account is in the `bluetooth`
  group, and expose `/var/run/dbus` plus the relevant `/dev` nodes when containerized.

```json
{
  "ingestion": {
    "ble_sources": [
      {
        "type": "static",
        "adapter_name": "ble-scanner-01",
        "scan_interval_seconds": 1.0,
        "measurements": [
          {"timestamp": 1700000000.0, "rssi": -42, "device_id": "demo-tag-01"}
        ]
      },
      {
        "type": "bleak",
        "adapter_name": "ble-scanner-01",
        "scan_interval_seconds": 2.0,
        "adapter_settings": {
          "scan_timeout_seconds": 1.5,
          "include_hashed_identifier": true,
          "offline": false,
          "offline_payloads": []
        }
      }
    ]
  }
}
```

## Serial mmWave data formats
The serial mmWave adapter accepts line-delimited payloads from UART/USB sensors. Each line can be
one of the following formats:

- **JSON object** (one per line):
  ```json
  {"timestamp_ms": 1700000000000, "sensor_id": "mmwave-1", "event_type": "presence", "confidence": 0.82}
  ```
- **CSV fields** (timestamp_ms, sensor_id, event_type, confidence, range_meters?, angle_degrees?):
  ```text
  1700000000000,mmwave-1,motion,45,3.1,90
  ```
- **Key=value pairs** (comma-separated):
  ```text
  sensor_id=mmwave-1,event_type=presence,confidence=1,timestamp=1700000000
  ```

Notes:
- `confidence` values greater than 1 are treated as percentages (e.g., `45` becomes `0.45`).
- `timestamp` is interpreted as seconds; `timestamp_ms` is interpreted as milliseconds.
- `angle_degrees` is converted to radians during ingestion.

## CLI configuration (mmWave serial sources)
To ingest mmWave data over a serial port, configure `ingestion.mmwave_sources` with
`type: "serial"`:

```json
{
  "ingestion": {
    "mmwave_sources": [
      {
        "type": "serial",
        "port": "/dev/ttyUSB0",
        "baudrate": 115200,
        "timeout_seconds": 0.5,
        "max_lines": 50,
        "default_sensor_id": "mmwave-1",
        "source_name": "serial_mmwave",
        "source_metadata": {"vendor": "ti"},
        "default_metadata": {"room": "lab"}
      }
    ]
  }
}
```
