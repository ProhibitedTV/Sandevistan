# Wearable Assembly Guide (Raspberry Pi 5)

This guide documents the baseline wearable hardware stack and assembly steps for the
Raspberry Pi 5 deployment. It focuses on a **portable, self-contained** build that can
run the local fusion pipeline without relying on external infrastructure.

## Hardware decisions (baseline)

- **Compute**: Raspberry Pi 5 (built-in Wi-Fi + Bluetooth).
- **Power**: USB-C PD power bank capable of **5V/5A (25W) sustained**, preferably 30W+.
- **Storage**: High-endurance microSD (64GB+) or NVMe via M.2 HAT for heavy logging.
- **Cooling**: Active cooler (official Pi 5 cooler or case with fan).
- **Display**: 5"–7" HDMI touchscreen for the HUD, or smaller SPI LCD for low-power status.
- **Controls**: GPIO buttons + rotary encoder (simple and glove-friendly).
- **Enclosure**: Ventilated case with cable strain relief and mounting points.

## Wearable power + runtime notes

- The Pi 5 can draw substantial current under load; use a PD bank that advertises a stable
  5V/5A profile, not only higher-voltage PD modes.
- If using a UPS HAT, ensure it can deliver 5V/5A to the Pi 5 and provide battery telemetry.
- Plan for **2–6 hours** of runtime depending on sensor load and display brightness.

## Display + controls integration

### HDMI touchscreen
1. Use a short HDMI cable or ribbon adapter to reduce snag risk.
2. Power the display from the same power bank only if it can supply both the Pi and display.
3. For touch input, connect the display’s USB touch cable to the Pi.

### GPIO controls
Recommended minimal layout:
- **Button A**: cycle view / HUD mode
- **Button B**: pause/resume ingestion
- **Button C**: shutdown sequence
- **Rotary encoder**: zoom or alert threshold adjustment

## Assembly steps (backpack or chest rig)

1. **Mount the Pi 5** inside a ventilated enclosure with the active cooler installed.
2. **Route cables**:
   - Short USB-C cable to the power bank.
   - Short HDMI + USB touch cable to the display (if used).
   - Optional USB cable to a BLE dongle only if external Bluetooth range is required.
3. **Secure the power bank** in the same pack, with a strain-relief loop for the USB-C cable.
4. **Attach the display** to the shoulder strap or chest plate for visibility.
5. **Add controls** to a reachable strap location (Velcro/3D-printed mount).
6. **Verify airflow** (intake/exhaust) and keep the cooler unobstructed.

## Pi 5 software readiness

The repo supports Raspberry Pi OS 64-bit (Python 3.10+). Optional runtime dependencies:

- **BLE scanning**: `bleak` + BlueZ (requires permissions).
- **mmWave serial**: `pyserial`.
- **HUD display**: `pygame`.
- **Wi-Fi capture**: `iw` + `nl80211` tools.

CSI capture requires specialized NIC/firmware; the built-in Pi 5 Wi-Fi typically only
provides RSSI, so plan accordingly if CSI is required.

## Quick start checklist

1. Flash Raspberry Pi OS 64-bit and enable SSH/Wi-Fi.
2. Install project dependencies and optional modules as needed.
3. Confirm `iw`/BlueZ access and serial permissions.
4. Run the CLI on the Pi with a local config.
5. Pipe output into the HUD or display module if a screen is attached.

## Field reliability tips

- Preload configs and log to a bounded ring buffer to avoid SD wear.
- Keep a spare USB-C cable and a second power bank on hand.
- Use a lightweight shoulder/chest rig to minimize cable strain.
