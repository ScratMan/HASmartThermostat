"""Durations longer than one day must be fully counted (timedelta.seconds drops days)."""

from datetime import timedelta

from custom_components.smart_thermostat.climate import SmartThermostat


def test_durations_over_one_day_are_fully_supported():
    """_pwm, _sensor_stall, _lookback and _sampling_period must keep their whole days."""
    thermostat = SmartThermostat(
        name="Unit Test Thermostat",
        heater_entity_id=["switch.heater"],
        sensor_entity_id="sensor.temperature",
        target_temp=20.0,
        keep_alive=timedelta(seconds=60),
        pwm=timedelta(days=1, hours=2),  # 93600 s
        sensor_stall=timedelta(days=2),  # 172800 s
        lookback=timedelta(days=3),  # 259200 s
        sampling_period=timedelta(days=1, hours=1),  # 90000 s
        kp=100.0,
        ki=0.0,
        kd=0.0,
    )
    assert thermostat._pwm == 93600
    assert thermostat._sensor_stall == 172800
    assert thermostat._lookback == 259200
    # _sampling_period keeps the full timedelta, and the PID receives total seconds
    assert thermostat._sampling_period == timedelta(days=1, hours=1)
    assert thermostat._pid_controller.sampling_period == 90000
