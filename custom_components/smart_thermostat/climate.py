"""Adds support for smart (PID) thermostat units.
For more details about this platform, please refer to the documentation at
https://github.com/fabiannydegger/custom_components/"""

import asyncio
import logging
import time
from abc import ABC

import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
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
    STATE_UNKNOWN,
)
from homeassistant.core import DOMAIN as HA_DOMAIN, callback
from homeassistant.util import slugify
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.event import (
    async_track_state_change,
    async_track_time_interval,
)
from homeassistant.helpers.reload import async_setup_reload_service
from homeassistant.helpers.restore_state import RestoreEntity

from homeassistant.components.climate import PLATFORM_SCHEMA, ClimateEntity, ClimateEntityFeature
from homeassistant.components.climate import (
    ATTR_PRESET_MODE,
    HVACMode,
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

_LOGGER = logging.getLogger(__name__)


PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(const.CONF_HEATER): cv.entity_id,
        vol.Required(const.CONF_INVERT_HEATER, default=False): cv.boolean,
        vol.Required(const.CONF_SENSOR): cv.entity_id,
        vol.Optional(const.CONF_OUTDOOR_SENSOR): cv.entity_id,
        vol.Optional(const.CONF_AC_MODE): cv.boolean,
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
        vol.Required(const.CONF_KEEP_ALIVE): vol.All(cv.time_period, cv.positive_timedelta),
        vol.Optional(const.CONF_SAMPLING_PERIOD, default=const.DEFAULT_SAMPLING_PERIOD): vol.All(
            cv.time_period, cv.positive_timedelta),
        vol.Optional(const.CONF_SENSOR_STALL, default=const.DEFAULT_SENSOR_STALL): vol.All(
            cv.time_period, cv.positive_timedelta),
        vol.Optional(const.CONF_OUTPUT_SAFETY, default=const.DEFAULT_OUTPUT_SAFETY): vol.Coerce(
            float),
        vol.Optional(const.CONF_INITIAL_HVAC_MODE): vol.In(
            [HVACMode.COOL, HVACMode.HEAT, HVACMode.OFF]
        ),
        vol.Optional(const.CONF_PRESET_SYNC_MODE, default=const.DEFAULT_PRESET_SYNC_MODE): vol.In(
            ['sync', 'none']
        ),
        vol.Optional(const.CONF_AWAY_TEMP): vol.Coerce(float),
        vol.Optional(const.CONF_ECO_TEMP): vol.Coerce(float),
        vol.Optional(const.CONF_BOOST_TEMP): vol.Coerce(float),
        vol.Optional(const.CONF_COMFORT_TEMP): vol.Coerce(float),
        vol.Optional(const.CONF_HOME_TEMP): vol.Coerce(float),
        vol.Optional(const.CONF_SLEEP_TEMP): vol.Coerce(float),
        vol.Optional(const.CONF_ACTIVITY_TEMP): vol.Coerce(float),
        vol.Optional(const.CONF_PRECISION): vol.In(
            [PRECISION_TENTHS, PRECISION_HALVES, PRECISION_WHOLE]
        ),
        vol.Optional(const.CONF_TARGET_TEMP_STEP): vol.In(
            [PRECISION_TENTHS, PRECISION_HALVES, PRECISION_WHOLE]
        ),
        vol.Optional(const.CONF_DIFFERENCE, default=const.DEFAULT_DIFFERENCE): vol.Coerce(float),
        vol.Optional(const.CONF_KP, default=const.DEFAULT_KP): vol.Coerce(float),
        vol.Optional(const.CONF_KI, default=const.DEFAULT_KI): vol.Coerce(float),
        vol.Optional(const.CONF_KD, default=const.DEFAULT_KD): vol.Coerce(float),
        vol.Optional(const.CONF_KE, default=const.DEFAULT_KE): vol.Coerce(float),
        vol.Optional(const.CONF_PWM, default=const.DEFAULT_PWM): vol.All(
            cv.time_period, cv.positive_timedelta
        ),
        vol.Optional(const.CONF_BOOST_PID_OFF, default=False): cv.boolean,
        vol.Optional(const.CONF_AUTOTUNE, default=const.DEFAULT_AUTOTUNE): cv.string,
        vol.Optional(const.CONF_NOISEBAND, default=const.DEFAULT_NOISEBAND): vol.Coerce(float),
        vol.Optional(const.CONF_LOOKBACK, default=const.DEFAULT_LOOKBACK): vol.All(
            cv.time_period, cv.positive_timedelta),
        vol.Optional(const.CONF_DEBUG, default=False): cv.boolean,
    }
)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType = None
) -> None:
    """Set up the thermostat platform."""
    await async_setup_reload_service(hass, DOMAIN, PLATFORMS)

    if hass.data.get(DOMAIN) is None:
        hass.data.setdefault(DOMAIN, {})

    parameters = {
        'name': config.get(CONF_NAME),
        'unique_id': config.get(CONF_UNIQUE_ID),
        'heater_entity_id': config.get(const.CONF_HEATER),
        'invert_heater': config.get(const.CONF_INVERT_HEATER),
        'sensor_entity_id': config.get(const.CONF_SENSOR),
        'ext_sensor_entity_id': config.get(const.CONF_OUTDOOR_SENSOR),
        'min_temp': config.get(const.CONF_MIN_TEMP),
        'max_temp': config.get(const.CONF_MAX_TEMP),
        'target_temp': config.get(const.CONF_TARGET_TEMP),
        'hot_tolerance': config.get(const.CONF_HOT_TOLERANCE),
        'cold_tolerance': config.get(const.CONF_COLD_TOLERANCE),
        'ac_mode': config.get(const.CONF_AC_MODE),
        'min_cycle_duration': config.get(const.CONF_MIN_CYCLE_DURATION),
        'min_off_cycle_duration': config.get(const.CONF_MIN_OFF_CYCLE_DURATION),
        'min_cycle_duration_pid_off': config.get(const.CONF_MIN_CYCLE_DURATION_PID_OFF),
        'min_off_cycle_duration_pid_off': config.get(const.CONF_MIN_OFF_CYCLE_DURATION_PID_OFF),
        'keep_alive': config.get(const.CONF_KEEP_ALIVE),
        'sampling_period': config.get(const.CONF_SAMPLING_PERIOD),
        'sensor_stall': config.get(const.CONF_SENSOR_STALL),
        'output_safety': config.get(const.CONF_OUTPUT_SAFETY),
        'initial_hvac_mode': config.get(const.CONF_INITIAL_HVAC_MODE),
        'preset_sync_mode': config.get(const.CONF_PRESET_SYNC_MODE),
        'away_temp': config.get(const.CONF_AWAY_TEMP),
        'eco_temp': config.get(const.CONF_ECO_TEMP),
        'boost_temp': config.get(const.CONF_BOOST_TEMP),
        'comfort_temp': config.get(const.CONF_COMFORT_TEMP),
        'home_temp': config.get(const.CONF_HOME_TEMP),
        'sleep_temp': config.get(const.CONF_SLEEP_TEMP),
        'activity_temp': config.get(const.CONF_ACTIVITY_TEMP),
        'precision': config.get(const.CONF_PRECISION),
        'target_temp_step': config.get(const.CONF_TARGET_TEMP_STEP),
        'unit': hass.config.units.temperature_unit,
        'difference': config.get(const.CONF_DIFFERENCE),
        'kp': config.get(const.CONF_KP),
        'ki': config.get(const.CONF_KI),
        'kd': config.get(const.CONF_KD),
        'ke': config.get(const.CONF_KE),
        'pwm': config.get(const.CONF_PWM),
        'boost_pid_off': config.get(const.CONF_BOOST_PID_OFF),
        'autotune': config.get(const.CONF_AUTOTUNE),
        'noiseband': config.get(const.CONF_NOISEBAND),
        'lookback': config.get(const.CONF_LOOKBACK),
        const.CONF_DEBUG: config.get(const.CONF_DEBUG),
    }

    # smart_thermostat = SmartThermostat(**parameters)
    # async_add_entities([smart_thermostat])
    add_entities([SmartThermostat(**parameters)])

    hass.services.async_register(  # type: ignore
        DOMAIN,
        "set_pid_gain",
        "async_set_pid",
        {
            vol.Optional("kp"): vol.Coerce(float),
            vol.Optional("ki"): vol.Coerce(float),
            vol.Optional("kd"): vol.Coerce(float),
            vol.Optional("ke"): vol.Coerce(float),
        },
    )
    hass.services.async_register(  # type: ignore
        DOMAIN,
        "set_pid_mode",
        "async_set_pid_mode",
        {
            vol.Required("mode"): vol.In(['auto', 'off']),
        },
    )
    hass.services.async_register(  # type: ignore
        DOMAIN,
        "set_preset_temp",
        "async_set_preset_temp",
        {
            vol.Optional("away_temp"): vol.Coerce(float),
            vol.Optional("eco_temp"): vol.Coerce(float),
            vol.Optional("boost_temp"): vol.Coerce(float),
            vol.Optional("comfort_temp"): vol.Coerce(float),
            vol.Optional("home_temp"): vol.Coerce(float),
            vol.Optional("sleep_temp"): vol.Coerce(float),
            vol.Optional("activity_temp"): vol.Coerce(float),
        },
    )
    hass.services.async_register(  # type: ignore
        DOMAIN,
        "clear_integral",
        "clear_integral",
        {},
    )


class SmartThermostat(ClimateEntity, RestoreEntity, ABC):
    """Representation of a Smart Thermostat device."""

    def __init__(self, **kwargs):
        """Initialize the thermostat."""
        self._name = kwargs.get('name')
        self._unique_id = kwargs.get('unique_id')
        self._heater_entity_id = kwargs.get('heater_entity_id')
        self._heater_polarity_invert = kwargs.get('invert_heater')
        self._sensor_entity_id = kwargs.get('sensor_entity_id')
        self._ext_sensor_entity_id = kwargs.get('ext_sensor_entity_id')
        if self._unique_id == 'none':
            self._unique_id = slugify(f"{DOMAIN}_{self._name}_{self._heater_entity_id}")
        self._ac_mode = kwargs.get('ac_mode')
        self._keep_alive = kwargs.get('keep_alive')
        self._sampling_period = kwargs.get('sampling_period').seconds
        self._sensor_stall = kwargs.get('sensor_stall').seconds
        self._output_safety = kwargs.get('output_safety')
        self._attr_hvac_mode = kwargs.get('initial_hvac_mode', None)
        self._saved_target_temp = kwargs.get('target_temp', None) or kwargs.get('away_temp', None)
        self._temp_precision = kwargs.get('precision')
        self._target_temperature_step = kwargs.get('target_temp_step')
        self._debug = kwargs.get(const.CONF_DEBUG)
        self._last_heat_cycle_time = time.time()
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
            self._support_flags = ClimateEntityFeature.TARGET_TEMPERATURE | \
                                  ClimateEntityFeature.PRESET_MODE
        self._difference = kwargs.get('difference')
        if self._ac_mode == HVACMode.COOL:
            self._attr_hvac_modes = [HVACMode.COOL, HVACMode.OFF]
            self._min_out = -self._difference
            self._max_out = 0
        else:
            self._attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
            self._min_out = 0
            self._max_out = self._difference
        self._kp = kwargs.get('kp')
        self._ki = kwargs.get('ki')
        self._kd = kwargs.get('kd')
        self._ke = kwargs.get('ke')
        self._pwm = kwargs.get('pwm').seconds
        self._p = self._i = self._d = self._e = self._dt = 0
        self._control_output = 0
        self._force_on = False
        self._force_off = False
        self._boost_pid_off = kwargs.get('boost_pid_off')
        self._autotune = kwargs.get('autotune')
        self._lookback = kwargs.get('lookback').seconds + kwargs.get('lookback').days * 86400
        self._noiseband = kwargs.get('noiseband')
        self._cold_tolerance = abs(kwargs.get('cold_tolerance'))
        self._hot_tolerance = abs(kwargs.get('hot_tolerance'))
        self._time_changed = 0
        self._last_sensor_update = time.time()
        self._last_ext_sensor_update = time.time()
        if self._autotune != "none":
            self._pid_controller = None
            self._pid_autotune = pid_controller.PIDAutotune(self._difference, self._lookback,
                                                            self._min_out, self._max_out,
                                                            self._noiseband, time.time)
            _LOGGER.warning("Autotune will run on %s (%s) with the target temperature "
                            "set after 10 temperature samples from sensor. Changes submitted "
                            "after doesn't have any effect until autotuning is finished",
                            self._name, self._unique_id)
        else:
            _LOGGER.debug("PID Gains for %s (%s): kp = %s, ki = %s, kd = %s", self._name,
                          self._unique_id, self._kp, self._ki, self._kd)
            self._pid_controller = pid_controller.PID(self._kp, self._ki, self._kd, self._ke,
                                                      self._min_out, self._max_out,
                                                      self._sampling_period, self._cold_tolerance,
                                                      self._hot_tolerance)
            self._pid_controller.mode = "AUTO"

    async def async_added_to_hass(self):
        """Run when entity about to be added."""
        await super().async_added_to_hass()

        # Add listener
        async_track_state_change(self.hass, self._sensor_entity_id, self._async_sensor_changed)
        if self._ext_sensor_entity_id is not None:
            async_track_state_change(self.hass, self._ext_sensor_entity_id,
                                     self._async_ext_sensor_changed)
        async_track_state_change(self.hass, self._heater_entity_id, self._async_switch_changed)

        if self._keep_alive:
            async_track_time_interval(self.hass, self._async_control_heating, self._keep_alive)

        @callback
        def _async_startup(event):
            """Init on startup."""
            sensor_state = self.hass.states.get(self._sensor_entity_id)
            if sensor_state and sensor_state.state != STATE_UNKNOWN:
                self._async_update_temp(sensor_state)
            if self._ext_sensor_entity_id is not None:
                ext_sensor_state = self.hass.states.get(self._ext_sensor_entity_id)
                if ext_sensor_state and ext_sensor_state.state != STATE_UNKNOWN:
                    self._async_update_ext_temp(ext_sensor_state)

        self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_START, _async_startup)

        # Check If we have an old state
        old_state = await self.async_get_last_state()
        if old_state is not None:
            # If we have no initial temperature, restore
            if self._target_temp is None:
                # If we have a previously saved temperature
                if old_state.attributes.get(ATTR_TEMPERATURE) is None:
                    if self._ac_mode:
                        self._target_temp = self.max_temp
                    else:
                        self._target_temp = self.min_temp
                    _LOGGER.warning("Undefined target temperature for %s (%s), falling back to %s",
                                    self.name, self.unique_id, self._target_temp)
                else:
                    self._target_temp = float(old_state.attributes.get(ATTR_TEMPERATURE))
            for preset_mode in ['away_temp', 'eco_temp', 'boost_temp', 'comfort_temp', 'home_temp',
                                'sleep_temp', 'activity_temp']:
                if old_state.attributes.get(preset_mode) is not None:
                    setattr(self, f"_{preset_mode}", float(old_state.attributes.get(preset_mode)))
            if old_state.attributes.get(ATTR_PRESET_MODE) is not None:
                self._attr_preset_mode = old_state.attributes.get(ATTR_PRESET_MODE)
            if isinstance(old_state.attributes.get('pid_i'), (float, int)) and \
                    self._pid_controller is not None:
                self._i = float(old_state.attributes.get('pid_i'))
                self._pid_controller.integral = self._i
            if self.hvac_mode is None and old_state.state in self.hvac_modes:
                self._attr_hvac_mode = old_state.state
            if old_state.attributes.get('kp') is not None and self._pid_controller is not None:
                self._kp = float(old_state.attributes.get('kp'))
                self._pid_controller.set_pid_param(kp=self._kp)
            if old_state.attributes.get('ki') is not None and self._pid_controller is not None:
                self._ki = float(old_state.attributes.get('ki'))
                self._pid_controller.set_pid_param(ki=self._ki)
            if old_state.attributes.get('kd') is not None and self._pid_controller is not None:
                self._kd = float(old_state.attributes.get('kd'))
                self._pid_controller.set_pid_param(kd=self._kd)
            if old_state.attributes.get('ke') is not None and self._pid_controller is not None:
                self._ke = float(old_state.attributes.get('ke'))
                self._pid_controller.set_pid_param(ke=self._ke)
            if old_state.attributes.get('pid_mode') is not None and \
                    self._pid_controller is not None:
                self._pid_controller.mode = old_state.attributes.get('pid_mode')

        else:
            # No previous state, try and restore defaults
            if self._target_temp is None:
                if self._ac_mode:
                    self._target_temp = self.max_temp
                else:
                    self._target_temp = self.min_temp
            _LOGGER.warning("No previously saved temperature for %s (%s), setting to %s",
                            self.name, self.unique_id, self._target_temp)

        # Set default state to off
        if not self.hvac_mode:
            self._attr_hvac_mode = HVACMode.OFF
        await self._async_control_heating(calc_pid=True)

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
    def target_temperature(self):
        """Return the temperature we try to reach."""
        return self._target_temp

    @property
    def preset_mode(self):
        """Return the current preset mode, e.g., home, away, temp."""
        return self._attr_preset_mode

    @property
    def preset_modes(self):
        """Return a list of available preset modes."""
        preset_modes = [PRESET_NONE]
        for mode, preset_mode_temp in self._preset_modes_temp.items():
            if preset_mode_temp is not None:
                preset_modes.append(mode)
        return preset_modes

    @property
    def _preset_modes_temp(self):
        """Return a list of preset modes and their temperatures"""
        return {
            PRESET_AWAY: self._away_temp,
            PRESET_ECO: self._eco_temp,
            PRESET_BOOST: self._boost_temp,
            PRESET_COMFORT: self._comfort_temp,
            PRESET_HOME: self._home_temp,
            PRESET_SLEEP: self._sleep_temp,
            PRESET_ACTIVITY: self._activity_temp,
        }

    @property
    def _preset_temp_modes(self):
        """Return a list of preset temperature and their modes"""
        return {
            self._away_temp: PRESET_AWAY,
            self._eco_temp: PRESET_ECO,
            self._boost_temp: PRESET_BOOST,
            self._comfort_temp: PRESET_COMFORT,
            self._home_temp: PRESET_HOME,
            self._sleep_temp: PRESET_SLEEP,
            self._activity_temp: PRESET_ACTIVITY,
        }

    @property
    def presets(self):
        """Return a dict of available preset and temperatures."""
        presets = {}
        for mode, preset_mode_temp in self._preset_modes_temp.items():
            if preset_mode_temp is not None:
                presets.update({mode: preset_mode_temp})
        return presets

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
        if getattr(self, '_pidController', None) is not None:
            return self._pid_controller.mode.lower()
        return 'off'

    @property
    def pid_control_output(self):
        """Return the pid control output of the thermostat."""
        return self._control_output

    @property
    def extra_state_attributes(self):
        """attributes to include in entity"""
        device_state_attributes = {
            'away_temp': self._away_temp,
            'eco_temp': self._eco_temp,
            'boost_temp': self._boost_temp,
            'comfort_temp': self._comfort_temp,
            'home_temp': self._home_temp,
            'sleep_temp': self._sleep_temp,
            'activity_temp': self._activity_temp,
            "control_output": self._control_output,
            "kp": self._kp,
            "ki": self._ki,
            "kd": self._kd,
            "ke": self._ke,
        }
        if self._autotune != "none" and self._debug:
            device_state_attributes.update({
                "pid_mode": 'off',
                "pid_p": 0,
                "pid_i": 0,
                "pid_d": 0,
                "pid_e": 0,
                "pid_dt": 0,
                "autotune_status": self._pid_autotune.state,
                "autotune_sample_time": self._pid_autotune.sample_time,
                "autotune_tuning_rule": self._autotune,
                "autotune_set_point": self._pid_autotune.set_point,
                "autotune_peak_count": self._pid_autotune.peak_count,
                "autotune_buffer_full": round(self._pid_autotune.buffer_full, 2),
                "autotune_buffer_length": self._pid_autotune.buffer_length,
            })
        elif self._debug:
            device_state_attributes.update({
                "pid_mode": self.pid_mode,
                "pid_p": self.pid_control_p,
                "pid_i": self.pid_control_i,
                "pid_d": self.pid_control_d,
                "pid_e": self.pid_control_e,
                "pid_dt": self._dt,
                "autotune_status": 'off',
                "autotune_sample_time": 0.0,
                "autotune_tuning_rule": 'none',
                "autotune_set_point": 0,
                "autotune_peak_count": 0,
                "autotune_buffer_full": 0.0,
                "autotune_buffer_length": 0,
            })
        return device_state_attributes

    def set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        if hvac_mode == HVACMode.HEAT:
            self._attr_hvac_mode = HVACMode.HEAT
            self._async_control_heating(calc_pid=True)
        elif hvac_mode == HVACMode.COOL:
            self._attr_hvac_mode = HVACMode.COOL
            self._async_control_heating(calc_pid=True)
        elif hvac_mode == HVACMode.HEAT_COOL:
            self._attr_hvac_mode = HVACMode.COOL
            self._async_control_heating(calc_pid=True)
        elif hvac_mode == HVACMode.OFF:
            self._attr_hvac_mode = HVACMode.OFF
            if self._is_device_active:
                self._async_heater_turn_off(force=True)
            # Clear the samples to avoid integrating the off period
            self._previous_temp = None
            self._previous_temp_time = None
            if self._pid_controller is not None:
                self._pid_controller.clear_samples()
        else:
            _LOGGER.error("Unrecognized hvac mode for %s (%s): %s",
                          self.name, self.unique_id, hvac_mode)
            return
        # Ensure we update the current operation after changing the mode
        self.schedule_update_ha_state()

    async def async_set_temperature(self, **kwargs):
        """Set new target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        if self._current_temp is not None and temperature > self._current_temp:
            self._force_on = True
        elif self._current_temp is not None and temperature < self._current_temp:
            self._force_off = True
        if temperature in self._preset_temp_modes and self._preset_sync_mode == 'sync':
            await self.async_set_preset_mode(self._preset_temp_modes[temperature])
        else:
            await self.async_set_preset_mode(PRESET_NONE)
            self._target_temp = temperature
        await self._async_control_heating(calc_pid=True)

    async def async_set_pid(self, **kwargs):
        """Set PID parameters."""
        gain_kp = kwargs.get('kp', None)
        gain_ki = kwargs.get('ki', None)
        gain_kd = kwargs.get('kd', None)
        gain_ke = kwargs.get('ke', None)
        if gain_kp is not None:
            self._kp = float(gain_kp)
        if gain_ki is not None:
            self._ki = float(gain_ki)
        if gain_kd is not None:
            self._kd = float(gain_kd)
        if gain_ke is not None:
            self._ke = float(gain_ke)
        self._pid_controller.set_pid_param(self._kp, self._ki, self._kd, self._ke)
        await self._async_control_heating(calc_pid=True)

    async def async_set_pid_mode(self, **kwargs):
        """Set PID parameters."""
        mode = kwargs.get('mode', None)
        if str(mode).upper() in ['AUTO', 'OFF'] and self._pid_controller is not None:
            self._pid_controller.mode = str(mode).upper()
        await self._async_control_heating(calc_pid=True)

    async def async_set_preset_temp(self, **kwargs):
        """Set the presets modes temperatures."""
        away_temp = kwargs.get('away_temp', None)
        eco_temp = kwargs.get('eco_temp', None)
        boost_temp = kwargs.get('boost_temp', None)
        comfort_temp = kwargs.get('comfort_temp', None)
        home_temp = kwargs.get('home_temp', None)
        sleep_temp = kwargs.get('sleep_temp', None)
        activity_temp = kwargs.get('activity_temp', None)
        if away_temp is not None:
            self._away_temp = max(min(float(away_temp), self.max_temp), self.min_temp)
        if eco_temp is not None:
            self._eco_temp = max(min(float(eco_temp), self.max_temp), self.min_temp)
        if boost_temp is not None:
            self._boost_temp = max(min(float(boost_temp), self.max_temp), self.min_temp)
        if comfort_temp is not None:
            self._comfort_temp = max(min(float(comfort_temp), self.max_temp), self.min_temp)
        if home_temp is not None:
            self._home_temp = max(min(float(home_temp), self.max_temp), self.min_temp)
        if sleep_temp is not None:
            self._sleep_temp = max(min(float(sleep_temp), self.max_temp), self.min_temp)
        if activity_temp is not None:
            self._activity_temp = max(min(float(activity_temp), self.max_temp), self.min_temp)
        await self._async_control_heating(calc_pid=True)

    async def clear_integral(self, **kwargs):
        """Clear the integral value."""
        self._pid_controller.integral = 0.0
        await self.async_update_ha_state()

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

    async def _async_sensor_changed(self, entity_id, old_state, new_state):
        """Handle temperature changes."""
        if new_state is None:
            return

        self._previous_temp_time = self._cur_temp_time
        self._cur_temp_time = time.time()
        self._async_update_temp(new_state)
        self._trigger_source = 'sensor'
        _LOGGER.debug("Received new temperature sensor input for %s (%s) at timestamp %s (before "
                      "%s): %s (before %s)", self.name, self.entity_id, self._cur_temp_time,
                      self._previous_temp_time, self._current_temp, self._previous_temp)
        await self._async_control_heating(calc_pid=True)

    async def _async_ext_sensor_changed(self, entity_id, old_state, new_state):
        """Handle temperature changes."""
        if new_state is None:
            return

        self._async_update_ext_temp(new_state)
        self._trigger_source = 'ext_sensor'
        _LOGGER.debug("Received new outdoor temperature sensor input for %s (%s) at timestamp %s: "
                      "%s", self.name, self.entity_id, time.time(), self._ext_temp)
        await self._async_control_heating(calc_pid=False)

    @callback
    def _async_switch_changed(self, entity_id, old_state, new_state):
        """Handle heater switch state changes."""
        if new_state is None:
            return
        self.async_schedule_update_ha_state()

    @callback
    def _async_update_temp(self, state):
        """Update thermostat with latest state from sensor."""
        try:
            self._previous_temp = self._current_temp
            self._current_temp = float(state.state)
            self._last_sensor_update = time.time()
        except ValueError as ex:
            _LOGGER.debug("%s (%s) - unable to update from sensor: %s",
                          self.name, self.entity_id, ex)

    @callback
    def _async_update_ext_temp(self, state):
        """Update thermostat with latest state from sensor."""
        try:
            self._ext_temp = float(state.state)
            self._last_ext_sensor_update = time.time()
        except ValueError as ex:
            _LOGGER.debug("%s (%s) - unable to update from sensor: %s",
                          self.name, self.entity_id, ex)

    async def _async_control_heating(self, time_func=None, calc_pid=False):
        """Run PID controller, optional autotune for faster integration"""
        async with self._temp_lock:
            if not self._active and None not in (self._current_temp, self._target_temp):
                self._active = True
                _LOGGER.info("Obtained temperature %s with set point %s. Smart thermostat %s (%s) "
                             "active", self._current_temp, self._target_temp, self.name,
                             self.entity_id)

            if not self._active or self._attr_hvac_mode == HVACMode.OFF:
                await self.async_update_ha_state()
                return

            if self._sensor_stall != 0 and time.time() - self._last_sensor_update > \
                    self._sensor_stall:
                # sensor not updated for too long, considered as stall, set to safety level
                self._control_output = self._output_safety
            elif calc_pid or self._sampling_period != 0:
                await self.calc_output()
            await self.set_control_value()
            await self.async_update_ha_state()

    @property
    def _is_device_active(self):
        """If the toggleable device is currently active."""
        if self._heater_polarity_invert:
            return self.hass.states.is_state(self._heater_entity_id, STATE_OFF)
        return self.hass.states.is_state(self._heater_entity_id, STATE_ON)

    @property
    def supported_features(self):
        """Return the list of supported features."""
        return self._support_flags

    async def _async_heater_turn_on(self):
        """Turn heater toggleable device on."""
        if time.time() - self._last_heat_cycle_time >= self._min_off_cycle_duration.seconds:
            data = {ATTR_ENTITY_ID: self._heater_entity_id}
            _LOGGER.info("Turning on %s for %s (%s)", self._heater_entity_id,
                         self.name, self.entity_id)
            if self._heater_polarity_invert:
                service = SERVICE_TURN_OFF
            else:
                service = SERVICE_TURN_ON
            await self.hass.services.async_call(HA_DOMAIN, service, data)
            self._last_heat_cycle_time = time.time()
        else:
            _LOGGER.info("Reject request turning on %s for %s (%s): Cycle is too short",
                         self._heater_entity_id, self.name, self.entity_id)

    async def _async_heater_turn_off(self, force=False):
        """Turn heater toggleable device off."""
        if time.time() - self._last_heat_cycle_time >= self._min_on_cycle_duration.seconds or force:
            data = {ATTR_ENTITY_ID: self._heater_entity_id}
            _LOGGER.info("Turning off %s for %s (%s)", self._heater_entity_id,
                         self.name, self.entity_id)
            if self._heater_polarity_invert:
                service = SERVICE_TURN_ON
            else:
                service = SERVICE_TURN_OFF
            await self.hass.services.async_call(HA_DOMAIN, service, data)
            self._last_heat_cycle_time = time.time()
        else:
            _LOGGER.info("Reject request turning off %s for %s (%s): Cycle is too short",
                         self._heater_entity_id, self.name, self.entity_id)

    async def async_set_preset_mode(self, preset_mode: str):
        """Set new preset mode.
        This method must be run in the event loop and returns a coroutine.
        """
        if preset_mode not in self.preset_modes:
            return None
        if preset_mode != PRESET_NONE and self.preset_mode == PRESET_NONE:
            # self._is_away = True
            self._saved_target_temp = self._target_temp
            self._target_temp = self.presets[preset_mode]
        elif preset_mode == PRESET_NONE and self.preset_mode != PRESET_NONE:
            # self._is_away = False
            self._target_temp = self._saved_target_temp
        elif preset_mode == PRESET_NONE and self.preset_mode == PRESET_NONE:
            return None
        else:
            self._target_temp = self.presets[preset_mode]
        self._attr_preset_mode = preset_mode
        if self._boost_pid_off and self._attr_preset_mode == PRESET_BOOST:
            # Force PID OFF if requested and boost mode is active
            await self.async_set_pid_mode(mode='off')
        elif self._boost_pid_off and self._attr_preset_mode != PRESET_BOOST:
            # Force PID Auto if managed by boost_pid_off and not in boost mode
            await self.async_set_pid_mode(mode='auto')
        else:
            # if boost_pid_off is false, don't change the PID mode
            await self._async_control_heating(calc_pid=True)

    async def calc_output(self):
        """calculate control output and handle autotune"""
        update = False
        if self._previous_temp_time is None:
            self._previous_temp_time = time.time()
        if self._cur_temp_time is None:
            self._cur_temp_time = time.time()
        if self._previous_temp_time > self._cur_temp_time:
            self._previous_temp_time = self._cur_temp_time
        if self._autotune != "none":
            if self._trigger_source == "sensor":
                self._trigger_source = None
                if self._pid_autotune.run(self._current_temp, self._target_temp):
                    for tuning_rule in self._pid_autotune.tuning_rules:
                        params = self._pid_autotune.get_pid_parameters(tuning_rule)
                        _LOGGER.warning("Smart thermostat %s (%s) PID Autotuner output with %s "
                                        "rule: kp=%s, ki=%s, kd=%s", self.name, self.entity_id,
                                        tuning_rule, params.kp, params.ki, params.kd)
                    params = self._pid_autotune.get_pid_parameters(self._autotune)
                    self._kp = params.kp
                    self._ki = params.ki
                    self._kd = params.kd
                    _LOGGER.warning("Smart thermostat %s (%s) now runs on PID Controller using "
                                    "rule %s: kp=%s, ki=%s, kd=%s", self.name, self.entity_id,
                                    self._autotune, self._kp, self._ki, self._kd)
                    self._pid_controller = pid_controller.PID(self._kp, self._ki, self._kd,
                                                              self._ke, self._min_out,
                                                              self._max_out, self._sampling_period,
                                                              self._cold_tolerance,
                                                              self._hot_tolerance)
                    self._autotune = "none"
            self._control_output = self._pid_autotune.output
            self._p = self._i = self._d = error = self._dt = 0
        else:
            if self._pid_controller.sampling_period == 0:
                self._control_output, update = self._pid_controller.calc(self._current_temp,
                                                                         self._target_temp,
                                                                         self._cur_temp_time,
                                                                         self._previous_temp_time,
                                                                         self._ext_temp)
            else:
                self._control_output, update = self._pid_controller.calc(self._current_temp,
                                                                         self._target_temp,
                                                                         ext_temp=self._ext_temp)
            self._p = round(self._pid_controller.P, 1)
            self._i = round(self._pid_controller.I, 1)
            self._d = round(self._pid_controller.D, 1)
            self._e = round(self._pid_controller.E, 1)
            self._control_output = round(self._control_output, 1)
            error = self._pid_controller.error
            self._dt = self._pid_controller.dt
        if update:
            _LOGGER.debug("New PID control output for %s (%s). %.2f (error = %.2f, dt = %.2f, "
                          "p=%.2f, i=%.2f, d=%.2f, e=%.2f)", self.name, self.entity_id,
                          self._control_output, error, self._dt, self._p, self._i, self._d,
                          self._e)

    async def set_control_value(self):
        """Set Output value for heater"""
        if self._pwm:
            # Compute time_on based on PWM duration and PID output
            time_on = self._pwm * abs(self._control_output) / self._difference
            time_off = self._pwm - time_on
            # Check time_on and time_off are not too short
            if 0 < time_on < self._min_on_cycle_duration.seconds:
                # time_on is too short, increase time_off and time_on
                time_off *= self._min_on_cycle_duration.seconds / time_on
                time_on = self._min_on_cycle_duration.seconds
            if 0 < time_off < self._min_off_cycle_duration.seconds:
                # time_off is too short, increase time_on and time_off
                time_on *= self._min_off_cycle_duration.seconds / time_off
                time_off = self._min_off_cycle_duration.seconds
            if abs(self._control_output) == self._difference:
                if not self._is_device_active:
                    _LOGGER.info("Request turning on %s for %s (%s)", self._heater_entity_id,
                                 self.name, self.entity_id)
                    await self._async_heater_turn_on()
                    self._time_changed = time.time()
            elif abs(self._control_output) > 0:
                await self.pwm_switch(time_on, time_off, time.time() - self._time_changed)
            else:
                if self._is_device_active:
                    _LOGGER.info("Request turning off %s for %s (%s)", self._heater_entity_id,
                                 self.name, self.entity_id)
                    await self._async_heater_turn_off()
                    self._time_changed = time.time()
        else:
            _LOGGER.info("Change state of %s to %s on %s (%s)", self._heater_entity_id,
                         round(self._control_output, 2), self.name, self.entity_id)
            self.hass.states.async_set(self._heater_entity_id, self._control_output)

    async def pwm_switch(self, time_on, time_off, time_passed):
        """turn off and on the heater proportionally to control_value."""
        if self._is_device_active:
            if time_on <= time_passed or self._force_off:
                _LOGGER.info("Request turning off %s for %s (%s)", self._heater_entity_id,
                             self.name, self.entity_id)
                await self._async_heater_turn_off()
                self._time_changed = time.time()
            else:
                _LOGGER.info("Time until %s turns off for %s (%s): %s sec", self._heater_entity_id,
                             self.name, self.entity_id, int(time_on - time_passed))
        else:
            if time_off <= time_passed or self._force_on:
                _LOGGER.info("Request turning on %s for %s (%s)", self._heater_entity_id,
                             self.name, self.entity_id)
                await self._async_heater_turn_on()
                self._time_changed = time.time()
            else:
                _LOGGER.info("Time until %s turns on for %s (%s): %s sec", self._heater_entity_id,
                             self.name, self.entity_id, int(time_off - time_passed))
        self._force_on = False
        self._force_off = False
