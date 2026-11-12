"""Tests for the minimum cycle durations (issue #316)."""

import time
from datetime import timedelta

import pytest
from homeassistant.components.climate import (
    DOMAIN as CLIMATE_DOMAIN,
)
from homeassistant.components.climate import (
    HVACMode,
)
from homeassistant.core import State
from homeassistant.setup import async_setup_component
from pytest_homeassistant.common import mock_restore_cache

from custom_components.smart_thermostat.const import DOMAIN


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


def _thermostat_config(**overrides):
    config = {
        "platform": DOMAIN,
        "name": "Test Thermostat",
        "unique_id": "test_thermostat",
        "heater": "switch.heater_switch",
        "target_sensor": "sensor.temperature",
        "target_temp": 20.0,
        "keep_alive": timedelta(seconds=60),
        "sampling_period": timedelta(seconds=0),
        "min_cycle_duration": "00:02:00",
        "kp": 100.0,
        "ki": 0.0,
        "kd": 0.0,
    }
    config.update(overrides)
    config = {key: value for key, value in config.items() if value is not None}
    return {CLIMATE_DOMAIN: config}

async def _setup_services(hass, follow_state: bool):
    """Register switch services; follow_state mirrors the command into the entity state."""
    await async_setup_component(hass, "switch", {})
    await async_setup_component(hass, "sensor", {})
    await hass.async_block_till_done()

    calls = []

    async def _handle(call):
        calls.append((call.service, time.monotonic()))
        if follow_state:
            new_state = "on" if call.service == "turn_on" else "off"
            entity_ids = call.data.get("entity_id", [])
            if isinstance(entity_ids, str):
                entity_ids = [entity_ids]
            for entity_id in entity_ids:
                hass.states.async_set(entity_id, new_state)

    hass.services.async_register("switch", "turn_on", _handle)
    hass.services.async_register("switch", "turn_off", _handle)
    return calls

def _entity(hass):
    return hass.data["entity_components"]["climate"].get_entity(
        "climate.test_thermostat"
    )

def _restore(hass, state=HVACMode.HEAT, temperature=20.0):
    mock_restore_cache(
        hass,
        (
            State(
                "climate.test_thermostat",
                state,
                attributes={"temperature": temperature, "pid_i": 0.0},
            ),
        ),
    )

async def _start(hass, temperature="20.0", config=None):
    hass.states.async_set("sensor.temperature", temperature)
    hass.states.async_set("switch.heater_switch", "off")
    assert await async_setup_component(
        hass, CLIMATE_DOMAIN, config or _thermostat_config()
    )
    await hass.async_block_till_done()


async def test_min_cycle_blocks_off_when_state_follows(hass):
    """The minimum ON duration is honoured when the switch reports its state."""
    calls = await _setup_services(hass, follow_state=True)
    _restore(hass)
    await _start(hass)

    hass.states.async_set("sensor.temperature", "10.0")
    await hass.async_block_till_done()
    assert calls[-1][0] == "turn_on", calls
    on_time = calls[-1][1]

    hass.states.async_set("sensor.temperature", "20.0")
    await hass.async_block_till_done()
    assert [call for call in calls if call[1] > on_time] == [], calls


async def test_min_cycle_blocks_off_when_state_lags(hass):
    """A device that reports its state late must not be switched off immediately (#316)."""
    calls = await _setup_services(hass, follow_state=False)
    _restore(hass)
    await _start(hass)

    hass.states.async_set("sensor.temperature", "10.0")
    await hass.async_block_till_done()
    assert calls[-1][0] == "turn_on", calls
    on_time = calls[-1][1]

    hass.states.async_set("sensor.temperature", "20.0")
    await hass.async_block_till_done()
    assert [call for call in calls if call[1] > on_time] == [], calls


async def test_startup_does_not_toggle_device(hass):
    """Starting without a restore state must not turn the heater on then off (#316)."""
    calls = await _setup_services(hass, follow_state=True)
    await _start(hass, temperature="10.0")

    assert all(call[0] != "turn_on" for call in calls), calls
    assert all(call[0] != "turn_off" for call in calls), calls


async def test_startup_does_not_toggle_device_with_unknown_state(hass):
    """An unusable restore state must not drive the heater then switch it off (#316)."""
    calls = await _setup_services(hass, follow_state=True)
    _restore(hass, state="unknown")
    await _start(hass, temperature="10.0")

    assert all(call[0] != "turn_on" for call in calls), calls
    assert all(call[0] != "turn_off" for call in calls), calls


async def test_refresh_does_not_restart_cycle_timer(hass):
    """Re-sending the current command must not restart the minimum cycle."""
    calls = await _setup_services(hass, follow_state=True)
    _restore(hass)
    await _start(hass)
    entity = _entity(hass)

    hass.states.async_set("sensor.temperature", "10.0")
    await hass.async_block_till_done()
    assert calls[-1][0] == "turn_on"
    cycle_time = entity._last_heat_cycle_time
    service_calls = len(calls)

    await entity._async_heater_turn_on()  # keep-alive refresh
    assert len(calls) == service_calls + 1
    assert calls[-1][0] == "turn_on"
    assert entity._last_heat_cycle_time == cycle_time

    await entity._async_heater_turn_off()  # still inside the minimum ON cycle
    assert len(calls) == service_calls + 1


async def test_external_device_change_restarts_cycle_timer(hass):
    """A device switched by another actor starts a new minimum cycle."""
    calls = await _setup_services(hass, follow_state=True)
    _restore(hass)
    await _start(hass)
    entity = _entity(hass)

    hass.states.async_set("sensor.temperature", "10.0")
    await hass.async_block_till_done()
    assert calls[-1][0] == "turn_on"
    cycle_time = entity._last_heat_cycle_time
    service_calls = len(calls)

    hass.states.async_set("switch.heater_switch", "off")  # external actor
    await hass.async_block_till_done()
    assert entity._last_device_state is False
    assert entity._last_heat_cycle_time > cycle_time

    await entity._async_heater_turn_on()  # minimum OFF cycle not elapsed
    assert len(calls) == service_calls


async def test_pwm_cycle_respects_min_duration(hass, freezer):
    """The PWM schedule stretches a short duty cycle to the minimum ON duration."""
    calls = await _setup_services(hass, follow_state=True)

    config = _thermostat_config(
        initial_hvac_mode=HVACMode.HEAT,
        target_temp=20.0,
        pwm=timedelta(seconds=60),
        min_cycle_duration="00:00:30",
        kp=10.0,
        ki=0.0,
    )

    hass.states.async_set("sensor.temperature", "19.0")  # 10% demand
    hass.states.async_set("switch.heater_switch", "off")
    assert await async_setup_component(hass, CLIMATE_DOMAIN, config)
    await hass.async_block_till_done()

    entity = _entity(hass)
    assert hass.states.get("switch.heater_switch").state == "on"
    assert calls[0][0] == "turn_on"
    on_time = calls[0][1]

    # A 6 s duty cycle is stretched to the 30 s minimum, so no OFF before then.
    freezer.tick(timedelta(seconds=29))
    await entity._async_control_heating()
    assert hass.states.get("switch.heater_switch").state == "on"
    assert all(call[0] != "turn_off" for call in calls), calls

    freezer.tick(timedelta(seconds=2))
    await entity._async_control_heating()
    assert hass.states.get("switch.heater_switch").state == "off"
    turn_off = [call for call in calls if call[0] == "turn_off"]
    assert len(turn_off) == 1
    assert turn_off[0][1] - on_time >= 30
