"""Tests for the Smart Thermostat climate platform."""
from datetime import timedelta
import csv
import math
from pathlib import Path
import pytest

from homeassistant.components.climate import (
    ATTR_TEMPERATURE,
    DOMAIN as CLIMATE_DOMAIN,
    HVACMode,
)
from homeassistant.core import State
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import mock_restore_cache

from custom_components.smart_thermostat.const import DOMAIN


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations for testing in Home Assistant."""
    yield


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
        simulation_data.append({
            "time_sec": current_time_sec,
            "room_temp": round(room_temp, 2),
            "outdoor_temp": outdoor_temp,
            "heater_state": 1 if is_heating else 0,
            "control_output": attrs.get("control_output", 0.0),
            "pid_p": attrs.get("pid_p", 0.0),
            "pid_i": attrs.get("pid_i", 0.0),
            "pid_d": attrs.get("pid_d", 0.0),
            "pid_e": attrs.get("pid_e", 0.0),
        })

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
    output_path = tmp_path / "thermal_simulation_results.csv"
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