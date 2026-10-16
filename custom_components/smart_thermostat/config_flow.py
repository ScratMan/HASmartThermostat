"""Config flow for Smart Thermostat."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

import voluptuous as vol

from homeassistant.components.climate import HVACMode
from homeassistant.components.climate import DOMAIN as CLIMATE_DOMAIN
from homeassistant.components.input_number import DOMAIN as INPUT_NUMBER_DOMAIN
from homeassistant.components.light import DOMAIN as LIGHT_DOMAIN
from homeassistant.components.number import DOMAIN as NUMBER_DOMAIN
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN, SensorDeviceClass
from homeassistant.components.valve import DOMAIN as VALVE_DOMAIN
from homeassistant.const import CONF_NAME, DEGREE
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector
from homeassistant.helpers.schema_config_entry_flow import (
    SchemaCommonFlowHandler,
    SchemaConfigFlowHandler,
    SchemaFlowError,
    SchemaFlowFormStep,
)

from .const import *

HEATER_DOMAINS = [
    "switch",
    "input_boolean",
    LIGHT_DOMAIN,
    VALVE_DOMAIN,
    NUMBER_DOMAIN,
    INPUT_NUMBER_DOMAIN,
    CLIMATE_DOMAIN,
]

SENSOR_DOMAINS = [
    SENSOR_DOMAIN,
]

AUTOTUNE_OPTIONS = [
    "none",
    "ziegler-nichols",
    "tyreus-luyben",
    "ciancone-marlin",
    "pessen-integral",
    "some-overshoot",
    "no-overshoot",
    "brewing",
]

DURATION_SELECTOR = selector.DurationSelector(
    selector.DurationSelectorConfig(allow_negative=False)
)
NUMBER_SELECTOR = selector.NumberSelector(
    selector.NumberSelectorConfig(mode=selector.NumberSelectorMode.BOX, step=0.1)
)
TEMPERATURE_SELECTOR = selector.NumberSelector(
    selector.NumberSelectorConfig(
        mode=selector.NumberSelectorMode.BOX,
        unit_of_measurement=DEGREE,
        step=0.1,
    )
)
HEATER_SELECTOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain=HEATER_DOMAINS, multiple=True)
)
COOLER_SELECTOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain=HEATER_DOMAINS, multiple=True)
)
TEMPERATURE_SENSOR_SELECTOR = selector.EntitySelector(
    selector.EntitySelectorConfig(
        domain=SENSOR_DOMAINS,
        device_class=SensorDeviceClass.TEMPERATURE,
    )
)


BASIC_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): selector.TextSelector(),
        vol.Required(CONF_HEATER): HEATER_SELECTOR,
        vol.Optional(CONF_COOLER): COOLER_SELECTOR,
        vol.Required(CONF_SENSOR): TEMPERATURE_SENSOR_SELECTOR,
        vol.Optional(CONF_OUTDOOR_SENSOR): TEMPERATURE_SENSOR_SELECTOR,
        vol.Required(CONF_AC_MODE, default=False): selector.BooleanSelector(),
    }
)

TEMPERATURE_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_MIN_TEMP, default=DEFAULT_MIN_TEMP): TEMPERATURE_SELECTOR,
        vol.Optional(CONF_MAX_TEMP, default=DEFAULT_MAX_TEMP): TEMPERATURE_SELECTOR,
        vol.Optional(CONF_TARGET_TEMP, default=DEFAULT_TARGET_TEMP): TEMPERATURE_SELECTOR,
        vol.Required("options"): section(
            vol.Schema(
                {
                    vol.Required(CONF_HOT_TOLERANCE, default=DEFAULT_TOLERANCE): TEMPERATURE_SELECTOR,
                    vol.Required(CONF_COLD_TOLERANCE, default=DEFAULT_TOLERANCE): TEMPERATURE_SELECTOR,
                    vol.Optional(CONF_INITIAL_HVAC_MODE): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[mode.value for mode in (HVACMode.HEAT, HVACMode.COOL, HVACMode.OFF)]
                        )
                    )
                }
            ),
            options={"collapsed": True},
        ),
    }
)

PRESETS_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_AWAY_TEMP): TEMPERATURE_SELECTOR,
        vol.Optional(CONF_ECO_TEMP): TEMPERATURE_SELECTOR,
        vol.Optional(CONF_BOOST_TEMP): TEMPERATURE_SELECTOR,
        vol.Optional(CONF_COMFORT_TEMP): TEMPERATURE_SELECTOR,
        vol.Optional(CONF_HOME_TEMP): TEMPERATURE_SELECTOR,
        vol.Optional(CONF_SLEEP_TEMP): TEMPERATURE_SELECTOR,
        vol.Optional(CONF_ACTIVITY_TEMP): TEMPERATURE_SELECTOR,
        vol.Required(CONF_PRESET_SYNC_MODE, default=DEFAULT_PRESET_SYNC_MODE): selector.SelectSelector(
            selector.SelectSelectorConfig(options=["sync", "none"])
        ),
        vol.Required(CONF_BOOST_PID_OFF, default=False): selector.BooleanSelector()
    }
)

PID_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_KP, default=DEFAULT_KP): NUMBER_SELECTOR,
        vol.Required(CONF_KI, default=DEFAULT_KI): NUMBER_SELECTOR,
        vol.Required(CONF_KD, default=DEFAULT_KD): NUMBER_SELECTOR,
        vol.Optional(CONF_KE, default=DEFAULT_KE): NUMBER_SELECTOR,
        vol.Required(CONF_PWM, default=DEFAULT_PWM_DURATION): DURATION_SELECTOR,
        vol.Optional(CONF_KEEP_ALIVE, default=DEFAULT_KEEP_ALIVE): DURATION_SELECTOR,
        vol.Optional(CONF_SAMPLING_PERIOD, default=DEFAULT_SAMPLING_PERIOD_DURATION): DURATION_SELECTOR,
        vol.Optional("autotune_options"): section(
            vol.Schema(
                {
                    vol.Optional(CONF_AUTOTUNE, default=DEFAULT_AUTOTUNE): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=AUTOTUNE_OPTIONS)
                    ),
                    vol.Optional(CONF_NOISEBAND, default=DEFAULT_NOISEBAND): NUMBER_SELECTOR,
                    vol.Optional(CONF_LOOKBACK, default=DEFAULT_LOOKBACK_DURATION): DURATION_SELECTOR,
                }
            ),
            options={"collapsed": True},
        ),
    }
)

ADVANCED_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_OUTPUT_PRECISION, default=DEFAULT_OUTPUT_PRECISION): selector.NumberSelector(
            selector.NumberSelectorConfig(min=0, max=3, mode=selector.NumberSelectorMode.BOX)
        ),
        vol.Optional(CONF_OUTPUT_MIN, default=DEFAULT_OUTPUT_MIN): NUMBER_SELECTOR,
        vol.Optional(CONF_OUTPUT_MAX, default=DEFAULT_OUTPUT_MAX): NUMBER_SELECTOR,
        vol.Optional(CONF_OUT_CLAMP_LOW, default=DEFAULT_OUT_CLAMP_LOW): NUMBER_SELECTOR,
        vol.Optional(CONF_OUT_CLAMP_HIGH, default=DEFAULT_OUT_CLAMP_HIGH): NUMBER_SELECTOR,
        vol.Optional(
            CONF_MIN_CYCLE_DURATION, default=DEFAULT_MIN_CYCLE_DURATION_DURATION
        ): DURATION_SELECTOR,
        vol.Optional(CONF_MIN_OFF_CYCLE_DURATION): DURATION_SELECTOR,
        vol.Required("advanced_options"): section(
            vol.Schema(
                {
                    vol.Optional(CONF_MIN_CYCLE_DURATION_PID_OFF): DURATION_SELECTOR,
                    vol.Optional(CONF_MIN_OFF_CYCLE_DURATION_PID_OFF): DURATION_SELECTOR,
                    vol.Optional(CONF_SENSOR_STALL, default=DEFAULT_SENSOR_STALL_DURATION): DURATION_SELECTOR,
                    vol.Optional(CONF_OUTPUT_SAFETY, default=DEFAULT_OUTPUT_SAFETY): NUMBER_SELECTOR,
                    vol.Required(CONF_INVERT_HEATER, default=False): selector.BooleanSelector(),
                    vol.Required(CONF_FORCE_OFF_STATE, default=True): selector.BooleanSelector(),
                    vol.Optional(CONF_DEBUG, default=False): selector.BooleanSelector(),
                }
            ),
            options={"collapsed": True},
        ),
    }
)


async def _validate_config(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Validate user input."""
    min_temp = user_input.get(CONF_MIN_TEMP)
    max_temp = user_input.get(CONF_MAX_TEMP)
    target_temp = user_input.get(CONF_TARGET_TEMP)

    if min_temp is not None and max_temp is not None and min_temp >= max_temp:
        raise SchemaFlowError("min_max_temp")

    if target_temp is not None and min_temp is not None and target_temp < min_temp:
        raise SchemaFlowError("target_temp")

    if target_temp is not None and max_temp is not None and target_temp > max_temp:
        raise SchemaFlowError("target_temp")

    output_min = user_input.get(CONF_OUTPUT_MIN, DEFAULT_OUTPUT_MIN)
    output_max = user_input.get(CONF_OUTPUT_MAX, DEFAULT_OUTPUT_MAX)

    clamp_low = user_input.get(CONF_OUT_CLAMP_LOW, DEFAULT_OUT_CLAMP_LOW)
    clamp_high = user_input.get(CONF_OUT_CLAMP_HIGH, DEFAULT_OUT_CLAMP_HIGH)

    if not (output_min <= clamp_low < clamp_high <= output_max):
        raise SchemaFlowError("output_min_max")

    return user_input


STEPS_AFTER_INIT = {
    "temperature": SchemaFlowFormStep(
        TEMPERATURE_SCHEMA,
        validate_user_input=_validate_config,
        next_step="presets",
    ),
    "presets": SchemaFlowFormStep(
        PRESETS_SCHEMA,
        next_step="pid",
    ),
    "pid": SchemaFlowFormStep(
        PID_SCHEMA,
        next_step="advanced",
    ),
    "advanced": SchemaFlowFormStep(
        ADVANCED_SCHEMA,
        validate_user_input=_validate_config,
    ),
}

CONFIG_FLOW = {
    "user": SchemaFlowFormStep(
        BASIC_SCHEMA,
        next_step="temperature",
    ),
    **STEPS_AFTER_INIT,
}

OPTIONS_FLOW = {
    "init": SchemaFlowFormStep(
        BASIC_SCHEMA,
        next_step="temperature",
    ),
    **STEPS_AFTER_INIT,
}


class SmartThermostatConfigFlowHandler(SchemaConfigFlowHandler, domain=DOMAIN):
    """Handle a config or options flow for Smart Thermostat."""

    config_flow = CONFIG_FLOW
    options_flow = OPTIONS_FLOW
    options_flow_reloads = True

    def async_config_entry_title(self, options: Mapping[str, Any]) -> str:
        """Return config entry title."""
        return cast(str, options[CONF_NAME])