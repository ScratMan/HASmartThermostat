"""Adds support for smart (PID) thermostat units.
For more details about this platform, please refer to the documentation at
https://github.com/ScratMan/HASmartThermostat"""

import asyncio
import logging
import time
from abc import ABC
from datetime import datetime, timedelta
from typing import Optional

import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.helpers import condition, entity_platform, discovery
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_TEMPERATURE,
    CONF_NAME,
    CONF_UNIQUE_ID,
    EVENT_HOMEASSISTANT_START,
    PRECISION_HALVES,
    PRECISION_TENTHS,
    PRECISION_WHOLE,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_ON,
    STATE_OFF,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.components.number.const import (
    ATTR_VALUE,
    SERVICE_SET_VALUE,
    DOMAIN as NUMBER_DOMAIN
)
from homeassistant.components.input_number import DOMAIN as INPUT_NUMBER_DOMAIN
from homeassistant.components.light import (DOMAIN as LIGHT_DOMAIN, SERVICE_TURN_ON as SERVICE_TURN_LIGHT_ON,
                                            ATTR_BRIGHTNESS_PCT)
from homeassistant.components.valve import (DOMAIN as VALVE_DOMAIN, SERVICE_SET_VALVE_POSITION, ATTR_POSITION)
from homeassistant.core import DOMAIN as HA_DOMAIN, CoreState, Event, EventStateChangedData, callback
from homeassistant.util import slugify
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.exceptions import HomeAssistantError, ServiceNotFound

from .adaptive.physics import calculate_thermal_time_constant, calculate_initial_pid, calculate_initial_ke
from .adaptive.night_setback import NightSetback
from .adaptive.solar_recovery import SolarRecovery
from .adaptive.sun_position import SunPositionCalculator
from .adaptive.contact_sensors import ContactSensorHandler, ContactAction
from .adaptive.ke_learning import KeLearner

from homeassistant.components.climate import PLATFORM_SCHEMA, ClimateEntity, ClimateEntityFeature
from homeassistant.components.climate import (
    ATTR_PRESET_MODE,
    HVACMode,
    HVACAction,
    PRESET_AWAY,
    PRESET_NONE,
    PRESET_ECO,
    PRESET_BOOST,
    PRESET_COMFORT,
    PRESET_HOME,
    PRESET_SLEEP,
    PRESET_ACTIVITY,
)

from . import DOMAIN, PLATFORMS
from . import const
from . import pid_controller
from .adaptive.learning import AdaptiveLearner, ThermalRateLearner
from .managers import ControlOutputManager, HeaterController, KeController, NightSetbackController, PIDTuningManager, StateRestorer, TemperatureManager, CycleTrackerManager
from .managers.state_attributes import build_state_attributes

_LOGGER = logging.getLogger(__name__)


PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(const.CONF_HEATER): cv.entity_ids,
        vol.Optional(const.CONF_COOLER): cv.entity_ids,
        vol.Optional(const.CONF_DEMAND_SWITCH): cv.entity_ids,
        vol.Required(const.CONF_INVERT_HEATER, default=False): cv.boolean,
        vol.Required(const.CONF_SENSOR): cv.entity_id,
        vol.Optional(const.CONF_FORCE_OFF_STATE, default=True): cv.boolean,
        vol.Optional(const.CONF_MAX_TEMP): vol.Coerce(float),
        vol.Optional(const.CONF_MIN_TEMP): vol.Coerce(float),
        vol.Optional(CONF_NAME, default=const.DEFAULT_NAME): cv.string,
        vol.Optional(CONF_UNIQUE_ID, default='none'): cv.string,
        vol.Optional(const.CONF_TARGET_TEMP): vol.Coerce(float),
        vol.Optional(const.CONF_HOT_TOLERANCE, default=const.DEFAULT_TOLERANCE): vol.Coerce(float),
        vol.Optional(const.CONF_COLD_TOLERANCE, default=const.DEFAULT_TOLERANCE): vol.Coerce(
            float),
        vol.Optional(const.CONF_MIN_CYCLE_DURATION, default=const.DEFAULT_MIN_CYCLE_DURATION):
            vol.All(cv.time_period, cv.positive_timedelta),
        vol.Optional(const.CONF_MIN_OFF_CYCLE_DURATION): vol.All(
            cv.time_period, cv.positive_timedelta),
        vol.Optional(const.CONF_MIN_CYCLE_DURATION_PID_OFF): vol.All(
            cv.time_period, cv.positive_timedelta),
        vol.Optional(const.CONF_MIN_OFF_CYCLE_DURATION_PID_OFF): vol.All(
            cv.time_period, cv.positive_timedelta),
        vol.Optional(const.CONF_CONTROL_INTERVAL): vol.All(cv.time_period, cv.positive_timedelta),
        vol.Optional(const.CONF_SAMPLING_PERIOD, default=const.DEFAULT_SAMPLING_PERIOD): vol.All(
            cv.time_period, cv.positive_timedelta),
        vol.Optional(const.CONF_SENSOR_STALL, default=const.DEFAULT_SENSOR_STALL): vol.All(
            cv.time_period, cv.positive_timedelta),
        vol.Optional(const.CONF_OUTPUT_SAFETY, default=const.DEFAULT_OUTPUT_SAFETY): vol.Coerce(
            float),
        vol.Optional(const.CONF_INITIAL_HVAC_MODE): vol.In(
            [HVACMode.COOL, HVACMode.HEAT, HVACMode.OFF]
        ),
        vol.Optional(const.CONF_PRECISION): vol.In(
            [PRECISION_TENTHS, PRECISION_HALVES, PRECISION_WHOLE]
        ),
        vol.Optional(const.CONF_TARGET_TEMP_STEP): vol.In(
            [PRECISION_TENTHS, PRECISION_HALVES, PRECISION_WHOLE]
        ),
        vol.Optional(const.CONF_OUTPUT_PRECISION, default=const.DEFAULT_OUTPUT_PRECISION): vol.Coerce(int),
        vol.Optional(const.CONF_OUTPUT_MIN, default=const.DEFAULT_OUTPUT_MIN): vol.Coerce(float),
        vol.Optional(const.CONF_OUTPUT_MAX, default=const.DEFAULT_OUTPUT_MAX): vol.Coerce(float),
        vol.Optional(const.CONF_OUT_CLAMP_LOW, default=const.DEFAULT_OUT_CLAMP_LOW): vol.Coerce(float),
        vol.Optional(const.CONF_OUT_CLAMP_HIGH, default=const.DEFAULT_OUT_CLAMP_HIGH): vol.Coerce(float),
        vol.Optional(const.CONF_PWM, default=const.DEFAULT_PWM): vol.All(
            cv.time_period, cv.positive_timedelta
        ),
        # Adaptive learning options
        vol.Optional(const.CONF_HEATING_TYPE): vol.In(const.VALID_HEATING_TYPES),
        vol.Optional(const.CONF_AREA_M2): vol.Coerce(float),
        vol.Optional(const.CONF_CEILING_HEIGHT, default=const.DEFAULT_CEILING_HEIGHT): vol.Coerce(float),
        vol.Optional(const.CONF_WINDOW_AREA_M2): vol.Coerce(float),
        vol.Optional(const.CONF_WINDOW_ORIENTATION): vol.In(const.VALID_WINDOW_ORIENTATIONS),
        vol.Optional(const.CONF_WINDOW_RATING): cv.string,
        # Zone linking
        vol.Optional(const.CONF_LINKED_ZONES): cv.entity_ids,
        vol.Optional(const.CONF_LINK_DELAY_MINUTES, default=const.DEFAULT_LINK_DELAY_MINUTES): vol.Coerce(int),
        # Contact sensors
        vol.Optional(const.CONF_CONTACT_SENSORS): cv.entity_ids,
        vol.Optional(const.CONF_CONTACT_ACTION, default=const.CONTACT_ACTION_PAUSE): vol.In(const.VALID_CONTACT_ACTIONS),
        vol.Optional(const.CONF_CONTACT_DELAY, default=const.DEFAULT_CONTACT_DELAY): vol.Coerce(int),
        # Night setback
        vol.Optional(const.CONF_NIGHT_SETBACK): vol.Schema({
            vol.Optional(const.CONF_NIGHT_SETBACK_START): cv.string,
            vol.Optional(const.CONF_NIGHT_SETBACK_END): cv.string,
            vol.Optional(const.CONF_NIGHT_SETBACK_DELTA, default=const.DEFAULT_NIGHT_SETBACK_DELTA): vol.Coerce(float),
            vol.Optional(const.CONF_NIGHT_SETBACK_RECOVERY_DEADLINE): cv.string,
            vol.Optional(const.CONF_NIGHT_SETBACK_SOLAR_RECOVERY): cv.boolean,
            vol.Optional(const.CONF_MIN_EFFECTIVE_ELEVATION, default=const.DEFAULT_MIN_EFFECTIVE_ELEVATION): vol.Coerce(float),
        }),
    }
)


def validate_pwm_compatibility(config):
    """Validate that PWM mode is not used with climate entities.

    PWM (Pulse Width Modulation) creates nested control loops when used with
    climate entities, which have their own internal PID controllers. This can
    cause instability and erratic behavior.

    Args:
        config: Platform configuration dictionary

    Raises:
        vol.Invalid: If PWM is configured with a climate entity

    Returns:
        config: Validated configuration (unchanged if valid)
    """
    pwm = config.get(const.CONF_PWM)
    pwm_seconds = pwm.seconds if pwm else 0

    # Only validate if PWM is actually enabled (> 0 seconds)
    if pwm_seconds == 0:
        return config

    # Check heater entity
    heater_entities = config.get(const.CONF_HEATER, [])
    for entity_id in heater_entities:
        if entity_id.startswith("climate."):
            raise vol.Invalid(
                f"PWM mode cannot be used with climate entity '{entity_id}'. "
                f"Climate entities have their own PID controllers, creating nested control loops. "
                f"Solutions: (1) Set pwm to '00:00:00' for valve mode, or (2) Use a switch/light entity instead."
            )

    # Check cooler entity
    cooler_entities = config.get(const.CONF_COOLER, [])
    for entity_id in cooler_entities:
        if entity_id.startswith("climate."):
            raise vol.Invalid(
                f"PWM mode cannot be used with climate entity '{entity_id}'. "
                f"Climate entities have their own PID controllers, creating nested control loops. "
                f"Solutions: (1) Set pwm to '00:00:00' for valve mode, or (2) Use a switch/light entity instead."
            )

    return config


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up the generic thermostat platform."""
    platform = entity_platform.current_platform.get()
    assert platform

    # Get name and create zone_id
    name = config.get(CONF_NAME)
    zone_id = slugify(name)

    # Validate that at least one output entity is configured
    heater = config.get(const.CONF_HEATER)
    cooler = config.get(const.CONF_COOLER)
    demand_switch = config.get(const.CONF_DEMAND_SWITCH)
    if not heater and not cooler and not demand_switch:
        _LOGGER.error(
            "%s: At least one of heater, cooler, or demand_switch must be configured",
            name
        )
        return

    # Validate PWM compatibility with entity types
    try:
        validate_pwm_compatibility(config)
    except vol.Invalid as ex:
        _LOGGER.error("%s: Configuration error - %s", name, ex)
        raise

    parameters = {
        'name': name,
        'unique_id': config.get(CONF_UNIQUE_ID),
        'heater_entity_id': config.get(const.CONF_HEATER),
        'cooler_entity_id': config.get(const.CONF_COOLER),
        'demand_switch_entity_id': config.get(const.CONF_DEMAND_SWITCH),
        'invert_heater': config.get(const.CONF_INVERT_HEATER),
        'sensor_entity_id': config.get(const.CONF_SENSOR),
        'ext_sensor_entity_id': hass.data.get(DOMAIN, {}).get("outdoor_sensor"),
        'min_temp': config.get(const.CONF_MIN_TEMP),
        'max_temp': config.get(const.CONF_MAX_TEMP),
        'target_temp': config.get(const.CONF_TARGET_TEMP),
        'hot_tolerance': config.get(const.CONF_HOT_TOLERANCE),
        'cold_tolerance': config.get(const.CONF_COLD_TOLERANCE),
        # Derive ac_mode from cooler presence (zone or controller level)
        'ac_mode': bool(cooler) or bool(hass.data.get(DOMAIN, {}).get("main_cooler_switch")),
        'force_off_state': config.get(const.CONF_FORCE_OFF_STATE),
        'min_cycle_duration': config.get(const.CONF_MIN_CYCLE_DURATION),
        'min_off_cycle_duration': config.get(const.CONF_MIN_OFF_CYCLE_DURATION),
        'min_cycle_duration_pid_off': config.get(const.CONF_MIN_CYCLE_DURATION_PID_OFF),
        'min_off_cycle_duration_pid_off': config.get(const.CONF_MIN_OFF_CYCLE_DURATION_PID_OFF),
        'control_interval': config.get(const.CONF_CONTROL_INTERVAL),
        'sampling_period': config.get(const.CONF_SAMPLING_PERIOD),
        'sensor_stall': config.get(const.CONF_SENSOR_STALL),
        'output_safety': config.get(const.CONF_OUTPUT_SAFETY),
        'initial_hvac_mode': config.get(const.CONF_INITIAL_HVAC_MODE),
        'preset_sync_mode': hass.data.get(DOMAIN, {}).get("preset_sync_mode"),
        'away_temp': hass.data.get(DOMAIN, {}).get("away_temp"),
        'eco_temp': hass.data.get(DOMAIN, {}).get("eco_temp"),
        'boost_temp': hass.data.get(DOMAIN, {}).get("boost_temp"),
        'comfort_temp': hass.data.get(DOMAIN, {}).get("comfort_temp"),
        'home_temp': hass.data.get(DOMAIN, {}).get("home_temp"),
        'activity_temp': hass.data.get(DOMAIN, {}).get("activity_temp"),
        'precision': config.get(const.CONF_PRECISION),
        'target_temp_step': config.get(const.CONF_TARGET_TEMP_STEP),
        'unit': hass.config.units.temperature_unit,
        'output_precision': config.get(const.CONF_OUTPUT_PRECISION),
        'output_min': config.get(const.CONF_OUTPUT_MIN),
        'output_max': config.get(const.CONF_OUTPUT_MAX),
        'output_clamp_low': config.get(const.CONF_OUT_CLAMP_LOW),
        'output_clamp_high': config.get(const.CONF_OUT_CLAMP_HIGH),
        'pwm': config.get(const.CONF_PWM),
        'boost_pid_off': hass.data.get(DOMAIN, {}).get("boost_pid_off"),
        # New adaptive learning parameters
        'zone_id': zone_id,
        'heating_type': config.get(const.CONF_HEATING_TYPE),
        'area_m2': config.get(const.CONF_AREA_M2),
        'ceiling_height': config.get(const.CONF_CEILING_HEIGHT),
        'window_area_m2': config.get(const.CONF_WINDOW_AREA_M2),
        'window_orientation': config.get(const.CONF_WINDOW_ORIENTATION),
        # Window rating: use zone-level config, fall back to controller default
        'window_rating': config.get(const.CONF_WINDOW_RATING) or hass.data.get(DOMAIN, {}).get("window_rating", const.DEFAULT_WINDOW_RATING),
        'linked_zones': config.get(const.CONF_LINKED_ZONES),
        'link_delay_minutes': config.get(const.CONF_LINK_DELAY_MINUTES),
        'contact_sensors': config.get(const.CONF_CONTACT_SENSORS),
        'contact_action': config.get(const.CONF_CONTACT_ACTION),
        'contact_delay': config.get(const.CONF_CONTACT_DELAY),
        'night_setback_config': config.get(const.CONF_NIGHT_SETBACK),
    }

    thermostat = AdaptiveThermostat(**parameters)

    # Register zone with coordinator BEFORE adding entity
    # This ensures zone_data is available when async_added_to_hass runs
    coordinator = hass.data.get(DOMAIN, {}).get("coordinator")
    if coordinator:
        zone_data = {
            "climate_entity_id": f"climate.{zone_id}",
            "zone_name": name,
            "area_m2": config.get(const.CONF_AREA_M2, 0),
            "heating_type": config.get(const.CONF_HEATING_TYPE),
            "learning_enabled": True,  # Always enabled, vacation mode can toggle
            "adaptive_learner": AdaptiveLearner(),
            "linked_zones": config.get(const.CONF_LINKED_ZONES, []),
        }
        coordinator.register_zone(zone_id, zone_data)
        _LOGGER.info("Registered zone %s with coordinator", zone_id)

    async_add_entities([thermostat])

    # Trigger sensor platform discovery for this zone (after entity is added)
    if coordinator:
        hass.async_create_task(
            discovery.async_load_platform(
                hass,
                "sensor",
                DOMAIN,
                {
                    "zone_id": zone_id,
                    "zone_name": name,
                    "climate_entity_id": f"climate.{zone_id}",
                },
                config,
            )
        )

    platform.async_register_entity_service(  # type: ignore
        "reset_pid_to_physics",
        {},
        "async_reset_pid_to_physics",
    )
    platform.async_register_entity_service(  # type: ignore
        "apply_adaptive_pid",
        {},
        "async_apply_adaptive_pid",
    )
    platform.async_register_entity_service(  # type: ignore
        "apply_adaptive_ke",
        {},
        "async_apply_adaptive_ke",
    )


class AdaptiveThermostat(ClimateEntity, RestoreEntity, ABC):
    """Representation of an Adaptive Thermostat device."""

    def __init__(self, **kwargs):
        """Initialize the thermostat."""
        self._name = kwargs.get('name')
        self._unique_id = kwargs.get('unique_id')
        self._heater_entity_id = kwargs.get('heater_entity_id')
        self._cooler_entity_id = kwargs.get('cooler_entity_id', None)
        self._demand_switch_entity_id = kwargs.get('demand_switch_entity_id', None)
        self._heater_polarity_invert = kwargs.get('invert_heater')
        self._sensor_entity_id = kwargs.get('sensor_entity_id')
        self._ext_sensor_entity_id = kwargs.get('ext_sensor_entity_id')
        if self._unique_id == 'none':
            self._unique_id = slugify(f"{DOMAIN}_{self._name}_{self._heater_entity_id}")
        self._ac_mode = kwargs.get('ac_mode', False)
        self._force_off_state = kwargs.get('force_off_state', True)
        self._control_interval = kwargs.get('control_interval')
        self._sampling_period = kwargs.get('sampling_period').seconds
        self._sensor_stall = kwargs.get('sensor_stall').seconds
        self._output_safety = kwargs.get('output_safety')
        self._hvac_mode = kwargs.get('initial_hvac_mode', None)
        self._saved_target_temp = kwargs.get('target_temp', None) or kwargs.get('away_temp', None)
        self._temp_precision = kwargs.get('precision')
        self._target_temperature_step = kwargs.get('target_temp_step')
        self._last_heat_cycle_time = None  # None means use device's last_changed time
        self._min_on_cycle_duration_pid_on = kwargs.get('min_cycle_duration')
        self._min_off_cycle_duration_pid_on = kwargs.get('min_off_cycle_duration')
        self._min_on_cycle_duration_pid_off = kwargs.get('min_cycle_duration_pid_off')
        self._min_off_cycle_duration_pid_off = kwargs.get('min_off_cycle_duration_pid_off')
        if self._min_off_cycle_duration_pid_on is None:
            self._min_off_cycle_duration_pid_on = self._min_on_cycle_duration_pid_on
        if self._min_on_cycle_duration_pid_off is None:
            self._min_on_cycle_duration_pid_off = self._min_on_cycle_duration_pid_on
        if self._min_off_cycle_duration_pid_off is None:
            self._min_off_cycle_duration_pid_off = self._min_on_cycle_duration_pid_off
        self._active = False
        self._trigger_source = None
        self._current_temp = None
        self._cur_temp_time = None
        self._previous_temp = None
        self._previous_temp_time = None
        self._ext_temp = None
        self._temp_lock = asyncio.Lock()
        self._min_temp = kwargs.get('min_temp')
        self._max_temp = kwargs.get('max_temp')
        self._target_temp = kwargs.get('target_temp')
        self._unit = kwargs.get('unit')
        self._support_flags = ClimateEntityFeature.TARGET_TEMPERATURE
        self._support_flags |= ClimateEntityFeature.TURN_OFF
        self._support_flags |= ClimateEntityFeature.TURN_ON
        self._enable_turn_on_off_backwards_compatibility = False  # Remove after deprecation period
        self._attr_preset_mode = 'none'
        self._away_temp = kwargs.get('away_temp')
        self._eco_temp = kwargs.get('eco_temp')
        self._boost_temp = kwargs.get('boost_temp')
        self._comfort_temp = kwargs.get('comfort_temp')
        self._home_temp = kwargs.get('home_temp')
        self._sleep_temp = kwargs.get('sleep_temp')
        self._activity_temp = kwargs.get('activity_temp')
        self._preset_sync_mode = kwargs.get('preset_sync_mode')
        if True in [temp is not None for temp in [self._away_temp,
                                                  self._eco_temp,
                                                  self._boost_temp,
                                                  self._comfort_temp,
                                                  self._home_temp,
                                                  self._sleep_temp,
                                                  self._activity_temp]]:
            self._support_flags |= ClimateEntityFeature.PRESET_MODE

        self._output_precision = kwargs.get('output_precision')
        self._output_min = kwargs.get('output_min')
        self._output_max = kwargs.get('output_max')
        self._output_clamp_low = kwargs.get('output_clamp_low')
        self._output_clamp_high = kwargs.get('output_clamp_high')
        self._difference = self._output_max - self._output_min
        if self._ac_mode:
            self._attr_hvac_modes = [HVACMode.COOL, HVACMode.HEAT, HVACMode.OFF]
            self._min_out = -self._output_clamp_high
            self._max_out = -self._output_clamp_low
        else:
            self._attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
            self._min_out = self._output_clamp_low
            self._max_out = self._output_clamp_high
        # Zone properties for physics-based initialization
        self._zone_id = kwargs.get('zone_id')
        self._heating_type = kwargs.get('heating_type', 'floor_hydronic')
        self._area_m2 = kwargs.get('area_m2')
        self._ceiling_height = kwargs.get('ceiling_height', 2.5)
        self._window_area_m2 = kwargs.get('window_area_m2')
        self._window_rating = kwargs.get('window_rating', 'hr++')
        self._window_orientation = kwargs.get('window_orientation')

        # Night setback
        self._night_setback = None
        self._night_setback_config = None
        self._solar_recovery = None
        self._night_setback_was_active = None  # Track previous state for transition detection
        self._learning_grace_until = None  # Pause learning until this time after transitions
        night_setback_config = kwargs.get('night_setback_config')
        _LOGGER.debug("%s: night_setback_config from kwargs: %s", self._name, night_setback_config)
        if night_setback_config:
            start = night_setback_config.get(const.CONF_NIGHT_SETBACK_START)
            end = night_setback_config.get(const.CONF_NIGHT_SETBACK_END)
            _LOGGER.info("%s: Night setback configured: start=%s, end=%s", self._name, start, end)
            if start:
                # Store config for dynamic end time calculation
                # Auto-enable solar_recovery if window_orientation is set (can be explicitly disabled)
                solar_recovery_enabled = night_setback_config.get(
                    const.CONF_NIGHT_SETBACK_SOLAR_RECOVERY,
                    bool(self._window_orientation)  # Auto-enable if orientation set
                )
                self._night_setback_config = {
                    'start': start,
                    'end': end,  # May be None - will use dynamic calculation
                    'delta': night_setback_config.get(
                        const.CONF_NIGHT_SETBACK_DELTA,
                        const.DEFAULT_NIGHT_SETBACK_DELTA
                    ),
                    'recovery_deadline': night_setback_config.get(const.CONF_NIGHT_SETBACK_RECOVERY_DEADLINE),
                    'solar_recovery': solar_recovery_enabled,
                    'min_effective_elevation': night_setback_config.get(
                        const.CONF_MIN_EFFECTIVE_ELEVATION,
                        const.DEFAULT_MIN_EFFECTIVE_ELEVATION
                    ),
                }
                # Only create NightSetback if end is explicitly configured
                if end:
                    self._night_setback = NightSetback(
                        start_time=start,
                        end_time=end,
                        setback_delta=self._night_setback_config['delta'],
                        recovery_deadline=self._night_setback_config['recovery_deadline'],
                    )

                # Solar recovery (uses window_orientation from zone config)
                # Works with both explicit and dynamic end times
                # Sun position calculator is set in async_added_to_hass
                # Automatically enabled if window_orientation is set
                if solar_recovery_enabled and self._window_orientation:
                    # Use explicit end time or default to 07:00 for static fallback
                    # (dynamic sun position calculator will override this)
                    base_recovery = end if end else "07:00"
                    self._solar_recovery = SolarRecovery(
                        window_orientation=self._window_orientation,
                        base_recovery_time=base_recovery,
                        recovery_deadline=self._night_setback_config['recovery_deadline'],
                        min_effective_elevation=self._night_setback_config['min_effective_elevation'],
                    )

        # Zone linking for thermally connected zones
        self._linked_zones = kwargs.get('linked_zones', [])
        self._link_delay_minutes = kwargs.get('link_delay_minutes', const.DEFAULT_LINK_DELAY_MINUTES)
        self._zone_linker = None  # Will be set in async_added_to_hass
        self._is_heating = False  # Track heating state for zone linking

        # Contact sensors (window/door open detection)
        self._contact_sensor_handler = None
        contact_sensors = kwargs.get('contact_sensors')
        if contact_sensors:
            contact_action = kwargs.get('contact_action', 'pause')
            contact_delay = kwargs.get('contact_delay', 300)  # Default 5 minutes
            # Convert delay to seconds if it's a timedelta-like value
            if hasattr(contact_delay, 'total_seconds'):
                contact_delay = int(contact_delay.total_seconds())
            action_enum = ContactAction.PAUSE if contact_action == 'pause' else ContactAction.FROST_PROTECTION
            self._contact_sensor_handler = ContactSensorHandler(
                contact_sensors=contact_sensors,
                contact_delay_seconds=contact_delay,
                action=action_enum,
            )
            _LOGGER.info(
                "%s: Contact sensors configured: %s (action=%s, delay=%ds)",
                self._name, contact_sensors, contact_action, contact_delay
            )

        # Heater controller (initialized in async_added_to_hass when hass is available)
        self._heater_controller: HeaterController | None = None

        # Night setback controller (initialized in async_added_to_hass when hass is available)
        self._night_setback_controller: NightSetbackController | None = None

        # Temperature manager (initialized in async_added_to_hass when hass is available)
        self._temperature_manager: TemperatureManager | None = None

        # Ke learning controller (initialized in async_added_to_hass when hass is available)
        self._ke_controller: KeController | None = None

        # PID tuning manager (initialized in async_added_to_hass when hass is available)
        self._pid_tuning_manager: PIDTuningManager | None = None

        # Cycle tracker for adaptive learning (initialized in async_added_to_hass when hass is available)
        self._cycle_tracker: CycleTrackerManager | None = None

        # Control output manager (initialized in async_added_to_hass when hass is available)
        self._control_output_manager: ControlOutputManager | None = None

        # Heater control failure tracking (managed by HeaterController when available)
        self._heater_control_failed = False
        self._last_heater_error: str | None = None

        # Calculate PID values from physics (adaptive learning will refine them)
        # Get energy rating from controller domain config
        # Note: hass is not available during __init__, it will be set in async_added_to_hass
        self._energy_rating = None

        if self._area_m2:
            volume_m3 = self._area_m2 * self._ceiling_height
            tau = calculate_thermal_time_constant(
                volume_m3=volume_m3,
                window_area_m2=self._window_area_m2,
                floor_area_m2=self._area_m2,
                window_rating=self._window_rating,
            )
            self._kp, self._ki, self._kd = calculate_initial_pid(tau, self._heating_type)
            _LOGGER.info("%s: Physics-based PID init (tau=%.2f, type=%s, window=%s): Kp=%.4f, Ki=%.5f, Kd=%.3f",
                         self.unique_id, tau, self._heating_type, self._window_rating, self._kp, self._ki, self._kd)
        else:
            # Fallback defaults if no zone properties
            self._kp = 0.5
            self._ki = 0.01
            self._kd = 5.0
            _LOGGER.warning("%s: No area_m2 configured, using default PID values", self.unique_id)

        # Calculate initial Ke from physics (adaptive learning will refine it)
        # Note: energy_rating may not be available during __init__ since hass isn't fully set up
        # It will be recalculated in async_added_to_hass if needed
        self._ke = const.DEFAULT_KE

        # Initialize KeLearner (will be configured properly in async_added_to_hass)
        self._ke_learner: Optional[KeLearner] = None

        self._pwm = kwargs.get('pwm').seconds
        self._p = self._i = self._d = self._e = self._dt = 0
        self._control_output = self._output_min
        self._force_on = False
        self._force_off = False
        self._boost_pid_off = kwargs.get('boost_pid_off')
        self._cold_tolerance = abs(kwargs.get('cold_tolerance'))
        self._hot_tolerance = abs(kwargs.get('hot_tolerance'))
        self._time_changed = time.time()
        self._last_sensor_update = time.time()
        self._last_ext_sensor_update = time.time()
        _LOGGER.info("%s: Active PID values - Kp=%.4f, Ki=%.5f, Kd=%.3f, Ke=%s",
                     self.unique_id, self._kp, self._ki, self._kd, self._ke or 0)
        self._pid_controller = pid_controller.PID(self._kp, self._ki, self._kd, self._ke,
                                                  self._min_out, self._max_out,
                                                  self._sampling_period, self._cold_tolerance,
                                                  self._hot_tolerance)
        self._pid_controller.mode = "AUTO"

    async def async_added_to_hass(self):
        """Run when entity about to be added."""
        await super().async_added_to_hass()

        # Initialize heater controller now that hass is available
        self._heater_controller = HeaterController(
            hass=self.hass,
            thermostat=self,
            heater_entity_id=self._heater_entity_id,
            cooler_entity_id=self._cooler_entity_id,
            demand_switch_entity_id=self._demand_switch_entity_id,
            heater_polarity_invert=self._heater_polarity_invert,
            pwm=self._pwm,
            difference=self._difference,
            min_on_cycle_duration=self._min_on_cycle_duration.seconds,
            min_off_cycle_duration=self._min_off_cycle_duration.seconds,
        )

        # Initialize night setback controller now that hass is available
        if self._night_setback or self._night_setback_config:
            self._night_setback_controller = NightSetbackController(
                hass=self.hass,
                entity_id=self.entity_id,
                night_setback=self._night_setback,
                night_setback_config=self._night_setback_config,
                solar_recovery=self._solar_recovery,
                window_orientation=self._window_orientation,
                get_target_temp=lambda: self._target_temp,
                get_current_temp=lambda: self._current_temp,
            )
            _LOGGER.info(
                "%s: Night setback controller initialized",
                self.entity_id
            )

        # Initialize temperature manager
        self._temperature_manager = TemperatureManager(
            thermostat=self,
            away_temp=self._away_temp,
            eco_temp=self._eco_temp,
            boost_temp=self._boost_temp,
            comfort_temp=self._comfort_temp,
            home_temp=self._home_temp,
            sleep_temp=self._sleep_temp,
            activity_temp=self._activity_temp,
            preset_sync_mode=self._preset_sync_mode,
            min_temp=self.min_temp,
            max_temp=self.max_temp,
            boost_pid_off=self._boost_pid_off or False,
            get_target_temp=lambda: self._target_temp,
            set_target_temp=self._set_target_temp,
            get_current_temp=lambda: self._current_temp,
            set_force_on=self._set_force_on,
            set_force_off=self._set_force_off,
            async_set_pid_mode=self._async_set_pid_mode_internal,
            async_control_heating=self._async_control_heating_internal,
        )
        # Sync initial preset mode state
        self._temperature_manager.restore_state(
            preset_mode=self._attr_preset_mode,
            saved_target_temp=self._saved_target_temp,
        )
        _LOGGER.info(
            "%s: Temperature manager initialized",
            self.entity_id
        )

        # Configure zone linking if linked zones are defined
        if self._linked_zones:
            zone_linker = self.hass.data.get(DOMAIN, {}).get("zone_linker")
            if zone_linker:
                self._zone_linker = zone_linker
                zone_linker.configure_linked_zones(self._unique_id, self._linked_zones)
                _LOGGER.info(
                    "%s: Zone linking configured with %s (delay=%d min)",
                    self.entity_id, self._linked_zones, self._link_delay_minutes
                )

        # Initialize sun position calculator for dynamic solar recovery
        if self._solar_recovery:
            sun_calculator = SunPositionCalculator.from_hass(self.hass)
            if sun_calculator:
                self._solar_recovery.set_sun_calculator(sun_calculator)
                _LOGGER.info(
                    "%s: Dynamic solar recovery enabled using location (%.2f, %.2f)",
                    self.entity_id,
                    self.hass.config.latitude,
                    self.hass.config.longitude,
                )
            else:
                _LOGGER.warning(
                    "%s: Could not initialize sun position calculator, "
                    "using static orientation offsets for solar recovery",
                    self.entity_id,
                )

        # Initialize Ke learning - start with Ke=0, let PID stabilize first
        # Physics-based Ke is stored in KeLearner as reference for later application
        # Get energy rating now that hass is available
        energy_rating = self.hass.data.get(DOMAIN, {}).get("house_energy_rating")
        if self._ext_sensor_entity_id:
            # Calculate physics-based Ke as reference (not applied yet)
            initial_ke = calculate_initial_ke(
                energy_rating=energy_rating,
                window_area_m2=self._window_area_m2,
                floor_area_m2=self._area_m2,
                window_rating=self._window_rating,
                heating_type=self._heating_type,
            )
            # Start with Ke=0 - don't apply until PID reaches equilibrium
            self._ke = 0.0
            self._ke_learner = KeLearner(initial_ke=initial_ke)
            # PID controller starts without Ke compensation
            self._pid_controller.set_pid_param(ke=0.0)
            _LOGGER.info(
                "%s: Ke learning initialized (physics reference Ke=%.2f, "
                "starting with Ke=0 until PID stabilizes) "
                "(energy_rating=%s, heating_type=%s)",
                self.entity_id, initial_ke, energy_rating or "default", self._heating_type
            )
        else:
            _LOGGER.debug(
                "%s: Ke learning disabled - no outdoor sensor configured",
                self.entity_id
            )

        # Initialize Ke controller (always, even without outdoor sensor)
        self._ke_controller = KeController(
            thermostat=self,
            ke_learner=self._ke_learner,
            get_hvac_mode=lambda: self._hvac_mode,
            get_current_temp=lambda: self._current_temp,
            get_target_temp=lambda: self._target_temp,
            get_ext_temp=lambda: self._ext_temp,
            get_control_output=lambda: self._control_output,
            get_cold_tolerance=lambda: self._cold_tolerance,
            get_hot_tolerance=lambda: self._hot_tolerance,
            get_ke=lambda: self._ke,
            set_ke=self._set_ke,
            get_pid_controller=lambda: self._pid_controller,
            async_control_heating=self._async_control_heating_internal,
            async_write_ha_state=self._async_write_ha_state_internal,
            get_is_pid_converged=self._is_pid_converged_for_ke,
        )
        _LOGGER.info(
            "%s: Ke controller initialized",
            self.entity_id
        )

        # Initialize PID tuning manager
        self._pid_tuning_manager = PIDTuningManager(
            thermostat=self,
            pid_controller=self._pid_controller,
            get_kp=lambda: self._kp,
            get_ki=lambda: self._ki,
            get_kd=lambda: self._kd,
            get_ke=lambda: self._ke,
            set_kp=self._set_kp,
            set_ki=self._set_ki,
            set_kd=self._set_kd,
            set_ke=self._set_ke,
            get_area_m2=lambda: self._area_m2,
            get_ceiling_height=lambda: self._ceiling_height,
            get_window_area_m2=lambda: self._window_area_m2,
            get_window_rating=lambda: self._window_rating,
            get_heating_type=lambda: self._heating_type,
            get_hass=lambda: self.hass,
            get_zone_id=lambda: self._zone_id,
            async_control_heating=self._async_control_heating_internal,
            async_write_ha_state=self._async_write_ha_state_internal,
        )
        _LOGGER.info(
            "%s: PID tuning manager initialized",
            self.entity_id
        )

        # Initialize control output manager
        self._control_output_manager = ControlOutputManager(
            thermostat=self,
            pid_controller=self._pid_controller,
            heater_controller=self._heater_controller,
            get_current_temp=lambda: self._current_temp,
            get_ext_temp=lambda: self._ext_temp,
            get_previous_temp_time=lambda: self._previous_temp_time,
            set_previous_temp_time=self._set_previous_temp_time,
            get_cur_temp_time=lambda: self._cur_temp_time,
            set_cur_temp_time=self._set_cur_temp_time,
            get_output_precision=lambda: self._output_precision,
            calculate_night_setback_adjustment=self._calculate_night_setback_adjustment,
            set_control_output=self._set_control_output,
            set_p=self._set_p,
            set_i=self._set_i,
            set_d=self._set_d,
            set_e=self._set_e,
            set_dt=self._set_dt,
            get_kp=lambda: self._kp,
            get_ki=lambda: self._ki,
            get_kd=lambda: self._kd,
            get_ke=lambda: self._ke,
        )
        _LOGGER.info(
            "%s: Control output manager initialized",
            self.entity_id
        )

        # Initialize cycle tracker for adaptive learning
        coordinator = self.hass.data.get(DOMAIN, {}).get("coordinator")
        if coordinator and self._zone_id:
            zone_data = coordinator.get_zone_data(self._zone_id)
            if zone_data:
                adaptive_learner = zone_data.get("adaptive_learner")
                if adaptive_learner:
                    self._cycle_tracker = CycleTrackerManager(
                        hass=self.hass,
                        zone_id=self._zone_id,
                        adaptive_learner=adaptive_learner,
                        get_target_temp=lambda: self._target_temp,
                        get_current_temp=lambda: self._current_temp,
                        get_hvac_mode=lambda: self._hvac_mode,
                        get_in_grace_period=lambda: self._in_grace_period,
                        get_is_device_active=lambda: self._is_device_active,
                    )
                    _LOGGER.info(
                        "%s: Initialized CycleTrackerManager",
                        self.entity_id
                    )

        # Set up state change listeners
        self._setup_state_listeners()

        # Restore state from previous session using StateRestorer
        old_state = await self.async_get_last_state()
        state_restorer = StateRestorer(self)
        state_restorer.restore(old_state)

        # Set default state to off
        if not self._hvac_mode:
            self._hvac_mode = HVACMode.OFF
        await self._async_control_heating(calc_pid=True)

    async def async_will_remove_from_hass(self) -> None:
        """Run when entity is being removed from Home Assistant.

        This method unregisters the zone from the coordinator to ensure
        clean removal and prevent stale zone data.
        """
        await super().async_will_remove_from_hass()

        # Unregister zone from coordinator
        if self._zone_id:
            coordinator = self.hass.data.get(DOMAIN, {}).get("coordinator")
            if coordinator:
                coordinator.unregister_zone(self._zone_id)
                _LOGGER.info(
                    "%s: Unregistered zone %s from coordinator",
                    self.entity_id,
                    self._zone_id,
                )

    def _setup_state_listeners(self) -> None:
        """Set up all state change listeners for sensors and controlled entities.

        This method registers listeners for:
        - Temperature sensor changes
        - External temperature sensor changes (if configured)
        - Heater entity state changes (if configured)
        - Cooler entity state changes (if configured)
        - Demand switch state changes (if configured)
        - Keep-alive interval timer (if configured)
        - Startup callback to initialize sensor values
        """
        # Temperature sensor listener
        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                self._sensor_entity_id,
                self._async_sensor_changed))

        # External temperature sensor listener
        if self._ext_sensor_entity_id is not None:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    self._ext_sensor_entity_id,
                    self._async_ext_sensor_changed))

        # Heater entity listener
        if self._heater_entity_id is not None:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    self._heater_entity_id,
                    self._async_switch_changed))

        # Cooler entity listener
        if self._cooler_entity_id is not None:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    self._cooler_entity_id,
                    self._async_switch_changed))

        # Demand switch entity listener
        if self._demand_switch_entity_id is not None:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    self._demand_switch_entity_id,
                    self._async_switch_changed))

        # Contact sensor listeners (window/door open detection)
        if self._contact_sensor_handler:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    self._contact_sensor_handler.contact_sensors,
                    self._async_contact_sensor_changed))
            # Initialize contact sensor states on startup
            self._update_contact_sensor_states()

        # Control loop interval timer
        # Derive interval: explicit control_interval > sampling_period > default 60s
        if self._control_interval:
            control_interval = self._control_interval
        elif self._sampling_period > 0:
            control_interval = timedelta(seconds=self._sampling_period)
        else:
            control_interval = timedelta(seconds=const.DEFAULT_CONTROL_INTERVAL)
        self.async_on_remove(
            async_track_time_interval(
                self.hass,
                self._async_control_heating,
                control_interval))

        # Startup callback to initialize sensor values
        @callback
        def _async_startup(*_):
            """Init on startup."""
            sensor_state = self.hass.states.get(self._sensor_entity_id)
            if sensor_state and sensor_state.state != STATE_UNKNOWN:
                self._async_update_temp(sensor_state)
            if self._ext_sensor_entity_id is not None:
                ext_sensor_state = self.hass.states.get(self._ext_sensor_entity_id)
                if ext_sensor_state and ext_sensor_state.state != STATE_UNKNOWN:
                    self._async_update_ext_temp(ext_sensor_state)

        if self.hass.state == CoreState.running:
            _async_startup()
        else:
            self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_START, _async_startup)

    def _restore_state(self, old_state) -> None:
        """Restore climate entity state from Home Assistant's state restoration.

        This is a compatibility wrapper that delegates to StateRestorer.
        """
        state_restorer = StateRestorer(self)
        state_restorer._restore_state(old_state)

    def _restore_pid_values(self, old_state) -> None:
        """Restore PID controller values from Home Assistant's state restoration.

        This is a compatibility wrapper that delegates to StateRestorer.
        """
        state_restorer = StateRestorer(self)
        state_restorer._restore_pid_values(old_state)

    @property
    def should_poll(self):
        """Return the polling state."""
        return False

    @property
    def name(self):
        """Return the name of the thermostat."""
        return self._name

    @property
    def unique_id(self):
        """Return a unique ID."""
        return self._unique_id

    @staticmethod
    def _get_number_entity_domain(entity_id):
        return INPUT_NUMBER_DOMAIN if "input_number" in entity_id else NUMBER_DOMAIN

    @property
    def precision(self):
        """Return the precision of the system."""
        if self._temp_precision is not None:
            return self._temp_precision
        return super().precision

    @property
    def target_temperature_step(self):
        """Return the supported step of target temperature."""
        return self._target_temperature_step

    @property
    def temperature_unit(self):
        """Return the unit of measurement."""
        return self._unit

    @property
    def current_temperature(self):
        """Return the sensor temperature."""
        return self._current_temp

    @property
    def hvac_mode(self):
        """Return current operation."""
        return self._hvac_mode

    @property
    def hvac_action(self):
        """Return the current running hvac operation if supported.
        Need to be one of CURRENT_HVAC_*.
        """
        if self._hvac_mode == HVACMode.OFF:
            return HVACAction.OFF
        if not self._is_device_active:
            return HVACAction.IDLE
        if self._hvac_mode == HVACMode.COOL:
            return HVACAction.COOLING
        return HVACAction.HEATING

    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        return self._target_temp

    @property
    def preset_mode(self):
        """Return the current preset mode, e.g., home, away, temp."""
        return self._temperature_manager.preset_mode

    @property
    def preset_modes(self):
        """Return a list of available preset modes."""
        return self._temperature_manager.preset_modes

    @property
    def _preset_modes_temp(self):
        """Return a dict of preset modes and their temperatures."""
        return self._temperature_manager._preset_modes_temp

    @property
    def _preset_temp_modes(self):
        """Return a dict of preset temperatures and their modes."""
        return self._temperature_manager._preset_temp_modes

    @property
    def presets(self):
        """Return a dict of available presets and their temperatures."""
        return self._temperature_manager.presets

    @property
    def in_learning_grace_period(self) -> bool:
        """Check if learning should be paused due to recent night setback transition."""
        if self._night_setback_controller:
            return self._night_setback_controller.in_learning_grace_period
        # No night setback controller means no grace period
        return False

    def _set_learning_grace_period(self, minutes: int = 60):
        """Set a grace period to pause learning after night setback transitions."""
        if self._night_setback_controller:
            self._night_setback_controller.set_learning_grace_period(minutes)

    def _calculate_night_setback_adjustment(self, current_time=None):
        """Calculate night setback adjustment for effective target temperature.

        Delegates to NightSetbackController for all calculation logic.

        Args:
            current_time: Optional datetime for testing; defaults to datetime.now()

        Returns:
            A tuple of (effective_target, in_night_period, night_setback_info) where:
            - effective_target: The adjusted target temperature
            - in_night_period: Whether we are currently in the night setback period
            - night_setback_info: Dict with additional info for state attributes
        """
        # Delegate to controller if available
        if self._night_setback_controller:
            return self._night_setback_controller.calculate_night_setback_adjustment(current_time)

        # Fallback: return defaults when controller not yet initialized
        # (e.g., before async_added_to_hass is called)
        return self._target_temp, False, {"night_setback_active": False}

    @property
    def _min_on_cycle_duration(self):
        if self.pid_mode == 'off':
            return self._min_on_cycle_duration_pid_off
        return self._min_on_cycle_duration_pid_on

    @property
    def _min_off_cycle_duration(self):
        if self.pid_mode == 'off':
            return self._min_off_cycle_duration_pid_off
        return self._min_off_cycle_duration_pid_on

    @property
    def pid_parm(self):
        """Return the pid parameters of the thermostat."""
        return self._kp, self._ki, self._kd

    @property
    def pid_control_p(self):
        """Return the proportional output of PID controller."""
        return self._p

    @property
    def pid_control_i(self):
        """Return the integral output of PID controller."""
        return self._i

    @property
    def pid_control_d(self):
        """Return the derivative output of PID controller."""
        return self._d

    @property
    def pid_control_e(self):
        """Return the external output of external temperature compensation."""
        return self._e

    @property
    def pid_mode(self):
        """Return the PID operating mode."""
        if getattr(self, '_pid_controller', None) is not None:
            return self._pid_controller.mode.lower()
        return 'off'

    @property
    def pid_control_output(self):
        """Return the pid control output of the thermostat."""
        return self._control_output

    @property
    def extra_state_attributes(self):
        """Return extra state attributes to include in entity."""
        return build_state_attributes(self)

    def set_hvac_mode(self, hvac_mode: (HVACMode, str)) -> None:
        """Set new target hvac mode."""
        if hvac_mode == HVACMode.HEAT:
            self._min_out = self._output_clamp_low
            self._max_out = self._output_clamp_high
            self._hvac_mode = HVACMode.HEAT
        elif hvac_mode == HVACMode.COOL:
            self._min_out = -self._output_clamp_high
            self._max_out = -self._output_clamp_low
            self._hvac_mode = HVACMode.COOL
        elif hvac_mode == HVACMode.HEAT_COOL:
            self._min_out = -self._output_clamp_high
            self._max_out = self._output_clamp_high
            self._hvac_mode = HVACMode.HEAT_COOL
        elif hvac_mode == HVACMode.OFF:
            self._hvac_mode = HVACMode.OFF
            self._control_output = self._output_min
            self._previous_temp = None
            self._previous_temp_time = None
            if self._pid_controller is not None:
                self._pid_controller.clear_samples()
        if self._pid_controller:
            self._pid_controller.out_max = self._max_out
            self._pid_controller.out_min = self._min_out

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        old_mode = self._hvac_mode
        await self._async_heater_turn_off(force=True)
        if hvac_mode == HVACMode.HEAT:
            self._min_out = self._output_clamp_low
            self._max_out = self._output_clamp_high
            self._hvac_mode = HVACMode.HEAT
        elif hvac_mode == HVACMode.COOL:
            self._min_out = -self._output_clamp_high
            self._max_out = -self._output_clamp_low
            self._hvac_mode = HVACMode.COOL
        elif hvac_mode == HVACMode.HEAT_COOL:
            self._min_out = -self._output_clamp_high
            self._max_out = self._output_clamp_high
            self._hvac_mode = HVACMode.HEAT_COOL
        elif hvac_mode == HVACMode.OFF:
            self._hvac_mode = HVACMode.OFF
            self._control_output = self._output_min
            if self._pwm:
                _LOGGER.debug("%s: Turn OFF heater from async_set_hvac_mode(%s)",
                              self.entity_id,
                              hvac_mode)
                await self._async_heater_turn_off(force=True)
            else:
                _LOGGER.debug("%s: Set heater to %s from async_set_hvac_mode(%s)",
                              self.entity_id,
                              self._control_output,
                              hvac_mode)
                await self._async_set_valve_value(self._control_output)
            # Clear the samples to avoid integrating the off period
            self._previous_temp = None
            self._previous_temp_time = None
            if self._pid_controller is not None:
                self._pid_controller.clear_samples()
        else:
            _LOGGER.error("%s: Unrecognized HVAC mode: %s", self.entity_id, hvac_mode)
            return
        if self._pid_controller:
            self._pid_controller.out_max = self._max_out
            self._pid_controller.out_min = self._min_out
        if self._hvac_mode != HVACMode.OFF:
            await self._async_control_heating(calc_pid=True)
        # Ensure we update the current operation after changing the mode
        self.async_write_ha_state()

        # Trigger mode sync if configured
        if self._zone_id and old_mode != self._hvac_mode:
            mode_sync = self.hass.data.get(DOMAIN, {}).get("mode_sync")
            if mode_sync:
                await mode_sync.on_mode_change(
                    zone_id=self._zone_id,
                    old_mode=old_mode.value if old_mode else "off",
                    new_mode=self._hvac_mode.value if self._hvac_mode else "off",
                    climate_entity_id=self.entity_id,
                )

        # Notify cycle tracker of mode change
        if self._cycle_tracker and old_mode != self._hvac_mode:
            old_mode_str = old_mode.value if old_mode else "off"
            new_mode_str = self._hvac_mode.value if self._hvac_mode else "off"
            self._cycle_tracker.on_mode_changed(old_mode_str, new_mode_str)

    async def async_set_temperature(self, **kwargs):
        """Set new target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        await self._temperature_manager.async_set_temperature(temperature)
        self.async_write_ha_state()

    async def async_set_pid(self, **kwargs):
        """Set PID parameters.

        Delegates to PIDTuningManager for the actual implementation.
        """
        await self._pid_tuning_manager.async_set_pid(**kwargs)

    async def async_set_pid_mode(self, **kwargs):
        """Set PID mode (AUTO or OFF).

        Delegates to PIDTuningManager for the actual implementation.
        """
        await self._pid_tuning_manager.async_set_pid_mode(**kwargs)

    async def async_set_preset_temp(self, **kwargs):
        """Set the presets modes temperatures."""
        await self._temperature_manager.async_set_preset_temp(**kwargs)

    async def clear_integral(self, **kwargs):
        """Clear the integral value."""
        self._pid_controller.integral = 0.0
        self._i = self._pid_controller.integral
        self.async_write_ha_state()

    async def async_reset_pid_to_physics(self, **kwargs):
        """Reset PID values to physics-based defaults.

        Delegates to PIDTuningManager for the actual implementation.
        """
        await self._pid_tuning_manager.async_reset_pid_to_physics(**kwargs)

    async def async_apply_adaptive_pid(self, **kwargs):
        """Apply adaptive PID values based on learned metrics.

        Delegates to PIDTuningManager for the actual implementation.
        """
        await self._pid_tuning_manager.async_apply_adaptive_pid(**kwargs)

    async def async_apply_adaptive_ke(self, **kwargs):
        """Apply adaptive Ke value based on learned outdoor temperature correlations.

        Delegates to PIDTuningManager (which delegates to KeController) for the actual implementation.
        """
        if self._ke_controller is not None:
            await self._ke_controller.async_apply_adaptive_ke(**kwargs)

    def _is_at_steady_state(self) -> bool:
        """Check if the system is at steady state (maintaining target temperature).

        Delegates to KeController for the actual implementation.

        Returns:
            True if at steady state, False otherwise
        """
        if self._ke_controller is not None:
            return self._ke_controller.is_at_steady_state()
        return False

    def _maybe_record_ke_observation(self) -> None:
        """Record a Ke observation if conditions are met.

        Delegates to KeController for the actual implementation.
        """
        if self._ke_controller is not None:
            self._ke_controller.maybe_record_observation()

    @property
    def min_temp(self):
        """Return the minimum temperature."""
        if self._min_temp:
            return self._min_temp

        # get default temp from super class
        return super().min_temp

    @property
    def max_temp(self):
        """Return the maximum temperature."""
        if self._max_temp:
            return self._max_temp

        # Get default temp from super class
        return super().max_temp

    @callback
    async def _async_sensor_changed(self, event: Event[EventStateChangedData]):
        """Handle temperature changes."""
        new_state = event.data["new_state"]
        if new_state is None:
            return

        self._previous_temp_time = self._cur_temp_time
        self._cur_temp_time = time.time()
        self._async_update_temp(new_state)
        self._trigger_source = 'sensor'
        _LOGGER.debug("%s: Received new temperature: %s", self.entity_id, self._current_temp)
        await self._async_control_heating(calc_pid=True)
        self.async_write_ha_state()

    @callback
    async def _async_ext_sensor_changed(self, event: Event[EventStateChangedData]):
        """Handle temperature changes."""
        new_state = event.data["new_state"]
        if new_state is None:
            return

        self._async_update_ext_temp(new_state)
        self._trigger_source = 'ext_sensor'
        _LOGGER.debug("%s: Received new external temperature: %s", self.entity_id, self._ext_temp)
        await self._async_control_heating(calc_pid=False)

    @callback
    def _async_switch_changed(self, event: Event[EventStateChangedData]):
        """Handle heater switch state changes."""
        new_state = event.data["new_state"]
        if new_state is None:
            return

        # Update zone demand for CentralController when valve state changes
        if self._zone_id:
            coordinator = self.hass.data.get(const.DOMAIN, {}).get("coordinator")
            if coordinator:
                coordinator.update_zone_demand(self._zone_id, self._is_device_active, self._hvac_mode.value if self._hvac_mode else None)

        self.async_write_ha_state()

    @callback
    async def _async_contact_sensor_changed(self, event: Event[EventStateChangedData]):
        """Handle contact sensor (window/door) state changes."""
        new_state = event.data["new_state"]
        if new_state is None:
            return

        # Update all contact sensor states in the handler
        self._update_contact_sensor_states()

        entity_id = event.data["entity_id"]
        is_open = new_state.state == STATE_ON
        _LOGGER.debug(
            "%s: Contact sensor %s changed to %s",
            self.entity_id, entity_id, "open" if is_open else "closed"
        )

        # Trigger control heating to potentially pause/resume
        await self._async_control_heating(calc_pid=False)

    def _update_contact_sensor_states(self):
        """Update contact sensor handler with current states from Home Assistant."""
        if not self._contact_sensor_handler:
            return

        contact_states = {}
        for sensor_id in self._contact_sensor_handler.contact_sensors:
            state = self.hass.states.get(sensor_id)
            if state:
                # Contact sensors: 'on' = open, 'off' = closed
                contact_states[sensor_id] = state.state == STATE_ON
            else:
                _LOGGER.warning(
                    "%s: Contact sensor %s not found",
                    self.entity_id, sensor_id
                )
        self._contact_sensor_handler.update_contact_states(contact_states)

    @callback
    def _async_update_temp(self, state):
        """Update thermostat with latest state from sensor."""
        if state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE, None):
            _LOGGER.debug("%s: Sensor %s is %s, skipping update",
                          self.entity_id, self._sensor_entity_id, state.state)
            return
        try:
            self._previous_temp = self._current_temp
            self._current_temp = float(state.state)
            self._last_sensor_update = time.time()
        except ValueError as ex:
            _LOGGER.debug("%s: Unable to update from sensor %s: %s", self.entity_id,
                          self._sensor_entity_id, ex)

    @callback
    def _async_update_ext_temp(self, state):
        """Update thermostat with latest state from sensor."""
        if state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE, None):
            _LOGGER.debug("%s: External sensor %s is %s, skipping update",
                          self.entity_id, self._ext_sensor_entity_id, state.state)
            return
        try:
            self._ext_temp = float(state.state)
            self._last_ext_sensor_update = time.time()
        except ValueError as ex:
            _LOGGER.debug("%s: Unable to update from sensor %s: %s", self.entity_id,
                          self._ext_sensor_entity_id, ex)

    async def _async_control_heating(
            self, time_func: object = None, calc_pid: object = False) -> object:
        """Run PID controller, optional autotune for faster integration"""
        async with self._temp_lock:
            if not self._active and None not in (self._current_temp, self._target_temp):
                self._active = True
                _LOGGER.info("%s: Obtained temperature %s with set point %s. Activating Smart"
                             "Thermostat.", self.entity_id, self._current_temp, self._target_temp)

            if not self._active or self._hvac_mode == HVACMode.OFF:
                if self._force_off_state and self._hvac_mode == HVACMode.OFF and \
                        self._is_device_active:
                    _LOGGER.debug("%s: %s is active while HVAC mode is %s. Turning it OFF.",
                                  self.entity_id, ", ".join([entity for entity in self.heater_or_cooler_entity]), self._hvac_mode)
                    if self._pwm:
                        await self._async_heater_turn_off(force=True)
                    else:
                        self._control_output = self._output_min
                        await self._async_set_valve_value(self._control_output)
                # Update zone demand to False when OFF/inactive
                if self._zone_id:
                    coordinator = self.hass.data.get(const.DOMAIN, {}).get("coordinator")
                    if coordinator:
                        coordinator.update_zone_demand(self._zone_id, False, self._hvac_mode.value if self._hvac_mode else None)
                self.async_write_ha_state()
                return

            # Contact sensor pause check (window/door open)
            if self._contact_sensor_handler and self._contact_sensor_handler.should_take_action():
                action = self._contact_sensor_handler.get_action()
                if action == ContactAction.PAUSE:
                    _LOGGER.info(
                        "%s: Contact sensor open - pausing heating",
                        self.entity_id
                    )
                    # Notify cycle tracker of contact sensor pause
                    if self._cycle_tracker:
                        self._cycle_tracker.on_contact_sensor_pause()

                    if self._pwm:
                        await self._async_heater_turn_off(force=True)
                    else:
                        self._control_output = self._output_min
                        await self._async_set_valve_value(self._control_output)
                    # Update zone demand to False when paused
                    if self._zone_id:
                        coordinator = self.hass.data.get(const.DOMAIN, {}).get("coordinator")
                        if coordinator:
                            coordinator.update_zone_demand(self._zone_id, False, self._hvac_mode.value if self._hvac_mode else None)
                    self.async_write_ha_state()
                    return

            if self._sensor_stall != 0 and time.time() - self._last_sensor_update > \
                    self._sensor_stall:
                # sensor not updated for too long, considered as stall, set to safety level
                self._control_output = self._output_safety
            else:
                # Always recalculate PID to ensure output reflects current conditions
                await self.calc_output()

                # Record temperature for cycle tracking
                if self._cycle_tracker and self._current_temp is not None:
                    await self._cycle_tracker.update_temperature(datetime.now(), self._current_temp)
            await self.set_control_value()

            # Update zone demand for CentralController (based on actual device state, not PID output)
            if self._zone_id:
                coordinator = self.hass.data.get(const.DOMAIN, {}).get("coordinator")
                if coordinator:
                    coordinator.update_zone_demand(self._zone_id, self._is_device_active, self._hvac_mode.value if self._hvac_mode else None)

            # Record Ke observation if at steady state
            self._maybe_record_ke_observation()

            self.async_write_ha_state()

    @property
    def _is_device_active(self) -> bool:
        """Check if the toggleable/valve device is currently active.

        Delegates to HeaterController for the actual check.

        Returns:
            True if device is active, False if no heater controller or device is inactive.
        """
        if self._heater_controller is None:
            return False
        return self._heater_controller.is_active(self.hvac_mode)

    def _get_cycle_start_time(self) -> float:
        """Get the time when the current heating/cooling cycle started.

        Returns our tracked time if available. If not yet tracked (startup),
        returns 0 to allow immediate action since we have no reliable data
        about when the cycle actually started (HA's last_changed reflects
        restart time, not actual device state change time).
        """
        if self._last_heat_cycle_time is not None:
            return self._last_heat_cycle_time

        # No tracked time yet - allow immediate action on first cycle after startup
        return 0

    # Setter callbacks for HeaterController
    def _set_is_heating(self, value: bool) -> None:
        """Set the heating state flag."""
        self._is_heating = value

    def _set_last_heat_cycle_time(self, value: float) -> None:
        """Set the last heat cycle time."""
        self._last_heat_cycle_time = value

    def _set_time_changed(self, value: float) -> None:
        """Set the time changed value."""
        self._time_changed = value

    def _set_force_on(self, value: bool) -> None:
        """Set the force on flag."""
        self._force_on = value

    def _set_force_off(self, value: bool) -> None:
        """Set the force off flag."""
        self._force_off = value

    # Setter callbacks for KeController
    def _set_ke(self, value: float) -> None:
        """Set the Ke value."""
        self._ke = value

    # Setter callbacks for PIDTuningManager
    def _set_kp(self, value: float) -> None:
        """Set the Kp value."""
        self._kp = value

    def _set_ki(self, value: float) -> None:
        """Set the Ki value."""
        self._ki = value

    def _set_kd(self, value: float) -> None:
        """Set the Kd value."""
        self._kd = value

    # Setter callbacks for ControlOutputManager
    def _set_control_output(self, value: float) -> None:
        """Set the control output value."""
        self._control_output = value

    def _set_p(self, value: float) -> None:
        """Set the proportional component value."""
        self._p = value

    def _set_i(self, value: float) -> None:
        """Set the integral component value."""
        self._i = value

    def _set_d(self, value: float) -> None:
        """Set the derivative component value."""
        self._d = value

    def _set_e(self, value: float) -> None:
        """Set the external component value."""
        self._e = value

    def _set_dt(self, value: float) -> None:
        """Set the delta time value."""
        self._dt = value

    def _set_previous_temp_time(self, value: float) -> None:
        """Set the previous temperature time."""
        self._previous_temp_time = value

    def _set_cur_temp_time(self, value: float) -> None:
        """Set the current temperature time."""
        self._cur_temp_time = value

    def _is_pid_converged_for_ke(self) -> bool:
        """Check if PID has converged sufficiently for Ke learning.

        Returns True if the adaptive learner reports PID convergence
        (stable performance for required number of consecutive cycles).
        """
        coordinator = self.hass.data.get(DOMAIN, {}).get("coordinator")
        if not coordinator or not self._zone_id:
            return False
        zone_data = coordinator.get_zone_data(self._zone_id)
        if not zone_data:
            return False
        adaptive_learner = zone_data.get("adaptive_learner")
        if not adaptive_learner:
            return False
        return adaptive_learner.is_pid_converged_for_ke()

    async def _async_write_ha_state_internal(self) -> None:
        """Write HA state (internal callback for managers)."""
        self.async_write_ha_state()

    # Setter callbacks for TemperatureManager
    def _set_target_temp(self, value: float) -> None:
        """Set the target temperature."""
        # Track old temperature for cycle tracker
        old_temp = self._target_temp

        # Update target temperature
        self._target_temp = value

        # Notify cycle tracker of setpoint change
        if self._cycle_tracker is not None and old_temp is not None and old_temp != value:
            self._cycle_tracker.on_setpoint_changed(old_temp, value)

    async def _async_set_pid_mode_internal(self, mode: str) -> None:
        """Internal callback to set PID mode from TemperatureManager."""
        await self.async_set_pid_mode(mode=mode)

    async def _async_control_heating_internal(self, calc_pid: bool) -> None:
        """Internal callback to trigger heating control from TemperatureManager."""
        await self._async_control_heating(calc_pid=calc_pid)

    @property
    def supported_features(self):
        """Return the list of supported features."""
        return self._support_flags

    @property
    def heater_or_cooler_entity(self):
        """Return the entities to be controlled based on HVAC MODE.

        Returns heater or cooler entities based on mode, plus any demand_switch
        entities which are controlled regardless of heat/cool mode.

        Delegates to HeaterController for the actual list.
        """
        return self._heater_controller.get_entities(self.hvac_mode)

    def _fire_heater_control_failed_event(
        self,
        entity_id: str,
        operation: str,
        error: str,
    ) -> None:
        """Fire an event when heater control fails.

        Delegates to HeaterController for the actual event firing.

        Args:
            entity_id: Entity that failed to control
            operation: Operation that failed (turn_on, turn_off, set_value)
            error: Error message
        """
        self._heater_controller._fire_heater_control_failed_event(
            entity_id, operation, error
        )

    async def _async_call_heater_service(
        self,
        entity_id: str,
        domain: str,
        service: str,
        data: dict,
    ) -> bool:
        """Call a heater/cooler service with error handling.

        Delegates to HeaterController for the actual service call.

        Args:
            entity_id: Entity ID being controlled
            domain: Service domain (homeassistant, light, valve, number, etc.)
            service: Service name (turn_on, turn_off, set_value, etc.)
            data: Service call data

        Returns:
            True if successful, False otherwise
        """
        result = await self._heater_controller._async_call_heater_service(
            entity_id, domain, service, data
        )
        # Sync failure state from controller
        self._heater_control_failed = self._heater_controller.heater_control_failed
        self._last_heater_error = self._heater_controller.last_heater_error
        return result

    async def _async_heater_turn_on(self):
        """Turn heater toggleable device on.

        Delegates to HeaterController for the actual turn on operation.
        """
        # Update cycle durations in case PID mode changed
        self._heater_controller.update_cycle_durations(
            self._min_on_cycle_duration.seconds,
            self._min_off_cycle_duration.seconds,
        )
        await self._heater_controller.async_turn_on(
            hvac_mode=self.hvac_mode,
            get_cycle_start_time=self._get_cycle_start_time,
            zone_linker=self._zone_linker,
            unique_id=self._unique_id,
            linked_zones=self._linked_zones,
            link_delay_minutes=self._link_delay_minutes,
            is_heating=self._is_heating,
            set_is_heating=self._set_is_heating,
            set_last_heat_cycle_time=self._set_last_heat_cycle_time,
        )

    async def _async_heater_turn_off(self, force=False):
        """Turn heater toggleable device off.

        Delegates to HeaterController for the actual turn off operation.
        """
        # Update cycle durations in case PID mode changed
        self._heater_controller.update_cycle_durations(
            self._min_on_cycle_duration.seconds,
            self._min_off_cycle_duration.seconds,
        )
        await self._heater_controller.async_turn_off(
            hvac_mode=self.hvac_mode,
            get_cycle_start_time=self._get_cycle_start_time,
            set_is_heating=self._set_is_heating,
            set_last_heat_cycle_time=self._set_last_heat_cycle_time,
            force=force,
        )

    async def _async_set_valve_value(self, value: float):
        """Set valve value for non-PWM devices.

        Delegates to HeaterController for the actual valve control.
        """
        await self._heater_controller.async_set_valve_value(value, self.hvac_mode)

    async def async_set_preset_mode(self, preset_mode: str):
        """Set new preset mode.
        This method must be run in the event loop and returns a coroutine.
        """
        await self._temperature_manager.async_set_preset_mode(preset_mode)
        # Sync internal state for backward compatibility
        self._attr_preset_mode = self._temperature_manager.preset_mode
        self._saved_target_temp = self._temperature_manager.saved_target_temp

    async def calc_output(self):
        """Calculate PID control output.

        Delegates to ControlOutputManager for the actual calculation.
        """
        await self._control_output_manager.calc_output()

    async def set_control_value(self):
        """Set output value for heater.

        Delegates to HeaterController for the actual control operation.
        """
        if self._heater_controller is None:
            _LOGGER.warning(
                "%s: HeaterController not initialized, cannot set control value",
                self.entity_id,
            )
            return

        # Update cycle durations in case PID mode changed
        self._heater_controller.update_cycle_durations(
            self._min_on_cycle_duration.seconds,
            self._min_off_cycle_duration.seconds,
        )
        await self._heater_controller.async_set_control_value(
            control_output=self._control_output,
            hvac_mode=self.hvac_mode,
            get_cycle_start_time=self._get_cycle_start_time,
            zone_linker=self._zone_linker,
            unique_id=self._unique_id,
            linked_zones=self._linked_zones,
            link_delay_minutes=self._link_delay_minutes,
            is_heating=self._is_heating,
            set_is_heating=self._set_is_heating,
            set_last_heat_cycle_time=self._set_last_heat_cycle_time,
            time_changed=self._time_changed,
            set_time_changed=self._set_time_changed,
            force_on=self._force_on,
            force_off=self._force_off,
            set_force_on=self._set_force_on,
            set_force_off=self._set_force_off,
        )

    async def pwm_switch(self):
        """Turn off and on the heater proportionally to control_value.

        Delegates to HeaterController for the PWM switching operation.
        """
        if self._heater_controller is None:
            _LOGGER.warning(
                "%s: HeaterController not initialized, cannot perform PWM switch",
                self.entity_id,
            )
            return

        # Update cycle durations in case PID mode changed
        self._heater_controller.update_cycle_durations(
            self._min_on_cycle_duration.seconds,
            self._min_off_cycle_duration.seconds,
        )
        await self._heater_controller.async_pwm_switch(
            control_output=self._control_output,
            hvac_mode=self.hvac_mode,
            get_cycle_start_time=self._get_cycle_start_time,
            zone_linker=self._zone_linker,
            unique_id=self._unique_id,
            linked_zones=self._linked_zones,
            link_delay_minutes=self._link_delay_minutes,
            is_heating=self._is_heating,
            set_is_heating=self._set_is_heating,
            set_last_heat_cycle_time=self._set_last_heat_cycle_time,
            time_changed=self._time_changed,
            set_time_changed=self._set_time_changed,
            force_on=self._force_on,
            force_off=self._force_off,
            set_force_on=self._set_force_on,
            set_force_off=self._set_force_off,
        )
