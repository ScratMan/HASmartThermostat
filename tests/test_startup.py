"""Tests for the startup guard on control passes (Z-Wave error 219)."""

from datetime import timedelta

import pytest
from homeassistant.components.climate import (
    ATTR_TEMPERATURE,
    HVACMode,
)
from homeassistant.components.climate import (
    DOMAIN as CLIMATE_DOMAIN,
)
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, State
from homeassistant.setup import async_setup_component
from pytest_homeassistant.common import async_mock_service, mock_restore_cache

from custom_components.smart_thermostat.const import DOMAIN


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


def _config():
    return {
        CLIMATE_DOMAIN: {
            "platform": DOMAIN,
            "name": "Test Thermostat",
            "heater": "switch.heater_switch",
            "target_sensor": "sensor.temperature",
            "outdoor_sensor": "sensor.outdoor_temperature",
            "target_temp": 21.0,
            "pwm": timedelta(minutes=15),
            "sampling_period": timedelta(seconds=250),
            "keep_alive": timedelta(seconds=500),
            "ke": 0.7,
            "kp": 0.0,
            "ki": 0.0,
            "kd": 0.0,
        }
    }


def _restore(hass):
    mock_restore_cache(
        hass,
        (
            State(
                "climate.test_thermostat",
                HVACMode.HEAT,
                attributes={ATTR_TEMPERATURE: 21.0, "pid_i": 0.0},
            ),
        ),
    )


def _entity(hass):
    return hass.data["entity_components"]["climate"].get_entity(
        "climate.test_thermostat"
    )


async def _prepare(hass, outdoor: str | None = None):
    calls = async_mock_service(hass, "switch", "turn_on")
    calls += async_mock_service(hass, "switch", "turn_off")
    _restore(hass)
    hass.states.async_set("sensor.temperature", "18.0")
    if outdoor is not None:
        hass.states.async_set("sensor.outdoor_temperature", outdoor)
    hass.states.async_set("switch.heater_switch", "off")
    return calls


async def test_sensor_events_during_startup_do_not_command_heater(hass):
    """Sensor events received before HA is ready must not drive the heater."""
    calls = await _prepare(hass)
    hass.set_state(CoreState.starting)

    assert await async_setup_component(hass, CLIMATE_DOMAIN, _config())
    await hass.async_block_till_done()

    hass.states.async_set("sensor.outdoor_temperature", "unknown")
    await hass.async_block_till_done()
    assert _entity(hass)._ext_temp is None, "unknown outdoor value must be ignored"
    assert calls == []

    hass.states.async_set("sensor.temperature", "18.1")
    await hass.async_block_till_done()
    assert calls == []

    hass.states.async_set("sensor.outdoor_temperature", "8.4")
    await hass.async_block_till_done()
    assert calls == []


async def test_startup_issues_single_heater_command(hass):
    """After the start event, one command matches the computed PWM state."""
    calls = await _prepare(hass)
    hass.set_state(CoreState.starting)

    assert await async_setup_component(hass, CLIMATE_DOMAIN, _config())
    await hass.async_block_till_done()

    hass.states.async_set("sensor.temperature", "18.1")
    hass.states.async_set("sensor.outdoor_temperature", "8.4")
    await hass.async_block_till_done()
    assert calls == []

    hass.set_state(CoreState.running)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()

    assert [call.service for call in calls] == ["turn_on"]
    state = hass.states.get("climate.test_thermostat")
    assert state.attributes["control_output"] == 8.8


async def test_control_runs_when_ha_is_already_running(hass):
    """A reload while HA is running still controls the heater immediately."""
    calls = await _prepare(hass, outdoor="8.4")

    assert await async_setup_component(hass, CLIMATE_DOMAIN, _config())
    await hass.async_block_till_done()

    assert calls
    assert calls[0].service == "turn_on"
    assert (
        hass.states.get("climate.test_thermostat").attributes["control_output"] == 8.8
    )
