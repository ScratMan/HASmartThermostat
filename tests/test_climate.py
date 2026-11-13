"""Tests for the Smart Thermostat climate platform."""

import csv
import math
from datetime import timedelta

import pytest
from homeassistant.components.climate import (
    ATTR_TEMPERATURE,
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.components.climate import (
    DOMAIN as CLIMATE_DOMAIN,
)
from homeassistant.core import State
from homeassistant.setup import async_setup_component
from pytest_homeassistant.common import mock_restore_cache

from custom_components.smart_thermostat.climate import SmartThermostat
from custom_components.smart_thermostat.const import DOMAIN

# Home Assistant 2026.11 renamed the temperature properties and _attr_ shorthands
HAS_NATIVE_TEMPERATURE = hasattr(ClimateEntity, "native_temperature_unit")


@pytest.fixture(autouse=True)
async def setup_switch_handler(hass):
    """Set up switch domain and register service handlers to reflect state changes."""
    await async_setup_component(hass, "switch", {})
    await async_setup_component(hass, "sensor", {})
    await hass.async_block_till_done()

    async def _async_handle_switch_service(call):
        entity_ids = call.data.get("entity_id", [])
        if isinstance(entity_ids, str):
            entity_ids = [entity_ids]
        new_state = "on" if call.service == "turn_on" else "off"
        for eid in entity_ids:
            hass.states.async_set(eid, new_state)

    hass.services.async_register("switch", "turn_on", _async_handle_switch_service)
    hass.services.async_register("switch", "turn_off", _async_handle_switch_service)


def test_temperature_properties_follow_home_assistant_api():
    """Temperature properties use the names the running Home Assistant defines."""
    deprecated = (
        "temperature_unit",
        "current_temperature",
        "target_temperature",
    )
    native = (
        "native_temperature_unit",
        "native_current_temperature",
        "native_target_temperature",
    )
    for name in native:
        assert name in vars(SmartThermostat)
    if HAS_NATIVE_TEMPERATURE:
        for name in deprecated:
            assert name not in vars(SmartThermostat)
    else:
        for name in deprecated:
            assert name in vars(SmartThermostat)


async def test_restore_state_pid_i_and_gains(hass):
    """Test that pid_i, target temperature, and PID gains are properly restored on startup."""
    mock_restore_cache(
        hass,
        (
            State(
                "climate.test_thermostat",
                HVACMode.HEAT,
                attributes={
                    ATTR_TEMPERATURE: 21.5,
                    "pid_i": 18.4,
                    "kp": 12.0,
                    "ki": 0.05,
                    "kd": 45.0,
                    "ke": 0.6,
                    "pid_mode": "auto",
                },
            ),
        ),
    )

    config = {
        CLIMATE_DOMAIN: {
            "platform": DOMAIN,
            "name": "Test Thermostat",
            "heater": "switch.heater_switch",
            "target_sensor": "sensor.temperature",
            "outdoor_sensor": "sensor.outdoor_temperature",
            "min_temp": 7.0,
            "max_temp": 35.0,
            "target_temp": 20.0,
            "kp": 10.0,
            "ki": 0.01,
            "kd": 40.0,
            "ke": 0.5,
            "keep_alive": timedelta(seconds=60),
        }
    }

    assert await async_setup_component(hass, CLIMATE_DOMAIN, config)
    await hass.async_block_till_done()

    state = hass.states.get("climate.test_thermostat")
    assert state is not None
    assert state.state == HVACMode.HEAT
    assert state.attributes[ATTR_TEMPERATURE] == 21.5
    assert state.attributes["pid_i"] == 18.4
    assert state.attributes["kp"] == 12.0
    assert state.attributes["ki"] == 0.05
    assert state.attributes["kd"] == 45.0
    assert state.attributes["ke"] == 0.6
    assert state.attributes["pid_mode"] == "auto"


async def test_turn_on_turn_off_services(hass):
    """Test standard climate services (turn_on / turn_off)."""
    config = {
        CLIMATE_DOMAIN: {
            "platform": DOMAIN,
            "name": "Test Thermostat",
            "heater": "switch.heater_switch",
            "target_sensor": "sensor.temperature",
            "keep_alive": timedelta(seconds=60),
        }
    }

    assert await async_setup_component(hass, CLIMATE_DOMAIN, config)
    await hass.async_block_till_done()

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        "set_hvac_mode",
        {"entity_id": "climate.test_thermostat", "hvac_mode": HVACMode.OFF},
        blocking=True,
    )

    state = hass.states.get("climate.test_thermostat")
    assert state is not None
    assert state.state == HVACMode.OFF


async def test_proportional_valve_position(hass):
    """Test controlling a 0-100% proportional valve via set_valve_position."""
    await async_setup_component(hass, "valve", {})
    last_position: int | None = None

    async def _handle_set_position(call):
        nonlocal last_position
        last_position = call.data.get("position")
        hass.states.async_set("valve.proportional_valve", f"{last_position}")

    hass.services.async_register("valve", "set_valve_position", _handle_set_position)

    hass.states.async_set("sensor.temperature", "19.0")
    hass.states.async_set("valve.proportional_valve", "0")

    config = {
        CLIMATE_DOMAIN: {
            "platform": DOMAIN,
            "name": "Proportional Valve Thermostat",
            "heater": ["valve.proportional_valve"],
            "target_sensor": "sensor.temperature",
            "target_temp": 20.0,
            "kp": 50.0,
            "ki": 0.0,
            "kd": 0.0,
            "pwm": timedelta(seconds=0),
            "keep_alive": timedelta(seconds=60),
            "sampling_period": timedelta(seconds=0),
        }
    }

    assert await async_setup_component(hass, CLIMATE_DOMAIN, config)
    await hass.async_block_till_done()

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        "set_hvac_mode",
        {
            "entity_id": "climate.proportional_valve_thermostat",
            "hvac_mode": HVACMode.HEAT,
        },
        blocking=True,
    )

    assert last_position == 50
    assert (
        hass.states.get("climate.proportional_valve_thermostat").attributes[
            "control_output"
        ]
        == 50
    )


@pytest.mark.asyncio
async def test_input_number_heater_output_clamping(hass):
    """Test that proportional output to an input_number never exceeds output_max (#243)."""
    # 1. Register input_number domain and setup mock service to track set_value calls
    await async_setup_component(hass, "input_number", {})
    await async_setup_component(hass, "sensor", {})
    await hass.async_block_till_done()

    last_set_value: float | None = None

    async def _handle_set_value(call):
        nonlocal last_set_value
        last_set_value = call.data.get("value")
        hass.states.async_set("input_number.z1valve", f"{last_set_value}")

    hass.services.async_register("input_number", "set_value", _handle_set_value)

    # Setup initial sensor states matching Issue #243
    hass.states.async_set("sensor.temperature", "17.0")
    hass.states.async_set("input_number.z1valve", "0.0")

    # Configuration identical to Issue #243 (output range 0..10, Kd = 500)
    config = {
        CLIMATE_DOMAIN: {
            "platform": DOMAIN,
            "name": "Zone1 Thermostat",
            "heater": ["input_number.z1valve"],
            "target_sensor": "sensor.temperature",
            "min_temp": 7.0,
            "max_temp": 28.0,
            "target_temp": 19.0,
            "kp": 5.0,
            "ki": 0.01,
            "kd": 500.0,  # High Kd that previously caused raw PID output spike to 33.6
            "output_min": 0.0,
            "output_max": 10.0,
            "pwm": timedelta(seconds=0),
            "keep_alive": timedelta(seconds=60),
            "sampling_period": timedelta(seconds=0),
        }
    }

    assert await async_setup_component(hass, CLIMATE_DOMAIN, config)
    await hass.async_block_till_done()

    # 2. Switch mode to HEAT (triggers initial control pass)
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        "set_hvac_mode",
        {"entity_id": "climate.zone1_thermostat", "hvac_mode": HVACMode.HEAT},
        blocking=True,
    )

    # 3. Simulate sudden large setpoint increase to 28°C (Step 3 of issue #243)
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        "set_temperature",
        {"entity_id": "climate.zone1_thermostat", "temperature": 28.0},
        blocking=True,
    )

    # 4. Verify that the output value sent to input_number is strictly clamped to output_max (10.0)
    state = hass.states.get("climate.zone1_thermostat")
    assert state.attributes["control_output"] == 10.0
    assert last_set_value == 10.0


async def test_heat_cool_dual_mode(hass):
    """Test switching between HEAT and COOL modes with heater and cooler entities."""
    hass.states.async_set("sensor.temperature", "25.0")
    hass.states.async_set("switch.heater", "off")
    hass.states.async_set("switch.cooler", "off")

    config = {
        CLIMATE_DOMAIN: {
            "platform": DOMAIN,
            "name": "Reversible Thermostat",
            "heater": ["switch.heater"],
            "cooler": ["switch.cooler"],
            "target_sensor": "sensor.temperature",
            "target_temp": 22.0,
            "initial_hvac_mode": HVACMode.OFF,
            "kp": 10.0,
            "ki": 0.0,
            "kd": 0.0,
            "pwm": timedelta(seconds=60),
            "keep_alive": timedelta(seconds=60),
            "sampling_period": timedelta(seconds=0),
        }
    }

    assert await async_setup_component(hass, CLIMATE_DOMAIN, config)
    await hass.async_block_till_done()

    state = hass.states.get("climate.reversible_thermostat")
    assert HVACMode.HEAT in state.attributes["hvac_modes"]
    assert HVACMode.COOL in state.attributes["hvac_modes"]

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        "set_hvac_mode",
        {"entity_id": "climate.reversible_thermostat", "hvac_mode": HVACMode.COOL},
        blocking=True,
    )

    assert hass.states.get("switch.cooler").state == "on"
    assert hass.states.get("switch.heater").state == "off"

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        "set_hvac_mode",
        {"entity_id": "climate.reversible_thermostat", "hvac_mode": HVACMode.HEAT},
        blocking=True,
    )

    assert hass.states.get("switch.cooler").state == "off"
    assert hass.states.get("switch.heater").state == "off"


@pytest.mark.asyncio
async def test_thermal_simulation_pid_mode_transition_to_hysteresis(hass, freezer):
    """Test transitioning from PID AUTO (with Ke) to PID OFF (pure hysteresis deadband) and back."""
    room_temp = 18.0
    outdoor_temp = 2.0  # Cold outdoor temperature

    hass.states.async_set("sensor.temperature", f"{room_temp:.2f}")
    hass.states.async_set("sensor.outdoor_temperature", f"{outdoor_temp:.2f}")
    hass.states.async_set("switch.heater_switch", "off")

    config = {
        CLIMATE_DOMAIN: {
            "platform": DOMAIN,
            "name": "Transition Thermostat",
            "heater": "switch.heater_switch",
            "target_sensor": "sensor.temperature",
            "outdoor_sensor": "sensor.outdoor_temperature",
            "target_temp": 20.0,
            "hot_tolerance": 0.2,  # Upper threshold: 20.2°C
            "cold_tolerance": 0.2,  # Lower threshold: 19.8°C
            "kp": 20.0,
            "ki": 0.01,
            "kd": 5.0,
            "ke": 5.0,  # High Ke: 5 * (20 - 2) = +90% offset in AUTO mode
            "pwm": timedelta(seconds=60),  # Valid PWM for switch entity
            "keep_alive": timedelta(seconds=60),
            "sampling_period": timedelta(seconds=0),
            "debug": True,
        }
    }

    assert await async_setup_component(hass, CLIMATE_DOMAIN, config)
    await hass.async_block_till_done()

    entity_id = "climate.transition_thermostat"

    # Turn ON thermostat in HEAT mode
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        "set_hvac_mode",
        {"entity_id": entity_id, "hvac_mode": HVACMode.HEAT},
        blocking=True,
    )

    # -------------------------------------------------------------------------
    # PHASE 1: Verify initial state in PID AUTO mode (PID active)
    # -------------------------------------------------------------------------
    state_auto = hass.states.get(entity_id)
    assert state_auto.attributes["pid_mode"] == "auto"

    # -------------------------------------------------------------------------
    # PHASE 2: Switch PID mode to OFF (Pure Hysteresis with Deadband verification)
    # -------------------------------------------------------------------------
    await hass.services.async_call(
        DOMAIN,
        "set_pid_mode",
        {"entity_id": entity_id, "mode": "off"},
        blocking=True,
    )

    state_off_init = hass.states.get(entity_id)
    assert state_off_init.attributes["pid_mode"] == "off"

    # --- Step 2a: Temperature drops below lower threshold (19.7°C < 19.8°C) ---
    freezer.tick(timedelta(seconds=10))
    hass.states.async_set("sensor.temperature", "19.70")
    await hass.async_block_till_done()

    state_low = hass.states.get(entity_id)
    assert state_low.attributes["control_output"] == 100.0

    # --- Step 2b: Temperature rises inside deadband (20.0°C) ---
    # Must preserve previous state (100.0 / ON)
    freezer.tick(timedelta(seconds=10))
    hass.states.async_set("sensor.temperature", "20.00")
    await hass.async_block_till_done()

    state_deadband_up = hass.states.get(entity_id)
    assert state_deadband_up.attributes["control_output"] == 100.0

    # --- Step 2c: Temperature exceeds upper threshold (20.3°C > 20.2°C) ---
    freezer.tick(timedelta(seconds=10))
    hass.states.async_set("sensor.temperature", "20.30")
    await hass.async_block_till_done()

    state_high = hass.states.get(entity_id)
    assert state_high.attributes["control_output"] == 0.0

    # --- Step 2d: Temperature drops back inside deadband (20.0°C) ---
    # Must preserve previous state (0.0 / OFF)
    freezer.tick(timedelta(seconds=10))
    hass.states.async_set("sensor.temperature", "20.00")
    await hass.async_block_till_done()

    state_deadband_down = hass.states.get(entity_id)
    assert state_deadband_down.attributes["control_output"] == 0.0

    # -------------------------------------------------------------------------
    # PHASE 3: Switch back to PID AUTO mode
    # -------------------------------------------------------------------------
    await hass.services.async_call(
        DOMAIN,
        "set_pid_mode",
        {"entity_id": entity_id, "mode": "auto"},
        blocking=True,
    )

    state_back_auto = hass.states.get(entity_id)
    assert state_back_auto.attributes["pid_mode"] == "auto"


@pytest.mark.slow
@pytest.mark.simulation
async def test_thermal_simulation_closed_loop(hass, freezer, tmp_path):
    """Simulate a dynamic room environment with outdoor temperature variation and PID outdoor compensation."""
    # Physical simulation parameters
    room_temp = 17.0  # Initial room temperature (°C)
    heat_gain_rate = 0.05  # Heating rate when switch is ON (°C / sec)
    heat_loss_rate = 0.01  # Base thermal loss coefficient (°C / sec)

    # Initial sensor states in Home Assistant
    initial_outdoor_temp = 8.0
    hass.states.async_set("sensor.temperature", str(room_temp))
    hass.states.async_set("sensor.outdoor_temperature", str(initial_outdoor_temp))
    hass.states.async_set("switch.heater_switch", "off")

    config = {
        CLIMATE_DOMAIN: {
            "platform": DOMAIN,
            "name": "Test Thermostat",
            "heater": "switch.heater_switch",
            "target_sensor": "sensor.temperature",
            "outdoor_sensor": "sensor.outdoor_temperature",
            "min_temp": 7.0,
            "max_temp": 35.0,
            "target_temp": 20.0,
            "kp": 30.0,
            "ki": 0.05,
            "kd": 10.0,
            "ke": 0.5,  # Outdoor temperature compensation gain
            "pwm": timedelta(seconds=60),
            "keep_alive": timedelta(seconds=60),
            "sampling_period": timedelta(seconds=10),
            "debug": True,
        }
    }

    # Start thermostat
    assert await async_setup_component(hass, CLIMATE_DOMAIN, config)
    await hass.async_block_till_done()

    # Switch to HEAT mode
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        "set_hvac_mode",
        {"entity_id": "climate.test_thermostat", "hvac_mode": HVACMode.HEAT},
        blocking=True,
    )

    # SIMULATION LOOP: 12 simulated hours with 10-second steps (4320 iterations)
    step_seconds = 10
    total_simulation_hours = 12
    total_steps = (total_simulation_hours * 3600) // step_seconds
    simulation_data = []

    for step in range(total_steps):
        current_time_sec = step * step_seconds

        # 1. Dynamic outdoor temperature profile (drops from 8°C down to 2°C at midnight, then warms back to 7°C)
        # Sinusoidal profile over 12 hours
        outdoor_temp = round(
            5.0 + 3.0 * math.cos(2 * math.pi * current_time_sec / (12 * 3600)), 2
        )

        # 2. Read switch state and thermostat attributes
        state_heater = hass.states.get("switch.heater_switch")
        is_heating = state_heater is not None and state_heater.state == "on"

        state_thermostat = hass.states.get("climate.test_thermostat")
        attrs = state_thermostat.attributes if state_thermostat else {}

        # Record metrics at current timestep
        simulation_data.append(
            {
                "time_sec": current_time_sec,
                "room_temp": round(room_temp, 2),
                "outdoor_temp": outdoor_temp,
                "heater_state": 1 if is_heating else 0,
                "control_output": attrs.get("control_output", 0.0),
                "pid_p": attrs.get("pid_p", 0.0),
                "pid_i": attrs.get("pid_i", 0.0),
                "pid_d": attrs.get("pid_d", 0.0),
                "pid_e": attrs.get("pid_e", 0.0),
            }
        )

        # 3. Physical thermal dynamics computation
        # Losses are directly proportional to (room_temp - outdoor_temp)
        thermal_loss = heat_loss_rate * (room_temp - outdoor_temp) / 15.0
        if is_heating:
            room_temp += (heat_gain_rate - thermal_loss) * step_seconds
        else:
            room_temp -= thermal_loss * step_seconds

        # 4. Advance virtual time in Home Assistant
        freezer.tick(timedelta(seconds=step_seconds))

        # 5. Publish new temperature readings from sensors
        hass.states.async_set("sensor.temperature", f"{room_temp:.2f}")
        hass.states.async_set("sensor.outdoor_temperature", f"{outdoor_temp:.2f}")
        await hass.async_block_till_done()

    # SAVE SIMULATION METRICS TO TEMPORARY CSV FILE
    output_path = tmp_path / "thermal_simulation_switch_results.csv"
    fieldnames = [
        "time_sec",
        "room_temp",
        "outdoor_temp",
        "heater_state",
        "control_output",
        "pid_p",
        "pid_i",
        "pid_d",
        "pid_e",
    ]
    with open(output_path, mode="w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(simulation_data)

    print(f"\n[Simulation Output] CSV generated at: {output_path.resolve()}")

    # FINAL ASSERTIONS
    state_final = hass.states.get("climate.test_thermostat")
    assert state_final is not None
    # Temperature should remain stable around 20.0°C (± 0.5°C) despite outdoor drops
    assert 19.5 <= room_temp <= 20.5
    # Verification that external compensation (pid_e) reacted to outdoor changes
    assert state_final.attributes["pid_e"] > 0
    assert output_path.exists()


class DummyTRV(ClimateEntity):
    """Slave thermostatic valve entity receiving setpoints from the Master Thermostat."""

    _attr_native_target_temperature = 17.0
    _attr_native_temperature_unit = "°C"

    def __init__(self, entity_id="climate.slave_trv"):
        """Initialize the dummy TRV entity."""
        self.entity_id = entity_id
        self._attr_name = "Slave TRV"
        self._attr_hvac_mode = HVACMode.HEAT
        self._attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.TURN_OFF
            | ClimateEntityFeature.TURN_ON
        )

    @property
    def hvac_mode(self):
        """Return current HVAC mode."""
        return self._attr_hvac_mode

    @property
    def native_target_temperature(self):
        """Return target temperature setpoint."""
        return self._attr_native_target_temperature

    @property
    def native_temperature_unit(self):
        """Return the temperature unit."""
        return self._attr_native_temperature_unit

    if not HAS_NATIVE_TEMPERATURE:
        target_temperature = native_target_temperature
        temperature_unit = native_temperature_unit

    async def async_set_temperature(self, **kwargs):
        """Dynamically update target temperature setpoint received from Master."""
        if ATTR_TEMPERATURE in kwargs:
            self._attr_native_target_temperature = float(kwargs[ATTR_TEMPERATURE])
            self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode):
        """Set new HVAC mode."""
        self._attr_hvac_mode = hvac_mode
        self.async_write_ha_state()


@pytest.mark.slow
@pytest.mark.simulation
async def test_thermal_simulation_climate_closed_loop(hass, freezer, tmp_path):
    """Cascade simulation: Master PID adjusts Slave TRV with dynamic sensor offset."""
    room_temp = 17.0
    initial_outdoor_temp = 8.0
    max_radiator_power = 0.008  # Heating gain in °C / sec at 100% valve opening
    heat_loss_rate = 0.001  # Base thermal loss coefficient

    # DYNAMIC TRV SENSOR OFFSET PARAMETERS
    trv_offset = 0.5  # Initial offset at rest (cold radiator, °C)
    min_offset = 0.5  # Residual thermal gradient at rest (°C)
    max_offset_gain = 3.5  # Temp gain at radiator body at 100% valve opening (°C)
    tau_heat = 300.0  # Heating time constant for radiator body (5 min)
    tau_cool = 600.0  # Cooling time constant for radiator body (10 min)

    # 1. Environmental sensors
    hass.states.async_set("sensor.temperature", f"{room_temp:.2f}")
    hass.states.async_set("sensor.outdoor_temperature", f"{initial_outdoor_temp:.2f}")

    # 2. Instantiate and register DummyTRV entity
    slave_trv = DummyTRV("climate.slave_trv")

    config = {
        CLIMATE_DOMAIN: [
            {
                "platform": DOMAIN,
                "name": "Master Thermostat",
                "heater": ["climate.slave_trv"],
                "target_sensor": "sensor.temperature",
                "outdoor_sensor": "sensor.outdoor_temperature",
                "min_temp": 7.0,
                "max_temp": 35.0,
                "target_temp": 20.0,
                "output_min": 15.0,  # Range of setpoints sent to slave (°C)
                "output_max": 28.0,
                "kp": 4.0,
                "ki": 0.0005,
                "kd": 2.0,
                "ke": 0.2,
                "pwm": timedelta(seconds=0),
                "keep_alive": timedelta(seconds=60),
                "sampling_period": timedelta(seconds=10),
                "debug": True,
            }
        ]
    }

    assert await async_setup_component(hass, CLIMATE_DOMAIN, config)
    await hass.async_block_till_done()

    climate_component = hass.data[CLIMATE_DOMAIN]
    await climate_component.async_add_entities([slave_trv])
    await hass.async_block_till_done()

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        "set_hvac_mode",
        {"entity_id": "climate.master_thermostat", "hvac_mode": HVACMode.HEAT},
        blocking=True,
    )

    # 3. Simulation loop (12h with 10s step resolution)
    step_seconds = 10
    total_steps = (12 * 3600) // step_seconds
    simulation_data = []

    for step in range(total_steps):
        current_time_sec = step * step_seconds

        outdoor_temp = round(
            5.0 + 3.0 * math.cos(2 * math.pi * current_time_sec / (12 * 3600)), 2
        )

        # Master setpoint updated on slave TRV entity
        slave_target_temp = slave_trv.native_target_temperature or 0.0

        # Local TRV sensor reading with dynamic offset
        trv_sensor_temp = room_temp + trv_offset

        # Calculate valve opening (local P-control of TRV)
        slave_error = slave_target_temp - trv_sensor_temp
        valve_opening = max(0.0, min(1.0, slave_error / 2.0))

        # UPDATE OFFSET ACCORDING TO VALVE OPENING
        target_offset = min_offset + valve_opening * max_offset_gain
        tau = tau_heat if target_offset > trv_offset else tau_cool
        trv_offset += (target_offset - trv_offset) * (step_seconds / tau)

        # Room thermal dynamics
        heat_gain = valve_opening * max_radiator_power
        thermal_loss = heat_loss_rate * (room_temp - outdoor_temp) / 15.0

        room_temp += (heat_gain - thermal_loss) * step_seconds

        state_thermostat = hass.states.get("climate.master_thermostat")
        attrs = state_thermostat.attributes if state_thermostat else {}

        simulation_data.append(
            {
                "time_sec": current_time_sec,
                "room_temp": round(room_temp, 2),
                "trv_sensor_temp": round(trv_sensor_temp, 2),
                "trv_offset": round(trv_offset, 2),
                "outdoor_temp": outdoor_temp,
                "slave_target_temp": round(slave_target_temp, 2),
                "valve_opening_pct": round(valve_opening * 100, 1),
                "control_output": attrs.get("control_output", 0.0),
                "pid_p": attrs.get("pid_p", 0.0),
                "pid_i": attrs.get("pid_i", 0.0),
                "pid_d": attrs.get("pid_d", 0.0),
                "pid_e": attrs.get("pid_e", 0.0),
            }
        )

        freezer.tick(timedelta(seconds=step_seconds))

        hass.states.async_set("sensor.temperature", f"{room_temp:.2f}")
        hass.states.async_set("sensor.outdoor_temperature", f"{outdoor_temp:.2f}")
        await hass.async_block_till_done()

    # 4. Save results to CSV
    output_path = tmp_path / "thermal_simulation_climate_results.csv"
    fieldnames = [
        "time_sec",
        "room_temp",
        "trv_sensor_temp",
        "trv_offset",
        "outdoor_temp",
        "slave_target_temp",
        "valve_opening_pct",
        "control_output",
        "pid_p",
        "pid_i",
        "pid_d",
        "pid_e",
    ]
    with open(output_path, mode="w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(simulation_data)

    assert output_path.exists()


async def test_integral_memory_across_hvac_mode_transitions(hass, freezer):
    """Test preserving integral on HEAT -> OFF -> HEAT (e.g. open window) and clearing on HEAT -> OFF -> COOL."""
    hass.states.async_set("sensor.temperature", "19.0")
    hass.states.async_set("switch.heater", "off")
    hass.states.async_set("switch.cooler", "off")

    config = {
        CLIMATE_DOMAIN: {
            "platform": DOMAIN,
            "name": "Memory Test Thermostat",
            "heater": ["switch.heater"],
            "cooler": ["switch.cooler"],
            "target_sensor": "sensor.temperature",
            "target_temp": 20.0,
            "initial_hvac_mode": HVACMode.HEAT,
            "kp": 10.0,
            "ki": 0.02,
            "kd": 0.0,
            "pwm": timedelta(seconds=60),
            "keep_alive": timedelta(seconds=60),
            "sampling_period": timedelta(seconds=0),
        }
    }

    assert await async_setup_component(hass, CLIMATE_DOMAIN, config)
    await hass.async_block_till_done()

    entity_id = "climate.memory_test_thermostat"

    # 1. Accumulate integral in HEAT mode (+1.0°C error over 500s -> pid_i = 10.0)
    freezer.tick(timedelta(seconds=500))
    hass.states.async_set("sensor.temperature", "19.0001")
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.attributes["pid_i"] == pytest.approx(10.0, abs=0.05)

    # 2. Switch to OFF (simulating open-window automation)
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        "set_hvac_mode",
        {"entity_id": entity_id, "hvac_mode": HVACMode.OFF},
        blocking=True,
    )
    state = hass.states.get(entity_id)
    assert state.state == HVACMode.OFF
    assert state.attributes["pid_i"] == pytest.approx(10.0, abs=0.05)

    # 3. Advance time while OFF and resume HEAT (window closed)
    # Integral memory must be preserved and the OFF duration must not be integrated
    freezer.tick(timedelta(seconds=300))
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        "set_hvac_mode",
        {"entity_id": entity_id, "hvac_mode": HVACMode.HEAT},
        blocking=True,
    )
    state = hass.states.get(entity_id)
    assert state.state == HVACMode.HEAT
    assert state.attributes["pid_i"] == pytest.approx(10.0, abs=0.05)

    # 4. Switch to OFF then COOL (indirect direction change: HEAT -> OFF -> COOL)
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        "set_hvac_mode",
        {"entity_id": entity_id, "hvac_mode": HVACMode.OFF},
        blocking=True,
    )
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        "set_hvac_mode",
        {"entity_id": entity_id, "hvac_mode": HVACMode.COOL},
        blocking=True,
    )
    state = hass.states.get(entity_id)
    assert state.state == HVACMode.COOL
    assert state.attributes["pid_i"] == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_sensor_stall_watchdog_resets_and_triggers_safety(hass, freezer):
    """Test that sensor stall watchdog is reset by state updates/reports and triggers output_safety on timeout (#339)."""
    # 1. Setup initial sensor states
    hass.states.async_set("sensor.temperature", "19.0")
    hass.states.async_set("switch.heater_switch", "off")

    sensor_stall_duration = timedelta(hours=6)
    output_safety_val = 8.0  # Duty cycle percentage or valve position on safety trigger

    config = {
        CLIMATE_DOMAIN: {
            "platform": DOMAIN,
            "name": "Stall Test Thermostat",
            "heater": "switch.heater_switch",
            "target_sensor": "sensor.temperature",
            "target_temp": 20.0,
            "initial_hvac_mode": HVACMode.HEAT,
            "kp": 10.0,
            "ki": 0.0,
            "kd": 0.0,
            "sensor_stall": sensor_stall_duration,
            "output_safety": output_safety_val,
            "keep_alive": timedelta(minutes=5),
            "sampling_period": timedelta(seconds=0),
        }
    }

    assert await async_setup_component(hass, CLIMATE_DOMAIN, config)
    await hass.async_block_till_done()

    entity_id = "climate.stall_test_thermostat"
    entity = hass.data["entity_components"]["climate"].get_entity(entity_id)

    # 2. Advance time near the stall threshold (5 hours) without new events
    freezer.tick(timedelta(hours=5))
    await entity._async_control_heating()
    state = hass.states.get(entity_id)
    assert state.attributes["control_output"] != output_safety_val

    # 3. Simulate periodic state report event with identical temperature value (issue #339)
    # This must refresh the watchdog timestamp (_last_sensor_update)
    freezer.tick(timedelta(minutes=30))  # Total time elapsed: 5h 30m
    hass.states.async_set("sensor.temperature", "19.0")
    await hass.async_block_till_done()

    # 4. Advance time past the original 6h mark (6h 30m total, but only 1h since last report)
    # Thermostat should STILL NOT be in safety mode because the report event reset the watchdog
    freezer.tick(timedelta(hours=1))
    await entity._async_control_heating()
    state = hass.states.get(entity_id)
    assert state.attributes["control_output"] != output_safety_val

    # 5. Now let time elapse beyond the sensor_stall threshold (6 hours with zero updates)
    freezer.tick(timedelta(hours=6, minutes=1))
    await entity._async_control_heating()
    await hass.async_block_till_done()

    # 6. Verify watchdog triggered and output_safety value is applied
    state = hass.states.get(entity_id)
    assert state.attributes["control_output"] == output_safety_val
