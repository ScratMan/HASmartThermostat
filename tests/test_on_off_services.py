"""Tests for ON/OFF service selection."""

from datetime import timedelta

import pytest
from homeassistant.components.climate import (
    DOMAIN as CLIMATE_DOMAIN,
)
from homeassistant.components.climate import HVACMode
from homeassistant.setup import async_setup_component
from pytest_homeassistant.common import async_mock_service

from custom_components.smart_thermostat.const import DOMAIN


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


async def test_group_entity_uses_generic_turn_off(hass):
    """A sensor update that switches a group heater off must not call group.turn_off.

    Confirmed on the 2026.11.0 release: _async_sensor_changed reached
    _async_heater_turn_off and raised ServiceNotFound: group.turn_off.
    """
    await async_setup_component(hass, "sensor", {})
    await hass.async_block_till_done()
    for service in ("turn_on", "turn_off"):
        if hass.services.has_service("homeassistant", service):
            hass.services.async_remove("homeassistant", service)
    async_mock_service(hass, "homeassistant", "turn_on")
    turn_off = async_mock_service(hass, "homeassistant", "turn_off")

    hass.states.async_set("sensor.temperature", "25.0")
    hass.states.async_set("group.heating", "on")
    assert await async_setup_component(
        hass,
        CLIMATE_DOMAIN,
        {
            CLIMATE_DOMAIN: {
                "platform": DOMAIN,
                "name": "Group Heater",
                "heater": "group.heating",
                "target_sensor": "sensor.temperature",
                "target_temp": 20.0,
                "keep_alive": timedelta(seconds=60),
                "sampling_period": timedelta(seconds=0),
                "initial_hvac_mode": HVACMode.HEAT,
                "kp": 100.0,
                "ki": 0.0,
                "kd": 0.0,
                "pwm": timedelta(seconds=60),
            }
        },
    )
    await hass.async_block_till_done()
    turn_off.clear()

    hass.states.async_set("sensor.temperature", "25.1")
    await hass.async_block_till_done()

    assert turn_off, "homeassistant.turn_off was not called"
    assert turn_off[-1].data["entity_id"] == "group.heating"
