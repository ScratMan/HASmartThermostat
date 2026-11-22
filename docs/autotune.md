# Autotune Guide

[← Back to Main README](../README.md) | [PID Tuning Guide](pid_tuning.md) | [Parameters Reference](parameters.md)

---

> [!WARNING]
> **Autotune is an experimental feature and may not work optimally for slow HVAC thermal loops. Manual tuning or online simulation tools like [PID Tuner](https://pidtuner.github.io/) are generally recommended.**

## How to Run Autotune

1. Set the `autotune` parameter in configuration to your desired tuning rule (e.g. `ziegler-nichols`).
2. Optionally adjust `noiseband` and `lookback` parameters.
3. Restart Home Assistant to start the thermostat in autotune mode.
4. Set the desired target temperature setpoint.
5. The autotuner will analyze system response by cycling the heater relay and measuring temperature oscillations.
6. Monitor progress via the `autotune_status` entity attribute.
7. Once finished, computed gains ($K_p$, $K_i$, $K_d$) are logged in Home Assistant logs and automatically applied to the thermostat.

---

## Autotuning Rules

The autotuner evaluates multiple tuning methods and logs calculated values for comparison:

| Rule Name | $K_p$ Divisor | $K_i$ Divisor | $K_d$ Divisor | Description |
| :--- | :--- | :--- | :--- | :--- |
| `"ziegler-nichols"` | 34 | 40 | 160 | Classic aggressive tuning with fast response. |
| `"tyreus-luyben"` | 44 | 9 | 126 | Conservative tuning with less overshoot. |
| `"ciancone-marlin"` | 66 | 88 | 162 | Designed for process disturbances. |
| `"pessen-integral"` | 28 | 50 | 133 | Optimized for quick error integration. |
| `"some-overshoot"` | 60 | 40 | 60 | Balanced transient overshoot. |
| `"no-overshoot"` | 100 | 40 | 60 | Smooth monotonic response without overshoot. |
| `"brewing"` | 2.5 | 6 | 380 | Tailored for liquid vessel heating dynamics. |