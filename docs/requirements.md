# Requirements: See-Through Walls (STW)

## Terminology (Key Terms)
- **See-Through Walls (STW):** A sensing and inference capability that estimates the **presence**, **coarse location**, and **motion** of people or large objects *behind opaque barriers* within a bounded area using indirect signals (e.g., Wi-Fi CSI/RSSI and camera feeds). STW **does not** reconstruct photographic imagery of hidden spaces, read text, identify faces, or infer private attributes.
- **Target Zone (TZ):** The bounded, pre-configured indoor area where STW is permitted to operate (e.g., a floor section or room set).
- **Line-of-Sight (LoS):** Direct visual or RF path between sensors and target.
- **Non-Line-of-Sight (NLoS):** Path where the target is occluded by walls or obstacles.
- **Detection Event (DE):** A system output indicating a likely presence or motion state in the TZ.
- **Localization Estimate (LE):** The system’s best-effort position estimate (coarse grid cell or coordinates) for a DE.

## Use Cases and Non-Goals
### Use Cases
- **Safety & rescue:** Locate people behind obstacles in emergency response within a known building (e.g., smoke-filled rooms).
- **Industrial monitoring:** Detect occupancy or motion behind partitions for safety automation (e.g., forklift zones, secure areas).
- **Facility analytics:** Coarse occupancy estimation in restricted areas without visual access.

### Non-Goals (Explicitly What “See Through Walls” Means and Does Not Mean)
- **Not imaging:** STW does **not** generate visual images or silhouettes of people behind walls.
- **Not identification:** STW does **not** identify individuals, faces, or personal traits (e.g., age, gender, health).
- **Not surveillance outside TZ:** STW does **not** operate beyond the configured Target Zone boundaries.
- **Not long-range:** STW does **not** provide reliable detection across large distances, multiple floors, or unknown structures.
- **Not adversarial use:** STW is not designed for covert surveillance, spying, or bypassing privacy protections.

## Data Sources, Hardware, and Operational Constraints
### Data Sources
- **Wi-Fi RSSI (Received Signal Strength Indicator):** Coarse signal strength measurements across access points.
- **Wi-Fi CSI (Channel State Information):** Fine-grained channel measurements across subcarriers and antennas.
- **Camera feeds (optional):** On-zone or perimeter cameras for contextual verification in LoS areas (not used to infer hidden imagery).

### Expected Hardware
- **Wi-Fi infrastructure:**
  - Commodity Wi-Fi 5/6 access points and/or CSI-capable NICs.
  - Multiple APs/antennas for spatial diversity.
- **Compute node:**
  - On-prem edge server or embedded GPU for real-time inference.
- **Optional cameras:**
  - Fixed cameras with privacy masking and on-device processing.

### Operational Constraints
- **Calibration required:** Site-specific calibration of RSSI/CSI fingerprints and environment mapping.
- **Environmental sensitivity:** Performance varies with wall materials, furniture changes, and RF interference.
- **Multi-path complexity:** NLoS signals can be unstable; model must handle drift and domain shift.
- **Bandwidth and privacy:** Raw CSI and video are sensitive; prefer on-device processing and data minimization.

## Target Performance Metrics
- **Latency:**
  - End-to-end DE latency ≤ **500 ms** (p95) under normal load.
- **Localization Accuracy:**
  - LE error ≤ **1.5 m** (median) within the TZ.
- **False Positive Rate (FPR):**
  - ≤ **5%** per hour of operation in an empty TZ.
- **False Negative Rate (FNR):**
  - ≤ **10%** for stationary or slow-moving human targets in the TZ.
- **Uptime/Availability:**
  - ≥ **99%** during configured operating hours.

## Safety and Legal Constraints (Target Jurisdictions)
- **Lawful basis required:** Operation must be tied to a documented legal basis (e.g., consent, safety mandate, or contractual authorization) for each TZ.
- **Notice and transparency:** Provide clear signage and policy disclosure for areas covered by STW.
- **Data minimization:** Collect only data necessary for DE/LE outputs; avoid storing raw CSI/video unless required for debugging with strict retention limits.
- **Access control:** Restrict system access to authorized personnel; audit all DE/LE queries.
- **Jurisdictional compliance:**
  - **United States:** Comply with federal and state privacy laws, wiretap/recording statutes where applicable, and sector-specific rules (e.g., healthcare, education).
  - **European Union/EEA:** Treat CSI/video as personal data when it can be linked to individuals; comply with GDPR (lawful basis, DPIA where required, data subject rights).
  - **United Kingdom:** UK GDPR and ICO guidance for surveillance and monitoring.
  - **Canada:** PIPEDA and provincial privacy laws for workplace/consumer monitoring.
- **Prohibited uses:** Use in private residences, bathrooms, changing rooms, or other highly sensitive spaces is disallowed unless explicitly required by law and with informed consent.

## Consistency Notes
- Use the terms **STW**, **Target Zone (TZ)**, **Detection Event (DE)**, and **Localization Estimate (LE)** consistently in future documentation, design, and implementation artifacts.
