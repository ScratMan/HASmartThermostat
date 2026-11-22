# Parameters Reference

[← Back to Main README](../README.md) | [Configuration & Examples](configuration.md) | [PID Tuning Guide](pid_tuning.md)

---

All parameters are categorized below by functional area.

## 1. Basic & Hardware Parameters

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `name` | string | `Smart Thermostat` | Friendly name of the thermostat entity. |
| `unique_id` | string | `none` | Unique ID for the entity. Required when cascading thermostats. |
| `heater` | string \| list | `None` | Entity ID or list of entity IDs for heating control. Supports switches, valves, lights, climate, numbers, input_numbers. |
| `cooler` | string \| list | `None` | Entity ID or list of entity IDs for cooling control. |
| `invert_heater` | boolean | `false` | Inverts switch polarity (ON when idle, OFF when active). |
| `target_sensor` | string | **Required** | Entity ID for the ambient temperature sensor. |
| `outdoor_sensor` | string | `None` | Entity ID for outdoor temperature sensor (used with `ke` / `ke_cool`). |
| `ac_mode` | boolean | `false` | Treats the heater entity as a cooling device (when `cooler` is omitted). |
| `force_off_state` | boolean | `true` | Forces actuator entities OFF when thermostat mode is set to `OFF`. |
| `initial_hvac_mode` | string | `None` | Forces operation mode on HA startup (`HEAT`, `COOL`, `OFF`). Restores previous mode if omitted. |

---

## 2. Setpoint, Range & Display Parameters

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `min_temp` | float | `7.0` | Minimum selectable target temperature setpoint. |
| `max_temp` | float | `35.0` | Maximum selectable target temperature setpoint. |
| `target_temp` | float | `None` | Initial target temperature setpoint. |
| `target_temp_step` | float | `0.5` (C) / `1.0` (F) | Step interval for adjusting setpoint in UI (`0.1`, `0.5`, `1.0`). |
| `precision` | float | `0.1` (C) / `1.0` (F) | Temperature display precision (`0.1`, `0.5`, `1.0`). |
| `cold_tolerance` | float | `0.3` | Hysteresis deadband below setpoint when PID is OFF. |
| `hot_tolerance` | float | `0.3` | Hysteresis deadband above setpoint when PID is OFF. |

---

## 3. Heating PID Gains & Control

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `kp` | float | `100.0` | Proportional gain for heating mode. |
| `ki` | float | `0.0` | Integral gain for heating mode. |
| `kd` | float | `0.0` | Derivative gain for heating mode. |
| `ke` | float | `0.0` | Outdoor temperature compensation gain for heating mode. |
| `pwm` | duration | `00:15:00` | Pulse-Width Modulation cycle time for binary ON/OFF heaters. |
| `derivative_filter` | duration | `00:00:00` | Time constant ($\tau$) for EMA low-pass filter on $D$ term. |
| `sampling_period` | duration | `00:00:00` | Interval between PID computations. If `0`, calculates on every sensor update. |
| `keep_alive` | duration | **Required** | Periodic update interval for PWM and actuator state refreshes. |

---

## 4. Cooling PID Gains & Control

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `kp_cool` | float | `None` | Proportional gain for cooling mode (falls back to `kp` if omitted). |
| `ki_cool` | float | `None` | Integral gain for cooling mode (falls back to `ki` if omitted). |
| `kd_cool` | float | `None` | Derivative gain for cooling mode (falls back to `kd` if omitted). |
| `ke_cool` | float | `None` | Outdoor temperature compensation gain for cooling mode (falls back to `ke` if omitted). |
| `pwm_cool` | duration | `None` | PWM cycle time for cooling binary entities (falls back to `pwm` if omitted). |

---

## 5. Actuator Output Range & Clamping

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `output_precision` | integer | `1` | Decimals for control output (set to `0` for integer valve levels). |
| `output_min` | float | `0.0` | Minimum control output value (Heating). |
| `output_max` | float | `100.0` | Maximum control output value (Heating). |
| `out_clamp_low` | float \| string | `output_min` | Low output clamp boundary or entity ID (Heating). |
| `out_clamp_high` | float \| string | `output_max` | High output clamp boundary or entity ID (Heating). |
| `output_min_cool` | float | `None` | Minimum control output value for cooling (falls back to `-output_max`). |
| `output_max_cool` | float | `None` | Maximum control output value for cooling (falls back to `-output_min`). |
| `out_clamp_low_cool` | float \| string | `None` | Low output clamp boundary or entity ID for cooling. |
| `out_clamp_high_cool` | float \| string | `None` | Maximum clamp limit for cooling mode. |

---

## 6. Cycle Protection & Minimum Durations

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `min_cycle_duration` | duration | `00:00:00` | Minimum ON time for binary switches (Heating). |
| `min_off_cycle_duration` | duration | `min_cycle_duration` | Minimum OFF time for binary switches (Heating). |
| `min_cycle_duration_pid_off` | duration | `min_cycle_duration` | Minimum ON time when PID mode is OFF (Heating). |
| `min_off_cycle_duration_pid_off` | duration | `min_cycle_duration_pid_off` | Minimum OFF time when PID mode is OFF (Heating). |
| `min_cycle_duration_cool` | duration | `None` | Minimum ON time for cooling switches. |
| `min_off_cycle_duration_cool` | duration | `None` | Minimum OFF time for cooling switches. |
| `min_cycle_duration_pid_off_cool` | duration | `None` | Minimum ON time when PID mode is OFF in cooling. |
| `min_off_cycle_duration_pid_off_cool` | duration | `None` | Minimum OFF time when PID mode is OFF in cooling. |

---

## 7. Safety, Presets & Debug

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `sensor_stall` | duration | `06:00:00` | Maximum allowed time without sensor update before entering safety mode (`0` to disable). |
| `output_safety` | float | `5.0` | Output level applied when sensor stall watchdog triggers. |
| `preset_sync_mode` | string | `none` | Automatically activates preset when target temp matches preset temp (`sync` or `none`). |
| `boost_pid_off` | boolean | `false` | Automatically switches PID to OFF (hysteresis) when `Boost` preset is active. |
| `away_temp` | float | `None` | Target temperature for `Away` preset. |
| `eco_temp` | float | `None` | Target temperature for `Eco` preset. |
| `boost_temp` | float | `None` | Target temperature for `Boost` preset. |
| `comfort_temp` | float | `None` | Target temperature for `Comfort` preset. |
| `home_temp` | float | `None` | Target temperature for `Home` preset. |
| `sleep_temp` | float | `None` | Target temperature for `Sleep` preset. |
| `activity_temp` | float | `None` | Target temperature for `Activity` preset. |
| `debug` | boolean | `false` | Exposes internal PID values (`pid_p`, `pid_i`, `pid_d`, `pid_e`, `pid_dt`) as state attributes. |