# Production Runbook (Minimal)

> This runbook is intentionally minimal because the repository is a prototype scaffold. Expand it
> for your deployment once you integrate actual sensor ingestion and fusion services.

## Startup
1. Verify ethics and consent requirements are satisfied for the current environment.
2. Confirm sensor hosts are reachable on the trusted local network.
3. Validate system time sync (NTP) across Wi-Fi sensors, cameras, and fusion host.
4. Load the latest configuration (space, sensor placements, retention policy).
5. Start the ingestion services (Wi-Fi telemetry, camera detection pipeline).
6. Start the fusion pipeline and confirm that tracks are emitted.

## Shutdown
1. Stop the fusion pipeline gracefully (flush in-memory buffers if retention is enabled).
2. Stop camera detection and Wi-Fi ingestion services.
3. Confirm no sensor processes remain running.
4. If retention is enabled, verify cleanup has completed and that retention TTLs are enforced.

## Troubleshooting
### No tracks emitted
- Confirm both Wi-Fi and camera ingestion services are running.
- Validate that sensor timestamps are within a reasonable skew (<= 100 ms suggested).
- Check coordinate system alignment (sensor positions may be wrong or inverted).

### Track jitter or instability
- Inspect camera detections for intermittent drops or frame rate issues.
- Reduce camera stream resolution or frame rate to maintain <250ms fusion latency.
- Verify access point placements are accurate; small errors can amplify drift.

### Unexpected data retention
- Ensure retention is disabled unless explicitly enabled.
- Review TTL values and cleanup interval to confirm they match policy expectations.

### Network connectivity issues
- Confirm sensors are on the trusted VLAN and that required ports are open.
- Check for packet loss or bandwidth saturation on camera streams.

## Operational checks
- Weekly: Re-validate sensor placements and document any changes.
- Monthly: Run a calibration walkthrough with ground truth markers.
- Quarterly: Review ethics and privacy policies for compliance updates.
