# Installation Guide

[← Back to Main README](../README.md)

---

## Installation via Home Assistant Marketplace (Recommended)

Since SmartThermostat is registered in the official brand repository, you can install it directly from the Home Assistant interface without adding a custom repository manually.

1. Open **Settings → Add-ons / Marketplace → Integrations** (or navigate to **Marketplace** from your side menu).
2. Search for **Smart Thermostat**.
3. Click on the **Smart Thermostat** card and click **Download / Install**.
4. Restart Home Assistant to load the component.
5. Go to **Settings → Devices & Services → Add Integration**, search for **Smart thermostat**, and complete the configuration wizard.

---

## Manual Installation

If you prefer to install the integration manually without using the Marketplace:

1. Navigate to your Home Assistant configuration directory `<conf-dir>` (where `configuration.yaml` is located, typically `/config` or `/homeassistant/.homeassistant/`).
2. Create the `<conf-dir>/custom_components/` directory if it does not already exist.
3. Copy the `smart_thermostat` folder from this repository into `<conf-dir>/custom_components/`.
4. Restart Home Assistant.
5. Set up the thermostat via **Settings → Devices & Services → Add Integration** or through `configuration.yaml`.