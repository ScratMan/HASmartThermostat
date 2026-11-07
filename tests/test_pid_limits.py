"""Tests for the PID output limits and anti-windup (issue #326)."""

from datetime import timedelta
import time

import pytest

from homeassistant.components.climate import (
    DOMAIN as CLIMATE_DOMAIN,
    HVACMode,
)
from homeassistant.setup import async_setup_component

from custom_components.smart_thermostat.const import DOMAIN
from custom_components.smart_thermostat.pid_controller import PID, PIDAutotune


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
        "kp": 100.0,
        "ki": 0.0,
        "kd": 0.0,
    }
    config.update(overrides)
    config = {key: value for key, value in config.items() if value is not None}
    return {CLIMATE_DOMAIN: config}

async def _setup_services(hass, follow_state: bool = True):
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


async def test_integral_moves_while_output_is_inside_limits(hass, freezer):
    """Regression guard for the E shift: the integral moves inside the limits (#326).

    194bff8 fixed the reported flatline by including E in the saturation test; this
    keeps it from coming back.
    """
    await _setup_services(hass, follow_state=True)

    config = _thermostat_config(
        outdoor_sensor="sensor.outdoor",
        kp=90.0,
        ki=0.015,
        ke=0.6,
        target_temp=21.5,
        output_min=0.0,
        output_max=100.0,
        out_clamp_low=-15.0,
        out_clamp_high=170.0,
        debug=True,
    )

    hass.states.async_set("sensor.outdoor", "-15.7")  # external = 0.6 * 37.2
    hass.states.async_set("sensor.temperature", "21.0")
    hass.states.async_set("switch.heater_switch", "off")
    assert await async_setup_component(hass, CLIMATE_DOMAIN, config)
    await hass.async_block_till_done()
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        "set_hvac_mode",
        {"entity_id": "climate.test_thermostat", "hvac_mode": HVACMode.HEAT},
        blocking=True,
    )

    steps = 0

    async def cycle(temperature):
        nonlocal steps
        steps += 1
        freezer.tick(timedelta(seconds=60))
        # Vary the value slightly so every cycle produces a state change event.
        hass.states.async_set("sensor.temperature", f"{temperature + steps / 10000:.4f}")
        await hass.async_block_till_done()
        return hass.states.get("climate.test_thermostat").attributes

    # Wind the integral up with a positive error.
    for _ in range(10):
        await cycle(21.0)

    # Negative error, output well inside [-15, 170]: the integral must move down.
    before = (await cycle(21.8))["pid_i"]
    for _ in range(5):
        attributes = await cycle(21.8)
    after = attributes["pid_i"]

    assert attributes["control_output"] > -15.0
    assert after < before, (before, after, attributes["control_output"])


async def test_integral_stops_at_the_clamp_not_the_span(hass, freezer):
    """The integral stops where the clamp is reached, not where the span ends (#326).

    With the clamps inside the span, the span-based anti-windup lets the integral
    climb to output_max while the actuator is already pinned at out_clamp_high.
    """
    await _setup_services(hass, follow_state=True)

    config = _thermostat_config(
        initial_hvac_mode=HVACMode.HEAT,
        kp=1.0,
        ki=0.1,
        kd=0.0,
        target_temp=20.0,
        output_min=0.0,
        output_max=100.0,
        out_clamp_low=20.0,
        out_clamp_high=80.0,
        debug=True,
    )

    hass.states.async_set("sensor.temperature", "15.0")  # error +5, P = 5
    hass.states.async_set("switch.heater_switch", "off")
    assert await async_setup_component(hass, CLIMATE_DOMAIN, config)
    await hass.async_block_till_done()

    for step in range(10):
        freezer.tick(timedelta(seconds=60))
        hass.states.async_set("sensor.temperature", f"{15.0 + step / 10000:.4f}")
        await hass.async_block_till_done()

    attributes = hass.states.get("climate.test_thermostat").attributes
    assert attributes["control_output"] == pytest.approx(80.0)
    # I = out_clamp_high - P - D - E = 80 - 5 = 75. The span would allow 100.
    assert attributes["pid_i"] == pytest.approx(75.0, abs=0.5)


async def test_outdoor_change_updates_output_without_integrating(hass, freezer):
    """The outdoor compensation moves the output but leaves the integral untouched."""
    await _setup_services(hass, follow_state=True)

    config = _thermostat_config(
        outdoor_sensor="sensor.outdoor",
        kp=10.0,
        ki=0.01,
        ke=0.6,
        target_temp=21.5,
        debug=True,
    )

    hass.states.async_set("sensor.outdoor", "-5.0")
    hass.states.async_set("sensor.temperature", "20.0")
    hass.states.async_set("switch.heater_switch", "off")
    assert await async_setup_component(hass, CLIMATE_DOMAIN, config)
    await hass.async_block_till_done()
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        "set_hvac_mode",
        {"entity_id": "climate.test_thermostat", "hvac_mode": HVACMode.HEAT},
        blocking=True,
    )

    freezer.tick(timedelta(seconds=60))
    hass.states.async_set("sensor.temperature", "20.0001")
    await hass.async_block_till_done()
    warm_outdoor = hass.states.get("climate.test_thermostat").attributes
    assert warm_outdoor["pid_e"] == pytest.approx(15.9, abs=0.1)

    hass.states.async_set("sensor.outdoor", "5.0")
    await hass.async_block_till_done()
    mild_outdoor = hass.states.get("climate.test_thermostat").attributes

    assert mild_outdoor["pid_e"] == pytest.approx(9.9, abs=0.1)
    assert mild_outdoor["pid_i"] == pytest.approx(warm_outdoor["pid_i"])
    assert mild_outdoor["control_output"] < warm_outdoor["control_output"]


async def test_autotune_rebuild_keeps_clamps(hass):
    """The controller rebuilt at the end of autotune keeps the actuator clamps (#326)."""
    await _setup_services(hass, follow_state=True)

    config = _thermostat_config(
        autotune="ziegler-nichols",
        initial_hvac_mode=HVACMode.HEAT,
        target_temp=20.0,
        output_min=0.0,
        output_max=170.0,
        out_clamp_low=-15.0,
        out_clamp_high=50.0,
    )
    hass.states.async_set("sensor.temperature", "20.0")
    hass.states.async_set("switch.heater_switch", "off")
    assert await async_setup_component(hass, CLIMATE_DOMAIN, config)
    await hass.async_block_till_done()

    entity = _entity(hass)
    assert entity._pid_controller.clamp_low == -15.0
    assert entity._pid_controller.clamp_high == 50.0

    entity._trigger_source = "sensor"
    entity._pid_autotune.get_pid_parameters = (
        lambda rule: PIDAutotune.PIDParams(10.0, 0.1, 0.0)
    )
    entity._pid_autotune.run = lambda *args, **kwargs: True
    await entity.calc_pid()

    assert entity._pid_controller.clamp_low == -15.0
    assert entity._pid_controller.clamp_high == 50.0
    assert entity._pid_controller.out_min == 0.0
    assert entity._pid_controller.out_max == 170.0


async def test_cool_mode_respects_clamps(hass, freezer):
    """In COOL mode the output stays within the sign-flipped clamps (#326)."""
    await _setup_services(hass, follow_state=True)

    config = _thermostat_config(
        cooler="switch.heater_switch",
        heater=None,
        ac_mode=True,
        initial_hvac_mode=HVACMode.COOL,
        target_temp=20.0,
        kp=10.0,
        ki=0.01,
        min_cycle_duration="00:00:00",
        output_min=0.0,
        output_max=100.0,
        out_clamp_low=-20.0,
        out_clamp_high=60.0,
        debug=True,
    )

    hass.states.async_set("sensor.temperature", "25.0")
    hass.states.async_set("switch.heater_switch", "off")
    assert await async_setup_component(hass, CLIMATE_DOMAIN, config)
    await hass.async_block_till_done()

    entity = _entity(hass)
    assert entity._pid_controller.clamp_low == -60.0
    assert entity._pid_controller.clamp_high == 20.0

    readings = []
    for step in range(6):
        freezer.tick(timedelta(seconds=60))
        hass.states.async_set("sensor.temperature", f"{25.0 + step / 10000:.4f}")
        await hass.async_block_till_done()
        attributes = hass.states.get("climate.test_thermostat").attributes
        readings.append(attributes["control_output"])
        assert -60.0 <= attributes["control_output"] <= 20.0

    assert readings[-1] < readings[0]


def test_long_sampling_gap_cannot_overshoot_the_integral():
    """One long sampling gap must not push the integral far beyond saturation (#326)."""
    pid = PID(kp=10.0, ki=0.1, kd=0.0, out_min=0.0, out_max=100.0)

    output, _ = pid.calc(15.0, 20.0, 3600.0, 0.0)  # error +5 held for one hour
    assert output == pytest.approx(100.0)
    # Bounded by clamp_high - P - D - E, not by ki * error * dt = 1800.
    assert pid.integral == pytest.approx(50.0)

    now = 3600.0
    for _ in range(20):
        now += 60
        output, _ = pid.calc(20.5, 20.0, now, now - 60)
    assert output == pytest.approx(0.0)
