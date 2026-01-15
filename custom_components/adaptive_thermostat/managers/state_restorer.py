"""State restoration manager for Adaptive Thermostat integration."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from homeassistant.core import State
    from ..climate import AdaptiveThermostat

_LOGGER = logging.getLogger(__name__)


class StateRestorer:
    """Manager for restoring thermostat state from Home Assistant's state restoration.

    Handles restoration of:
    - Target temperature setpoint
    - Active preset mode
    - HVAC mode
    - PID controller values (integral, gains, mode)
    """

    def __init__(self, thermostat: AdaptiveThermostat) -> None:
        """Initialize the StateRestorer.

        Args:
            thermostat: Reference to the parent thermostat entity
        """
        self._thermostat = thermostat

    def restore(self, old_state: Optional[State]) -> None:
        """Restore all state from a previous session.

        This is the main entry point that orchestrates the full restoration
        process by calling both _restore_state and _restore_pid_values.

        Args:
            old_state: The restored state object from async_get_last_state(),
                      or None if no previous state exists.
        """
        self._restore_state(old_state)
        if old_state is not None:
            self._restore_pid_values(old_state)

    def _restore_state(self, old_state: Optional[State]) -> None:
        """Restore climate entity state from Home Assistant's state restoration.

        This method restores:
        - Target temperature setpoint
        - Active preset mode
        - HVAC mode

        Note: Preset temperatures are not restored as they now come from controller config.

        Args:
            old_state: The restored state object from async_get_last_state(),
                      or None if no previous state exists.
        """
        # Import here to avoid circular imports
        from homeassistant.const import ATTR_TEMPERATURE
        from homeassistant.components.climate import ATTR_PRESET_MODE

        thermostat = self._thermostat

        if old_state is not None:
            # Restore target temperature
            if old_state.attributes.get(ATTR_TEMPERATURE) is None:
                if thermostat._target_temp is None:
                    if thermostat._ac_mode:
                        thermostat._target_temp = thermostat.max_temp
                    else:
                        thermostat._target_temp = thermostat.min_temp
                _LOGGER.warning("%s: No setpoint available in old state, falling back to %s",
                                thermostat.entity_id, thermostat._target_temp)
            else:
                thermostat._target_temp = float(old_state.attributes.get(ATTR_TEMPERATURE))

            # Restore preset mode
            if old_state.attributes.get(ATTR_PRESET_MODE) is not None:
                thermostat._attr_preset_mode = old_state.attributes.get(ATTR_PRESET_MODE)
                # Sync to temperature manager if initialized
                if thermostat._temperature_manager:
                    thermostat._temperature_manager.restore_state(
                        preset_mode=thermostat._attr_preset_mode,
                        saved_target_temp=thermostat._saved_target_temp,
                    )

            # Restore HVAC mode
            if not thermostat._hvac_mode and old_state.state:
                thermostat.set_hvac_mode(old_state.state)
        else:
            # No previous state, set defaults
            if thermostat._target_temp is None:
                if thermostat._ac_mode:
                    thermostat._target_temp = thermostat.max_temp
                else:
                    thermostat._target_temp = thermostat.min_temp
            _LOGGER.warning("%s: No setpoint to restore, setting to %s", thermostat.entity_id,
                            thermostat._target_temp)

    def _restore_pid_values(self, old_state: State) -> None:
        """Restore PID controller values from Home Assistant's state restoration.

        This method restores:
        - PID integral value (pid_i)
        - PID gains: Kp, Ki, Kd, Ke (supports both lowercase and uppercase attribute names)
        - PID mode (auto/off)

        Args:
            old_state: The restored state object from async_get_last_state().
                      Must not be None.
        """
        thermostat = self._thermostat

        if old_state is None or thermostat._pid_controller is None:
            return

        # Restore PID integral value with migration for v0.7.0 dimensional fix
        # In v0.6.x and earlier, integral was accumulated with dt in seconds
        # In v0.7.0+, integral uses dt in hours, so we need to multiply by 3600
        if isinstance(old_state.attributes.get('pid_i'), (float, int)):
            old_integral = float(old_state.attributes.get('pid_i'))
            # Check if migration is needed by looking for version marker
            # If no marker exists, assume old version and migrate
            needs_migration = old_state.attributes.get('pid_integral_migrated') != True

            if needs_migration and old_integral != 0:
                # Migrate: old integral was in %·seconds, new integral is in %·hours
                # So multiply by 3600 to convert seconds to hours
                thermostat._i = old_integral * 3600.0
                _LOGGER.info(
                    "%s: Migrated PID integral from v0.6.x (seconds) to v0.7.0+ (hours): "
                    "%.4f -> %.4f",
                    thermostat.entity_id, old_integral, thermostat._i
                )
            else:
                thermostat._i = old_integral

            thermostat._pid_controller.integral = thermostat._i

        # Restore Kp (supports both 'kp' and 'Kp')
        if old_state.attributes.get('kp') is not None:
            thermostat._kp = float(old_state.attributes.get('kp'))
            thermostat._pid_controller.set_pid_param(kp=thermostat._kp)
        elif old_state.attributes.get('Kp') is not None:
            thermostat._kp = float(old_state.attributes.get('Kp'))
            thermostat._pid_controller.set_pid_param(kp=thermostat._kp)

        # Restore Ki (supports both 'ki' and 'Ki')
        if old_state.attributes.get('ki') is not None:
            thermostat._ki = float(old_state.attributes.get('ki'))
            thermostat._pid_controller.set_pid_param(ki=thermostat._ki)
        elif old_state.attributes.get('Ki') is not None:
            thermostat._ki = float(old_state.attributes.get('Ki'))
            thermostat._pid_controller.set_pid_param(ki=thermostat._ki)

        # Restore Kd (supports both 'kd' and 'Kd')
        if old_state.attributes.get('kd') is not None:
            thermostat._kd = float(old_state.attributes.get('kd'))
            thermostat._pid_controller.set_pid_param(kd=thermostat._kd)
        elif old_state.attributes.get('Kd') is not None:
            thermostat._kd = float(old_state.attributes.get('Kd'))
            thermostat._pid_controller.set_pid_param(kd=thermostat._kd)

        # Restore Ke (supports both 'ke' and 'Ke') with migration for v0.7.0 scaling fix
        # In v0.6.x and earlier, Ke values were 100x larger
        # In v0.7.0+, Ke scaled by 1/100 to match corrected Ki dimensional analysis
        ke_value = None
        if old_state.attributes.get('ke') is not None:
            ke_value = float(old_state.attributes.get('ke'))
        elif old_state.attributes.get('Ke') is not None:
            ke_value = float(old_state.attributes.get('Ke'))

        if ke_value is not None:
            # Check if migration is needed by looking for version marker
            # If no marker exists, assume old version and migrate if Ke > 0.05
            ke_migrated = old_state.attributes.get('ke_migrated') == True

            if not ke_migrated and ke_value > 0.05:
                # Migrate: old Ke was 100x larger, divide by 100
                thermostat._ke = ke_value / 100.0
                _LOGGER.info(
                    "%s: Migrated Ke from v0.6.x to v0.7.0+ (100x scaling): "
                    "%.4f -> %.4f",
                    thermostat.entity_id, ke_value, thermostat._ke
                )
            else:
                thermostat._ke = ke_value

            thermostat._pid_controller.set_pid_param(ke=thermostat._ke)

        _LOGGER.info("%s: Restored PID values - Kp=%.4f, Ki=%.5f, Kd=%.3f, Ke=%s",
                     thermostat.entity_id, thermostat._kp, thermostat._ki, thermostat._kd, thermostat._ke or 0)

        # Restore PID mode
        if old_state.attributes.get('pid_mode') is not None:
            thermostat._pid_controller.mode = old_state.attributes.get('pid_mode')
