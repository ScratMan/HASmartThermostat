# Services Reference

[← Back to Main README](../README.md) | [Parameters Reference](parameters.md) | [PID Tuning Guide](pid_tuning.md)

---

Home Assistant services allow dynamic adjustment of PID parameters, filters, modes, and presets at runtime without restarting Home Assistant.

## 1. Set PID Gains (`smart_thermostat.set_pid_gain`)

Adjust PID gains dynamically for heating and/or cooling modes. Changes are saved to the Home Assistant storage/database and restored across restarts.

### Parameters:
- `kp` (Optional, float) — Proportional gain for heating mode
- `ki` (Optional, float) — Integral gain for heating mode
- `kd` (Optional, float) — Derivative gain for heating mode
- `ke` (Optional, float) — External temperature compensation gain for heating mode
- `kp_cool` (Optional, float) — Proportional gain for cooling mode
- `ki_cool` (Optional, float) — Integral gain for cooling mode
- `kd_cool` (Optional, float) — Derivative gain for cooling mode
- `ke_cool` (Optional, float) — External temperature compensation gain for cooling mode

### Example:
```yaml
service: smart_thermostat.set_pid_gain
data:
  kp: 11.8
  ki: 0.00878
  kp_cool: 14.2
  ki_cool: 0.005
target:
  entity_id: climate.smart_thermostat_example
```

---

## 2. Set Derivative Filter (`smart_thermostat.set_derivative_filter`)

Adjust the time constant of the derivative EMA low-pass filter on the fly.

### Parameters:
- `derivative_filter` (Required, duration e.g., `"00:02:00"` or seconds)

### Example:
```yaml
service: smart_thermostat.set_derivative_filter
data:
  derivative_filter: "00:02:00"
target:
  entity_id: climate.smart_thermostat_example
```

---

## 3. Set PID Mode (`smart_thermostat.set_pid_mode`)

Switch between PID control (`auto`) and pure Hysteresis control (`off`).

### Parameters:
- `mode` (Required, string: `'auto'` or `'off'`)

### Example:
```yaml
service: smart_thermostat.set_pid_mode
data:
  mode: 'off'
target:
  entity_id: climate.smart_thermostat_example
```

---

## 4. Set Preset Temperatures (`smart_thermostat.set_preset_temp`)

Dynamically update setpoints for preset modes.

### Parameters:
- `away_temp`, `eco_temp`, `boost_temp`, `comfort_temp`, `home_temp`, `sleep_temp`, `activity_temp` (float)
- `<preset_name>_disable` (boolean) — Disable a specific preset.

### Example:
```yaml
service: smart_thermostat.set_preset_temp
data:
  away_temp: 14.6
  boost_temp: 22.5
  home_temp_disable: true
target:
  entity_id: climate.smart_thermostat_example
```

---

## 5. Clear Integral (`smart_thermostat.clear_integral`)

Resets the accumulated integral term $I$ to `0` (or a custom initial value). Useful during PID tuning to avoid waiting for integral windup to decay naturally.

### Parameters:
- `value` (Optional, float, default `0.0`)

### Example:
```yaml
service: smart_thermostat.clear_integral
data:
  value: 0.0
target:
  entity_id: climate.smart_thermostat_example
```