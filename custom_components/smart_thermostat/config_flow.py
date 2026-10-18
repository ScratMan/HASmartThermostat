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

from . import const
from .const import DOMAIN

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
CLAMP_SELECTOR = selector.TextSelector(
    selector.TextSelectorConfig(
        type=selector.TextSelectorType.TEXT,
    )
)

BASIC_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): selector.TextSelector(),
        vol.Required(const.CONF_HEATER): HEATER_SELECTOR,
        vol.Optional(const.CONF_COOLER): COOLER_SELECTOR,
        vol.Required(const.CONF_SENSOR): TEMPERATURE_SENSOR_SELECTOR,
        vol.Optional(const.CONF_OUTDOOR_SENSOR): TEMPERATURE_SENSOR_SELECTOR,
        vol.Required(const.CONF_AC_MODE, default=False): selector.BooleanSelector(),
    }
)

TEMPERATURE_SCHEMA = vol.Schema(
    {
        vol.Optional(const.CONF_MIN_TEMP, default=const.DEFAULT_MIN_TEMP): TEMPERATURE_SELECTOR,
        vol.Optional(const.CONF_MAX_TEMP, default=const.DEFAULT_MAX_TEMP): TEMPERATURE_SELECTOR,
        vol.Optional(
            const.CONF_TARGET_TEMP, default=const.DEFAULT_TARGET_TEMP
        ): TEMPERATURE_SELECTOR,
        vol.Required("options"): section(
            vol.Schema(
                {
                    vol.Required(
                        const.CONF_HOT_TOLERANCE, default=const.DEFAULT_TOLERANCE
                    ): TEMPERATURE_SELECTOR,
                    vol.Required(
                        const.CONF_COLD_TOLERANCE, default=const.DEFAULT_TOLERANCE
                    ): TEMPERATURE_SELECTOR,
                    vol.Optional(const.CONF_INITIAL_HVAC_MODE): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                mode.value
                                for mode in (HVACMode.HEAT, HVACMode.COOL, HVACMode.OFF)
                            ]
                        )
                    ),
                }
            ),
            options={"collapsed": True},
        ),
    }
)

PRESETS_SCHEMA = vol.Schema(
    {
        vol.Optional(const.CONF_AWAY_TEMP): TEMPERATURE_SELECTOR,
        vol.Optional(const.CONF_ECO_TEMP): TEMPERATURE_SELECTOR,
        vol.Optional(const.CONF_BOOST_TEMP): TEMPERATURE_SELECTOR,
        vol.Optional(const.CONF_COMFORT_TEMP): TEMPERATURE_SELECTOR,
        vol.Optional(const.CONF_HOME_TEMP): TEMPERATURE_SELECTOR,
        vol.Optional(const.CONF_SLEEP_TEMP): TEMPERATURE_SELECTOR,
        vol.Optional(const.CONF_ACTIVITY_TEMP): TEMPERATURE_SELECTOR,
        vol.Required(
            const.CONF_PRESET_SYNC_MODE, default=const.DEFAULT_PRESET_SYNC_MODE
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(options=["sync", "none"])
        ),
        vol.Required(const.CONF_BOOST_PID_OFF, default=False): selector.BooleanSelector(),
    }
)

PID_SCHEMA = vol.Schema(
    {
        vol.Required(const.CONF_KP, default=const.DEFAULT_KP): NUMBER_SELECTOR,
        vol.Required(const.CONF_KI, default=const.DEFAULT_KI): NUMBER_SELECTOR,
        vol.Required(const.CONF_KD, default=const.DEFAULT_KD): NUMBER_SELECTOR,
        vol.Optional(const.CONF_KE, default=const.DEFAULT_KE): NUMBER_SELECTOR,
        vol.Required(const.CONF_PWM, default=const.DEFAULT_PWM_DURATION): DURATION_SELECTOR,
        vol.Optional(const.CONF_KEEP_ALIVE, default=const.DEFAULT_KEEP_ALIVE): DURATION_SELECTOR,
        vol.Optional(
            const.CONF_SAMPLING_PERIOD, default=const.DEFAULT_SAMPLING_PERIOD_DURATION
        ): DURATION_SELECTOR,
        vol.Optional("autotune_options"): section(
            vol.Schema(
                {
                    vol.Optional(
                        const.CONF_AUTOTUNE, default=const.DEFAULT_AUTOTUNE
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=const.AUTOTUNE_OPTIONS)
                    ),
                    vol.Optional(
                        const.CONF_NOISEBAND, default=const.DEFAULT_NOISEBAND
                    ): NUMBER_SELECTOR,
                    vol.Optional(
                        const.CONF_LOOKBACK, default=const.DEFAULT_LOOKBACK_DURATION
                    ): DURATION_SELECTOR,
                }
            ),
            options={"collapsed": True},
        ),
    }
)

ADVANCED_SCHEMA = vol.Schema(
    {
        vol.Optional(
            const.CONF_OUTPUT_PRECISION, default=const.DEFAULT_OUTPUT_PRECISION
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0, max=3, mode=selector.NumberSelectorMode.BOX
            )
        ),
        vol.Optional(const.CONF_OUTPUT_MIN, default=const.DEFAULT_OUTPUT_MIN): NUMBER_SELECTOR,
        vol.Optional(const.CONF_OUTPUT_MAX, default=const.DEFAULT_OUTPUT_MAX): NUMBER_SELECTOR,
        vol.Optional(const.CONF_OUT_CLAMP_LOW): CLAMP_SELECTOR,
        vol.Optional(const.CONF_OUT_CLAMP_HIGH): CLAMP_SELECTOR,
        vol.Optional(
            const.CONF_MIN_CYCLE_DURATION, default=const.DEFAULT_MIN_CYCLE_DURATION_DURATION
        ): DURATION_SELECTOR,
        vol.Optional(const.CONF_MIN_OFF_CYCLE_DURATION): DURATION_SELECTOR,
        vol.Required("advanced_options"): section(
            vol.Schema(
                {
                    vol.Optional(const.CONF_MIN_CYCLE_DURATION_PID_OFF): DURATION_SELECTOR,
                    vol.Optional(
                        const.CONF_MIN_OFF_CYCLE_DURATION_PID_OFF
                    ): DURATION_SELECTOR,
                    vol.Optional(
                        const.CONF_SENSOR_STALL, default=const.DEFAULT_SENSOR_STALL_DURATION
                    ): DURATION_SELECTOR,
                    vol.Optional(
                        const.CONF_OUTPUT_SAFETY, default=const.DEFAULT_OUTPUT_SAFETY
                    ): NUMBER_SELECTOR,
                    vol.Required(
                        const.CONF_INVERT_HEATER, default=False
                    ): selector.BooleanSelector(),
                    vol.Required(
                        const.CONF_FORCE_OFF_STATE, default=True
                    ): selector.BooleanSelector(),
                    vol.Optional(const.CONF_DEBUG, default=False): selector.BooleanSelector(),
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
    min_temp = user_input.get(const.CONF_MIN_TEMP)
    max_temp = user_input.get(const.CONF_MAX_TEMP)
    target_temp = user_input.get(const.CONF_TARGET_TEMP)

    if min_temp is not None and max_temp is not None and min_temp >= max_temp:
        raise SchemaFlowError("min_max_temp")

    if target_temp is not None and min_temp is not None and target_temp < min_temp:
        raise SchemaFlowError("target_temp")

    if target_temp is not None and max_temp is not None and target_temp > max_temp:
        raise SchemaFlowError("target_temp")

    output_min = user_input.get(const.CONF_OUTPUT_MIN, const.DEFAULT_OUTPUT_MIN)
    output_max = user_input.get(const.CONF_OUTPUT_MAX, const.DEFAULT_OUTPUT_MAX)

    clamp_low = user_input.get(const.CONF_OUT_CLAMP_LOW, output_min)
    clamp_high = user_input.get(const.CONF_OUT_CLAMP_HIGH, output_max)

    if not (output_min < output_max):
        raise SchemaFlowError("output_min_max")
    if isinstance(clamp_low, (int, float)) and isinstance(clamp_high, (int, float)):
        if not (output_min <= clamp_low < clamp_high <= output_max):
            raise SchemaFlowError("output_min_max")

    for clamp_key in (const.CONF_OUT_CLAMP_LOW, const.CONF_OUT_CLAMP_HIGH):
        val = user_input.get(clamp_key)
        if val is not None and isinstance(val, str):
            try:
                # Convert to float if it's a number
                user_input[clamp_key] = float(val)
            except ValueError:
                # It's an entity ID, so we don't need to validate it here. It will be validated when the entity is resolved.
                pass

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
