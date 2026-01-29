# Deployment Guide

## Runtime requirements
- Python 3.10+ (prototype runtime).
- Access to Wi-Fi telemetry sources (RSSI/CSI exporters) and fixed camera feeds.
- Local storage for short-lived logs and metrics (in-memory by default; optional TTL-based retention).
- Time synchronization across sensor hosts (NTP or equivalent) to keep timestamps aligned.

## Desktop demo (no hardware)
Use the sample config and demo scripts to exercise the pipeline on a laptop without any sensors.

1. Start the optional Wi-Fi HTTP stub (required only if the sample config keeps Wi-Fi enabled):

   ```bash
   python scripts/demo_wifi_exporter.py --port 8081
   ```

2. The vision demo is invoked automatically by the config via
   `scripts/demo_vision_exporter.py` (the process exporter prints JSON detections to stdout).

3. In another terminal, run the fusion CLI and pipe it into the display:

   ```bash
   python -m sandevistan.cli --config docs/demo-desktop-config.json --poll-interval 0.5 \
     | python -m sandevistan.display --space-width 8 --space-height 5
   ```

4. Optional: if you do not want Wi-Fi in the demo, remove the `ingestion.wifi_sources` block from
   `docs/demo-desktop-config.json` and skip step 1.

## Wi-Fi telemetry sources
Supported ingestion methods today focus on **HTTP JSON exporters** that run on or near the target
AP/router. Typical deployments use:

- **OpenWRT/hostapd exporters** that expose RSSI/CSI telemetry over an HTTP endpoint.
- **Monitor mode sniffers** that forward parsed RSSI/CSI frames to a local HTTP exporter service.

If you need pcap parsing or vendor SDK integrations, wrap them behind the same HTTP exporter schema
so the adapter can ingest without changes.

### Required permissions
- **Router/AP access**: read permission (or telemetry API token) to pull RSSI/CSI metrics.
- **Network access**: the fusion host must reach exporter endpoints over the local network.
- **Monitor mode capture (optional)**: sniffers require elevated privileges/root on the capture
  host to enable monitor mode and read frames.

## Environment variables
This prototype does not hardcode environment variables, but deployments typically use the following to
standardize runtime behavior. Treat these as **recommended conventions** to keep environments
consistent:

- `SANDEVISTAN_LOG_LEVEL`: `DEBUG`, `INFO`, `WARNING`, `ERROR`.
- `SANDEVISTAN_RETENTION_ENABLED`: `true` or `false` to gate in-memory retention.
- `SANDEVISTAN_MEASUREMENT_TTL_SECONDS`: float seconds for measurement TTL.
- `SANDEVISTAN_LOG_TTL_SECONDS`: float seconds for audit log TTL.
- `SANDEVISTAN_CLEANUP_INTERVAL_SECONDS`: float seconds between retention cleanup sweeps.
- `SANDEVISTAN_SPACE_WIDTH_METERS`: float width of the tracked space.
- `SANDEVISTAN_SPACE_HEIGHT_METERS`: float height of the tracked space.
- `SANDEVISTAN_COORD_ORIGIN`: `x,y` tuple for the coordinate origin (meters).

If you already manage configuration via files or a secret store, map those settings into the
corresponding runtime configuration objects before starting the pipeline.

## Audit logging and consent enforcement
Audit logging and consent checks are configured through the CLI JSON config. To enable them, add
an `audit` block with the options below:

```json
{
  "audit": {
    "enabled": true,
    "require_consent": true,
    "consent_records": [
      {
        "status": "granted",
        "participant_id": "demo-user-001"
      }
    ]
  }
}
```

- `audit.enabled`: turn on audit logging and retention of provenance/track update events.
- `audit.require_consent`: when `true`, the pipeline enforces that consent records exist before
  logging updates; when `false`, audit logs are captured without consent checks.
- `audit.consent_records`: optional seed data for demo or bootstrap flows. Each entry can include
  `status` (`granted` or `revoked`), plus optional `participant_id` and `session_id`.

## Local network constraints
- **On-prem only**: All processing must stay within a trusted local network. Avoid internet egress for
  raw sensor data.
- **Low latency**: Keep Wi-Fi and camera ingestion on the same LAN as the fusion process to minimize
  jitter and timestamp skew.
- **Isolated VLANs**: Prefer segregated VLANs for sensor traffic to reduce exposure and simplify
  access control.
- **Clock discipline**: Ensure consistent NTP sources across sensor hosts and the fusion runtime.
- **Bandwidth planning**: Camera streams can saturate links quickly. Use hardware-accelerated
  encoding and downsample as needed to maintain <250ms fusion latency.

## Deployment checklist
1. Confirm consent and ethics policy alignment before enabling any capture.
2. Validate that all sensors are inside the trusted local network boundary.
3. Establish a shared coordinate system and document sensor placements.
4. Configure retention defaults (disabled unless explicitly enabled).
5. Run a short calibration pass and compare track output against ground truth markers.
