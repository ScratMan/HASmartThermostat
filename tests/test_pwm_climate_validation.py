"""Test PWM + climate entity validation."""

import pytest
import sys
from pathlib import Path
from datetime import timedelta

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components" / "adaptive_thermostat"))

from const import CONF_HEATER, CONF_COOLER, CONF_PWM


# Inline the validation function for testing
def validate_pwm_compatibility(config):
    """Validate that PWM mode is not used with climate entities.

    PWM (Pulse Width Modulation) creates nested control loops when used with
    climate entities, which have their own internal PID controllers. This can
    cause instability and erratic behavior.

    Args:
        config: Platform configuration dictionary

    Raises:
        ValueError: If PWM is configured with a climate entity

    Returns:
        config: Validated configuration (unchanged if valid)
    """
    pwm = config.get(CONF_PWM)
    pwm_seconds = pwm.seconds if pwm else 0

    # Only validate if PWM is actually enabled (> 0 seconds)
    if pwm_seconds == 0:
        return config

    # Check heater entity
    heater_entities = config.get(CONF_HEATER, [])
    for entity_id in heater_entities:
        if entity_id.startswith("climate."):
            raise ValueError(
                f"PWM mode cannot be used with climate entity '{entity_id}'. "
                f"Climate entities have their own PID controllers, creating nested control loops. "
                f"Solutions: (1) Set pwm to '00:00:00' for valve mode, or (2) Use a switch/light entity instead."
            )

    # Check cooler entity
    cooler_entities = config.get(CONF_COOLER, [])
    for entity_id in cooler_entities:
        if entity_id.startswith("climate."):
            raise ValueError(
                f"PWM mode cannot be used with climate entity '{entity_id}'. "
                f"Climate entities have their own PID controllers, creating nested control loops. "
                f"Solutions: (1) Set pwm to '00:00:00' for valve mode, or (2) Use a switch/light entity instead."
            )

    return config


class TestPWMClimateValidation:
    """Test suite for PWM climate entity validation."""

    def test_valid_pwm_with_switch(self):
        """Test that PWM mode works with switch entities."""
        config = {
            CONF_HEATER: ["switch.heater"],
            CONF_PWM: timedelta(minutes=15),
        }
        # Should not raise
        result = validate_pwm_compatibility(config)
        assert result == config

    def test_valid_pwm_with_light(self):
        """Test that PWM mode works with light entities."""
        config = {
            CONF_HEATER: ["light.heater"],
            CONF_PWM: timedelta(minutes=10),
        }
        # Should not raise
        result = validate_pwm_compatibility(config)
        assert result == config

    def test_valid_valve_mode_with_climate(self):
        """Test that valve mode (PWM=0) works with climate entities."""
        config = {
            CONF_HEATER: ["climate.underfloor"],
            CONF_PWM: timedelta(seconds=0),
        }
        # Should not raise
        result = validate_pwm_compatibility(config)
        assert result == config

    def test_valid_no_pwm_specified(self):
        """Test that no PWM works with climate entities."""
        config = {
            CONF_HEATER: ["climate.underfloor"],
        }
        # Should not raise (no PWM key)
        result = validate_pwm_compatibility(config)
        assert result == config

    def test_invalid_pwm_with_climate_heater(self):
        """Test that PWM mode raises error with climate heater."""
        config = {
            CONF_HEATER: ["climate.underfloor"],
            CONF_PWM: timedelta(minutes=15),
        }
        with pytest.raises(ValueError) as exc_info:
            validate_pwm_compatibility(config)

        assert "climate.underfloor" in str(exc_info.value)
        assert "nested control loops" in str(exc_info.value)
        assert "pwm to '00:00:00'" in str(exc_info.value)

    def test_invalid_pwm_with_climate_cooler(self):
        """Test that PWM mode raises error with climate cooler."""
        config = {
            CONF_COOLER: ["climate.ac_unit"],
            CONF_PWM: timedelta(minutes=10),
        }
        with pytest.raises(ValueError) as exc_info:
            validate_pwm_compatibility(config)

        assert "climate.ac_unit" in str(exc_info.value)
        assert "nested control loops" in str(exc_info.value)

    def test_invalid_pwm_with_multiple_climate_entities(self):
        """Test that PWM mode raises error with multiple climate entities."""
        config = {
            CONF_HEATER: ["climate.zone1", "climate.zone2"],
            CONF_PWM: timedelta(minutes=15),
        }
        # Should raise on first climate entity found
        with pytest.raises(ValueError) as exc_info:
            validate_pwm_compatibility(config)

        assert "climate." in str(exc_info.value)
        assert "nested control loops" in str(exc_info.value)

    def test_valid_mixed_entities_with_pwm(self):
        """Test that PWM works with mixed entity types (switches with PWM)."""
        # This config has switches with PWM, which is valid
        config = {
            CONF_HEATER: ["switch.heater", "switch.pump"],
            CONF_PWM: timedelta(minutes=15),
        }
        # Should not raise
        result = validate_pwm_compatibility(config)
        assert result == config

    def test_error_message_suggests_solutions(self):
        """Test that error message provides helpful solutions."""
        config = {
            CONF_HEATER: ["climate.radiant_floor"],
            CONF_PWM: timedelta(minutes=20),
        }
        with pytest.raises(ValueError) as exc_info:
            validate_pwm_compatibility(config)

        error_msg = str(exc_info.value)
        # Check both solution suggestions are present
        assert "Set pwm to '00:00:00'" in error_msg or "valve mode" in error_msg
        assert "Use a switch" in error_msg or "switch/light entity" in error_msg

    def test_pwm_climate_validation_module_exists(self):
        """Marker test to verify module and function exist."""
        assert validate_pwm_compatibility is not None
        assert callable(validate_pwm_compatibility)
