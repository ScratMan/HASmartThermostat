"""Adds support for smart (PID) thermostat units.
For more details about this platform, please refer to the documentation at
https://github.com/fabiannydegger/custom_components/"""

import asyncio
import logging
import time
import custom_components.smart_thermostat.pid_controller as pid_controller

import voluptuous as vol

from homeassistant.const import (
    ATTR_ENTITY_ID, ATTR_TEMPERATURE, CONF_NAME, EVENT_HOMEASSISTANT_START,
    PRECISION_HALVES, PRECISION_TENTHS, PRECISION_WHOLE, SERVICE_TURN_OFF,
    SERVICE_TURN_ON, STATE_ON, STATE_UNKNOWN)
from homeassistant.core import DOMAIN as HA_DOMAIN, callback
from homeassistant.helpers import condition
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.event import (
    async_track_state_change, async_track_time_interval)
from homeassistant.helpers.restore_state import RestoreEntity

from homeassistant.components.climate import PLATFORM_SCHEMA, ClimateEntity
from homeassistant.components.climate.const import (
    ATTR_PRESET_MODE, CURRENT_HVAC_COOL, CURRENT_HVAC_HEAT, CURRENT_HVAC_IDLE,
    CURRENT_HVAC_OFF, HVAC_MODE_COOL, HVAC_MODE_HEAT, HVAC_MODE_OFF,
    PRESET_AWAY, SUPPORT_PRESET_MODE, SUPPORT_TARGET_TEMPERATURE)

_LOGGER = logging.getLogger(__name__)

DEFAULT_TOLERANCE = 0.3
DEFAULT_NAME = 'Smart Thermostat'
DEFAULT_DIFFERENCE = 100
DEFAULT_PWM = 0
DEFAULT_KP = 0
DEFAULT_KI = 0
DEFAULT_KD = 0
DEFAULT_AUTOTUNE = "none"
DEFAULT_NOISEBAND = 0.5

CONF_HEATER = 'heater'
CONF_SENSOR = 'target_sensor'
CONF_MIN_TEMP = 'min_temp'
CONF_MAX_TEMP = 'max_temp'
CONF_TARGET_TEMP = 'target_temp'
CONF_AC_MODE = 'ac_mode'
CONF_MIN_DUR = 'min_cycle_duration'
CONF_COLD_TOLERANCE = 'cold_tolerance'
CONF_HOT_TOLERANCE = 'hot_tolerance'
CONF_KEEP_ALIVE = 'keep_alive'
CONF_INITIAL_HVAC_MODE = 'initial_hvac_mode'
CONF_AWAY_TEMP = 'away_temp'
CONF_PRECISION = 'precision'
CONF_DIFFERENCE = 'difference'
CONF_KP = 'kp'
CONF_KI = 'ki'
CONF_KD = 'kd'
CONF_PWM = 'pwm'
CONF_AUTOTUNE = 'autotune'
CONF_NOISEBAND = 'noiseband'

SUPPORT_FLAGS = SUPPORT_TARGET_TEMPERATURE

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_HEATER): cv.entity_id,
    vol.Required(CONF_SENSOR): cv.entity_id,
    vol.Optional(CONF_AC_MODE): cv.boolean,
    vol.Optional(CONF_MAX_TEMP): vol.Coerce(float),
    vol.Optional(CONF_MIN_DUR): vol.All(cv.time_period, cv.positive_timedelta),
    vol.Optional(CONF_MIN_TEMP): vol.Coerce(float),
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    vol.Optional(CONF_COLD_TOLERANCE, default=DEFAULT_TOLERANCE): vol.Coerce(
        float),
    vol.Optional(CONF_HOT_TOLERANCE, default=DEFAULT_TOLERANCE): vol.Coerce(
        float),
    vol.Optional(CONF_TARGET_TEMP): vol.Coerce(float),
    vol.Required(CONF_KEEP_ALIVE): vol.All(
        cv.time_period, cv.positive_timedelta),
    vol.Optional(CONF_INITIAL_HVAC_MODE):
        vol.In([HVAC_MODE_COOL, HVAC_MODE_HEAT, HVAC_MODE_OFF]),
    vol.Optional(CONF_AWAY_TEMP): vol.Coerce(float),
    vol.Optional(CONF_PRECISION): vol.In(
        [PRECISION_TENTHS, PRECISION_HALVES, PRECISION_WHOLE]),
    vol.Optional(CONF_DIFFERENCE, default=DEFAULT_DIFFERENCE): vol.Coerce(float),
    vol.Optional(CONF_KP, default=DEFAULT_KP): vol.Coerce(float),
    vol.Optional(CONF_KI, default=DEFAULT_KI): vol.Coerce(float),
    vol.Optional(CONF_KD, default=DEFAULT_KD): vol.Coerce(float),
    vol.Optional(CONF_PWM, default=DEFAULT_PWM): vol.Coerce(float),
    vol.Optional(CONF_AUTOTUNE, default=DEFAULT_AUTOTUNE): cv.string,
    vol.Optional(CONF_NOISEBAND, default=DEFAULT_NOISEBAND): vol.Coerce(float)
})


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up the generic thermostat platform."""
    name = config.get(CONF_NAME)
    heater_entity_id = config.get(CONF_HEATER)
    sensor_entity_id = config.get(CONF_SENSOR)
    min_temp = config.get(CONF_MIN_TEMP)
    max_temp = config.get(CONF_MAX_TEMP)
    target_temp = config.get(CONF_TARGET_TEMP)
    ac_mode = config.get(CONF_AC_MODE)
    min_cycle_duration = config.get(CONF_MIN_DUR)
    cold_tolerance = config.get(CONF_COLD_TOLERANCE)
    hot_tolerance = config.get(CONF_HOT_TOLERANCE)
    keep_alive = config.get(CONF_KEEP_ALIVE)
    initial_hvac_mode = config.get(CONF_INITIAL_HVAC_MODE)
    away_temp = config.get(CONF_AWAY_TEMP)
    precision = config.get(CONF_PRECISION)
    unit = hass.config.units.temperature_unit
    difference = config.get(CONF_DIFFERENCE)
    kp = config.get(CONF_KP)
    ki = config.get(CONF_KI)
    kd = config.get(CONF_KD)
    pwm = config.get(CONF_PWM)
    autotune = config.get(CONF_AUTOTUNE)
    noiseband = config.get(CONF_NOISEBAND)

    async_add_entities([SmartThermostat(
        name, heater_entity_id, sensor_entity_id, min_temp, max_temp,
        target_temp, ac_mode, min_cycle_duration, cold_tolerance,
        hot_tolerance, keep_alive, initial_hvac_mode, away_temp,
        precision, unit, difference, kp, ki, kd, pwm, autotune, noiseband)])


class SmartThermostat(ClimateEntity, RestoreEntity):
    """Representation of a Smart Thermostat device."""

    def __init__(self, name, heater_entity_id, sensor_entity_id,
                 min_temp, max_temp, target_temp, ac_mode, min_cycle_duration,
                 cold_tolerance, hot_tolerance, keep_alive,
                 initial_hvac_mode, away_temp, precision, unit,
                 difference, kp, ki, kd, pwm, autotune, noiseband):
        """Initialize the thermostat."""
        self._name = name
        self.heater_entity_id = heater_entity_id
        self.sensor_entity_id = sensor_entity_id
        self.ac_mode = ac_mode
        self.min_cycle_duration = min_cycle_duration
        self._cold_tolerance = cold_tolerance
        self._hot_tolerance = hot_tolerance
        self._keep_alive = keep_alive
        self._hvac_mode = initial_hvac_mode
        self._saved_target_temp = target_temp or away_temp
        self._temp_precision = precision
        if self.ac_mode:
            self._hvac_list = [HVAC_MODE_COOL, HVAC_MODE_OFF]
            self.minOut = -difference
            self.maxOut = 0
        else:
            self._hvac_list = [HVAC_MODE_HEAT, HVAC_MODE_OFF]
            self.minOut = 0
            self.maxOut = difference
        self._active = False
        self._cur_temp = None
        self._cur_temp_time = None
        self._previous_temp = None
        self._previous_temp_time = None
        self._temp_lock = asyncio.Lock()
        self._min_temp = min_temp
        self._max_temp = max_temp
        self._target_temp = target_temp
        self._unit = unit
        self._support_flags = SUPPORT_FLAGS
        if away_temp:
            self._support_flags = SUPPORT_FLAGS | SUPPORT_PRESET_MODE
        self._away_temp = away_temp
        self._is_away = False
        self.difference = difference
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.pwm = pwm
        self.p = self.i = self.d = 0
        self.hass.custom_attributes = {}
        self.control_output = 0
        self._last_control_output = 0
        self._force_on = False
        self._force_off = False
        self.autotune = autotune
        self.sensor_entity_id = sensor_entity_id
        self.time_changed = time.time()
        if self.autotune != "none":
            self.pidAutotune = pid_controller.PIDAutotune(self._target_temp, self.difference, self._keep_alive.seconds,
                                                          self._keep_alive.seconds, self.minOut, self.maxOut, noiseband,
                                                          time.time)
            _LOGGER.warning("Autotune will run with the next Setpoint Value you set. Changes, submitted after doesn't "
                            "have any effect until it's finished")
        else:
            self.pidController = pid_controller.PIDArduino(self._keep_alive.seconds, self.kp, self.ki, self.kd,
                                                           self.minOut, self.maxOut, time.time)

    async def async_added_to_hass(self):
        """Run when entity about to be added."""
        await super().async_added_to_hass()

        # Add listener
        async_track_state_change(
            self.hass, self.sensor_entity_id, self._async_sensor_changed)
        async_track_state_change(
            self.hass, self.heater_entity_id, self._async_switch_changed)

        if self._keep_alive:
            async_track_time_interval(
                self.hass, self._async_control_heating, self._keep_alive)

        @callback
        def _async_startup(event):
            """Init on startup."""
            sensor_state = self.hass.states.get(self.sensor_entity_id)
            if sensor_state and sensor_state.state != STATE_UNKNOWN:
                self._async_update_temp(sensor_state)

        self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_START, _async_startup)

        # Check If we have an old state
        old_state = await self.async_get_last_state()
        if old_state is not None:
            # If we have no initial temperature, restore
            if self._target_temp is None:
                # If we have a previously saved temperature
                if old_state.attributes.get(ATTR_TEMPERATURE) is None:
                    if self.ac_mode:
                        self._target_temp = self.max_temp
                    else:
                        self._target_temp = self.min_temp
                    _LOGGER.warning("Undefined target temperature, falling back to %s", self._target_temp)
                else:
                    self._target_temp = float(
                        old_state.attributes[ATTR_TEMPERATURE])
            if old_state.attributes.get(ATTR_PRESET_MODE) == PRESET_AWAY:
                self._is_away = True
            if not self._hvac_mode and old_state.state:
                self._hvac_mode = old_state.state

        else:
            # No previous state, try and restore defaults
            if self._target_temp is None:
                if self.ac_mode:
                    self._target_temp = self.max_temp
                else:
                    self._target_temp = self.min_temp
            _LOGGER.warning("No previously saved temperature, setting to %s",
                            self._target_temp)

        # Set default state to off
        if not self._hvac_mode:
            self._hvac_mode = HVAC_MODE_OFF

    @property
    def should_poll(self):
        """Return the polling state."""
        return False

    @property
    def name(self):
        """Return the name of the thermostat."""
        return self._name

    @property
    def precision(self):
        """Return the precision of the system."""
        if self._temp_precision is not None:
            return self._temp_precision
        return super().precision

    @property
    def temperature_unit(self):
        """Return the unit of measurement."""
        return self._unit

    @property
    def current_temperature(self):
        """Return the sensor temperature."""
        return self._cur_temp

    @property
    def hvac_mode(self):
        """Return current operation."""
        return self._hvac_mode

    @property
    def hvac_action(self):
        """Return the current running hvac operation if supported.
        Need to be one of CURRENT_HVAC_*.
        """
        if self._hvac_mode == HVAC_MODE_OFF:
            return CURRENT_HVAC_OFF
        if not self._is_device_active:
            return CURRENT_HVAC_IDLE
        if self.ac_mode:
            return CURRENT_HVAC_COOL
        return CURRENT_HVAC_HEAT

    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        return self._target_temp

    @property
    def hvac_modes(self):
        """List of available operation modes."""
        return self._hvac_list

    @property
    def preset_mode(self):
        """Return the current preset mode, e.g., home, away, temp."""
        if self._is_away:
            return PRESET_AWAY
        return None

    @property
    def preset_modes(self):
        """Return a list of available preset modes."""
        if self._away_temp:
            return [PRESET_AWAY]
        return None

    @property
    def pid_parm(self):
        """Return the pid parameters of the thermostat."""
        return self.kp, self.ki, self.kd

    @property
    def pid_control_output(self):
        """Return the pid control output of the thermostat."""
        return self.control_output

    @property
    def device_state_attributes(self):
        """Return the state attributes of the sensor."""
        return self.hass.custom_attributes

    def update(self):
        attributes = dict()
        attributes['control_output'] = self.pid_control_output
        attributes['p'] = self.p
        attributes['i'] = self.i
        attributes['d'] = self.d
        self.hass.custom_attributes = attributes

    async def async_set_hvac_mode(self, hvac_mode):
        """Set hvac mode."""
        if hvac_mode == HVAC_MODE_HEAT:
            self._hvac_mode = HVAC_MODE_HEAT
            await self._async_control_heating(force=True)
        elif hvac_mode == HVAC_MODE_COOL:
            self._hvac_mode = HVAC_MODE_COOL
            await self._async_control_heating(force=True)
        elif hvac_mode == HVAC_MODE_OFF:
            self._hvac_mode = HVAC_MODE_OFF
            if self._is_device_active:
                await self._async_heater_turn_off()
        else:
            _LOGGER.error("Unrecognized hvac mode: %s", hvac_mode)
            return
        # Ensure we update the current operation after changing the mode
        self.schedule_update_ha_state()

    async def async_set_temperature(self, **kwargs):
        """Set new target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        if temperature > self._target_temp:
            self._force_on = True
        elif temperature < self._target_temp:
            self._force_off = True
        self._target_temp = temperature
        await self._async_control_heating(force=True)
        await self.async_update_ha_state()

    async def async_set_pid(self, kp, ki, kd):
        """Set PID parameters."""

        self.kp = kp
        self.ki = ki
        self.kd = kd
        await self._async_control_heating()
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
        await self._async_control_heating()
        await self.async_update_ha_state()

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
            self._previous_temp = self._cur_temp
            self._cur_temp = float(state.state)
        except ValueError as ex:
            _LOGGER.error("Unable to update from sensor: %s", ex)

    async def _async_control_heating(self, time=None, force=False):
        """Run PID controller, optional autotune for faster integration"""
        async with self._temp_lock:
            if not self._active and None not in (self._cur_temp,
                                                 self._target_temp):
                self._active = True
                _LOGGER.info("Obtained current and target temperature. "
                             "Smart thermostat active. %s, %s",
                             self._cur_temp, self._target_temp)

            if not self._active or self._hvac_mode == HVAC_MODE_OFF:
                return

            # if not force and time is None:
            #    # If the `force` argument is True, we
            #    # ignore `min_cycle_duration`.
            #    # If the `time` argument is not none, we were invoked for
            #    # keep-alive purposes, and `min_cycle_duration` is irrelevant.
            #    if self.min_cycle_duration:
            #        if self._is_device_active:
            #            current_state = STATE_ON
            #        else:
            #            current_state = STATE_OFF
            #        long_enough = condition.state(
            #            self.hass, self.heater_entity_id, current_state,
            #            self.min_cycle_duration)
            #        if not long_enough:
            #            return

            # self.calc_output()
            await self.calc_output()

    @property
    def _is_device_active(self):
        """If the toggleable device is currently active."""
        return self.hass.states.is_state(self.heater_entity_id, STATE_ON)

    @property
    def supported_features(self):
        """Return the list of supported features."""
        return self._support_flags

    async def _async_heater_turn_on(self):
        """Turn heater toggleable device on."""
        data = {ATTR_ENTITY_ID: self.heater_entity_id}
        await self.hass.services.async_call(HA_DOMAIN, SERVICE_TURN_ON, data)

    async def _async_heater_turn_off(self):
        """Turn heater toggleable device off."""
        data = {ATTR_ENTITY_ID: self.heater_entity_id}
        await self.hass.services.async_call(HA_DOMAIN, SERVICE_TURN_OFF, data)

    async def async_set_preset_mode(self, preset_mode: str):
        """Set new preset mode.
        This method must be run in the event loop and returns a coroutine.
        """
        if preset_mode == PRESET_AWAY and not self._is_away:
            self._is_away = True
            self._saved_target_temp = self._target_temp
            self._target_temp = self._away_temp
            await self._async_control_heating(force=True)
        elif not preset_mode and self._is_away:
            self._is_away = False
            self._target_temp = self._saved_target_temp
            await self._async_control_heating(force=True)

        await self.async_update_ha_state()

    async def calc_output(self):
        """calculate control output and handle autotune"""
        if self._previous_temp_time is None:
            self._previous_temp_time = time.time()
        if self._cur_temp_time is None:
            self._cur_temp_time = time.time()
        if self.autotune != "none":
            if self.pidAutotune.run(self._cur_temp):
                params = self.pidAutotune.get_pid_parameters(self.autotune)
                self.kp = params.Kp
                self.ki = params.Ki
                self.kd = params.Kd
                _LOGGER.warning("Set Kp, Ki, Kd. Smart thermostat now runs on PID Controller. %s,  %s,  %s", self.kp,
                                self.ki, self.kd)
                self.pidController = pid_controller.PIDArduino(self._keep_alive.seconds, self.kp, self.ki, self.kd,
                                                               self.minOut, self.maxOut, time.time)
                self.autotune = "none"
            self.control_output = self.pidAutotune.output
            self.p = self.i = self.d = 0
        else:
            self.control_output, self.p, self.i, self.d = self.pidController.calc(self._cur_temp, self._target_temp,
                                                                   self._cur_temp_time, self._previous_temp_time)
        if self.control_output != self._last_control_output:
            _LOGGER.info("Obtained current control output. %s (p=%s, i=%s, d=%s)", self.control_output, self.p, self.i,
                         self.d)
        await self.set_control_value()
        self._last_control_output = self.control_output

    async def set_control_value(self):
        """Set Output value for heater"""
        if self.pwm:
            if self.control_output == self.difference or self.control_output == -self.difference:
                if not self._is_device_active:
                    if self.control_output != self._last_control_output:
                        _LOGGER.info("Turning on %s", self.heater_entity_id)
                    await self._async_heater_turn_on()
                    self.time_changed = time.time()
            elif self.control_output > 0:
                await self.pwm_switch(self.pwm * self.control_output / self.maxOut,
                                      self.pwm * (self.maxOut - self.control_output) / self.maxOut,
                                      time.time() - self.time_changed)
            elif self.control_output < 0:
                await self.pwm_switch(self.pwm * self.control_output / self.minOut,
                                      self.pwm * self.minOut / self.control_output,
                                      time.time() - self.time_changed)
            else:
                if self._active:
                    if self.control_output != self._last_control_output:
                        _LOGGER.info("Turning off %s", self.heater_entity_id)
                    await self._async_heater_turn_off()
                    self.time_changed = time.time()
        else:
            if self.control_output != self._last_control_output:
                _LOGGER.info("Change state of %s to %s", self.heater_entity_id, round(self.control_output, 2))
            self.hass.states.async_set(self.heater_entity_id, self.control_output)

    async def pwm_switch(self, time_on, time_off, time_passed):
        """turn off and on the heater proportionally to control_value."""
        if self._is_device_active:
            if time_on < time_passed or self._force_off:
                if self.control_output != self._last_control_output:
                    _LOGGER.info("Turning off %s", self.heater_entity_id)
                await self._async_heater_turn_off()
                self.time_changed = time.time()
            else:
                _LOGGER.info("Time until %s turns off: %s sec", self.heater_entity_id, int(time_on - time_passed))
        else:
            if time_off < time_passed or self._force_on:
                if self.control_output != self._last_control_output:
                    _LOGGER.info("Turning on %s", self.heater_entity_id)
                await self._async_heater_turn_on()
                self.time_changed = time.time()
            else:
                _LOGGER.info("Time until %s turns on: %s sec", self.heater_entity_id, int(time_off - time_passed))
        self._force_on = False
        self._force_off = False
