# PID Principles & Tuning Guide

[← Back to Main README](../README.md) | [Configuration & Examples](configuration.md) | [Services Reference](services.md)

---

## Principle of Operation

The target sensor measures the ambient room temperature while the heater/cooler entities control the physical system.

The PID controller continuously computes the required output demand to reach and maintain the target setpoint:

- **Digital / ON-OFF devices** (e.g., `switch`): The thermostat uses **Pulse-Width Modulation (PWM)** to regulate active heating time over a fixed PWM period. For instance, with a 15-minute PWM period:
  - PID output = **100%** → Switch stays **ON for 15 minutes**.
  - PID output = **33%** → Switch stays **ON for 5 minutes** and OFF for 10 minutes.
- **Analog / Continuous devices** (e.g., `valve`, `light`, `fan`, `climate`, `number`, `input_number`): The PID output value (or setpoint) is sent directly to the entity.

---

## PID Equations & Terms

The PID output is the weighted sum of three control terms (plus optional outdoor compensation):

$$\text{error} = \text{target\_temp} - \text{current\_temperature}$$

$$\text{di} = \text{temperature change between last two samples}$$

$$\text{dt} = \text{time elapsed between last two samples}$$

### 1. Proportional (P)
$$\text{P} = K_p \times \text{error}$$
- Adjusts compensation proportionally to the instantaneous error.
- Higher values mean stronger reaction. Increase $K_p$ for faster rise times.

### 2. Integral (I)
$$\text{I} = \text{last\_I} + (K_i \times \text{error} \times \text{dt})$$
- Compensates for cumulative residual error when temperature settles near the setpoint.
- If the system settles below setpoint, increase $K_i$. If it overshoots/settles above, decrease $K_i$.

### 3. Derivative (D)
$$\text{raw\_D} = -\frac{K_d \times \text{di}}{\text{dt}}$$
$$\text{D} = \alpha \times \text{raw\_D} + (1 - \alpha) \times \text{last\_D} \quad \text{where } \alpha = \frac{\text{dt}}{\text{derivative\_filter} + \text{dt}}$$
- Compensates for system inertia and rate of change.
- Suppresses overshoot by reducing output when temperature rises quickly.

### 4. Outdoor Compensation (E)
$$\text{E} = K_e \times (\text{target\_temp} - \text{outdoor\_temp})$$
- Automatically compensates building thermal losses based on outdoor temperature difference.

### Total Output
$$\text{output} = \text{P} + \text{I} + \text{D} + \text{E}$$
Output is then clamped to the configured range (`output_min` to `output_max`, or active clamp boundaries).

---

## Derivative Filter (`derivative_filter`)

The derivative action can react aggressively to sensor quantization noise or sudden jump steps. The `derivative_filter` parameter applies an Exponential Moving Average (EMA) low-pass filter to smooth the $D$ term:

### Recommended Filter Settings:
1. **High-frequency / Noisy sensors** (e.g., ESPHome / MQTT raw readings updating every few seconds):
   - Set `derivative_filter` between **`00:01:00` and `00:03:00`** (60s–180s).
   - Filters out quantization steps (e.g., $0.1^\circ\text{C}$ sensor steps) without adding thermal lag.
2. **Standard sensors** (updates every 1 to 5 minutes or on change):
   - Set `derivative_filter` between **`00:00:15` and `00:01:00`** (15s–60s).
3. **Smooth / Already filtered sensors** (e.g., HA `filter` integration or slow Zigbee/Z-Wave sensors):
   - Keep at **`00:00:00`** (disabled).

---

## Useful Tuning Resources & Guides

For deeper guidance on tuning PID controllers for home heating systems, consult these reference guides:

* [PID Tuning for on/off gas boiler](https://docs.google.com/document/d/1SYQxjMJ8vJnhU-7zxUrSQMOWPfgQsHsOKm13ai4pnsU), thanks to [@nistvan86](https://github.com/nistvan86)
* [PID Control Made Easy - Eurotherm](https://www.eurotherm.com/temperature-control/pid-control-made-easy/)
* [Practical PID Process Dynamics](https://clippard.com/cms/wiki/practical-pid-process-dynamics-proportional-pressure-controllers)
* [PID Tuner Online Simulation Tool](https://pidtuner.github.io/)
* [PID Development Blog by Brett Beauregard](http://brettbeauregard.com/blog/category/pid/)
* [Control Guru - PID Explained](https://controlguru.com/table-of-contents/)