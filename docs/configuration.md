# Configuration & Examples

[← Back to Main README](../README.md) | [Parameters Reference](parameters.md) | [PID Tuning Guide](pid_tuning.md)

---

## Setup Methods

### 1. Configure via UI (Recommended)

1. Open **Settings → Devices & Services → Add Integration**.
2. Search for **Smart thermostat**.
3. Follow the setup wizard to select your temperature sensor, heater/cooler actuators, and PID settings.
4. Adjust settings later via **Configure** on the integration card.

### 2. Manual YAML Configuration

The smart thermostat can also be configured by adding a `climate` entry to your `configuration.yaml` file.

---

## Configuration Examples

### Single ON/OFF Heater Example

Standard configuration for controlling a single ON/OFF electric heater or boiler relay:

```yaml
climate:
  - platform: smart_thermostat
    name: Smart Thermostat Single ON/OFF Heater Example
    unique_id: smart_thermostat_single_on_off_heat_example
    heater: switch.on_off_heater
    target_sensor: sensor.ambient_temperature
    min_temp: 7
    max_temp: 28
    ac_mode: False
    target_temp: 19
    keep_alive:
      seconds: 60
    away_temp: 14
    kp: 50
    ki: 0.01
    kd: 2000
    derivative_filter: "00:02:00"
    pwm: 00:15:00
```

### Multiple Radiator Valves Example

Thermostat controlling several radiator valves in the same room:

```yaml
climate:
  - platform: smart_thermostat
    name: Smart Thermostat Multiple Valves Example
    unique_id: smart_thermostat_m_valve_example
    heater:
      - valve.radiator_valve_1
      - valve.radiator_valve_2
      - valve.radiator_valve_3
    target_sensor: sensor.ambient_temperature
    min_temp: 7
    max_temp: 28
    ac_mode: False
    target_temp: 19
    keep_alive:
      seconds: 60
    away_temp: 14
    kp: 50
    ki: 0.01
    kd: 5000
```

### Mixed Actuators Example (Digital + Analog)

Thermostat controlling a supplementary electric heater (ON/OFF via PWM) and a proportional radiator valve simultaneously:

```yaml
climate:
  - platform: smart_thermostat
    name: Smart Thermostat Mixed Actuators Example
    unique_id: smart_thermostat_mixed_actuators_example
    heater:
      - switch.supplementary_electric_heater  # On/Off device (uses PWM)
      - valve.radiator_valve_1                # Analog device (0-100% position)
    target_sensor: sensor.ambient_temperature
    min_temp: 7
    max_temp: 28
    ac_mode: False
    target_temp: 19
    keep_alive:
      seconds: 60
    away_temp: 14
    kp: 5
    ki: 0.01
    kd: 500
    output_min: 0
    output_max: 100
    pwm: 00:15:00
```

---

## Cascading PID

Optionally, two (or more) PIDs can be used in a cascading manner. For example, in underfloor heating systems, you can define an outer PID between the room temperature and the floor temperature, and an inner PID between the floor temperature and the PWM switch. This setup prevents overheating the floor slab.

See details on [Cascade Control on Wikipedia](https://en.wikipedia.org/wiki/Proportional%E2%80%93integral%E2%80%93derivative_controller#Cascade_control).

### Setup Procedure:
1. First, measure the effect of turning the underfloor heating on and off on the floor temperature sensor. Use that response data as input for [PID Tuner](https://pidtuner.github.io/) to determine the inner PID parameters.
2. Create an inner Smart Thermostat with `min_temp` and `max_temp` set to the maximum safe floor temperatures.
3. Next, measure the effect on room temperature of stepping the inner thermostat's setpoint.
4. Create the main (outer) Smart Thermostat, referencing the inner thermostat's `unique_id` or `entity_id` as its `heater`.
5. The `sampling_period` and `min_cycle_duration` should be higher for the outer thermostat, and its `pwm` can be left to `0` or omitted.

### Cascading Example YAML:

```yaml
climate:
  - platform: smart_thermostat
    name: "Bedroom Underfloor Heating Thermostat"
    unique_id: bedroom_underfloor_heating_thermostat
    heater: climate.bedroom_underfloor_heating_inner_thermostat
    target_sensor: sensor.bedroom_room_temperature
    min_temp: 7
    max_temp: 28
    output_min: 7
    output_max: 28
    out_clamp_low: 7
    out_clamp_high: 28
    ac_mode: False
    target_temp: 23
    keep_alive:
      seconds: 60
    sampling_period: 600
    min_cycle_duration: 50
    force_off_state: false
    kp: 19.4
    ki: 0.005
    kd: 0

  - platform: smart_thermostat
    name: "Bedroom Underfloor Heating Inner Thermostat"
    unique_id: bedroom_underfloor_heating_inner_thermostat
    heater: switch.bedroom_heating
    target_sensor: sensor.bedroom_floor_temperature
    min_temp: 7
    max_temp: 28
    ac_mode: False
    target_temp: 23
    keep_alive:
      seconds: 60
    sampling_period: 120
    min_cycle_duration: 10
    kp: 2.06
    ki: 0.001
    kd: 0
    pwm: 00:15:00
```