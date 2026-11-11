"""Tests for PID integral stability across setpoint changes, trapezoidal rule (#329), and anti-windup (#326)."""

import pytest

from custom_components.smart_thermostat.pid_controller import PID


def test_pid_setpoint_change_trapezoidal_and_unwinding():
    """Verify no integral kick on setpoint change, proper trapezoidal integration, and unwinding with Ke."""
    # Setup similar to a bathroom configuration:
    # Kp=50, Ki=0.02, Kd=0, Ke=1.5, output bounded between 0 and 100
    pid = PID(kp=50.0, ki=0.02, kd=0.0, ke=1.5, out_min=0.0, out_max=100.0)

    t0 = 10000.0
    ext_temp = 15.0  # Setpoint 24°C -> E = 1.5 * (24 - 15) = +13.5

    # 1. t0 (05:30): First sample at 23.8°C for a 24.0°C setpoint (Error = +0.2°C)
    out, updated = pid.calc(
        input_val=23.8,
        set_point=24.0,
        input_time=t0,
        last_input_time=None,
        ext_temp=ext_temp,
    )
    assert updated is True
    assert pid.integral == pytest.approx(0.0)
    assert pid.external == pytest.approx(13.5)

    # 2. t1 = t0 + 900s (05:45): New sensor report at 23.9°C (Error = +0.1°C)
    # Trapezoidal rule: average between +0.2 and +0.1 = +0.15°C over 900s
    # dI = 0.02 * 0.15 * 900 = +2.7
    t1 = t0 + 900.0
    out, updated = pid.calc(
        input_val=23.9,
        set_point=24.0,
        input_time=t1,
        last_input_time=t0,
        ext_temp=ext_temp,
    )
    assert pid.integral == pytest.approx(2.7)

    # Simulate an already high integral in steady state before 06:00 (e.g., I = 67.0)
    pid.integral = 67.0

    # 3. t2 = t1 + 900s (06:00:00.000): CLOSING STEP 1 (_async_close_previous_period)
    # Before lowering the setpoint to 21°C, settle the elapsed period using the previous setpoint (24°C)
    # Error remains +0.1°C -> dI = 0.02 * 0.1 * 900 = +1.8 -> I increases to 68.8
    t2 = t1 + 900.0
    out, updated = pid.calc(
        input_val=23.9,
        set_point=24.0,
        input_time=t2,
        last_input_time=t1,
        ext_temp=ext_temp,
    )
    assert pid.integral == pytest.approx(68.8)

    # 4. t2 (06:00:00.001): CLOSING STEP 2 - Apply new setpoint at 21.0°C with dt = 0
    # Error flips to -2.9°C (21.0 - 23.9), but dt=0: the integral MUST NOT DROP!
    # Total output (P + I + E) goes negative (-145 + 68.8 + 9.0 = -67.2), saturating low output at 0.
    out, updated = pid.calc(
        input_val=23.9,
        set_point=21.0,
        input_time=t2,
        last_input_time=t2,
        ext_temp=ext_temp,
    )
    assert pid.integral == pytest.approx(68.8)
    assert pid.derivative == pytest.approx(0.0)  # No derivative kick
    assert pid.external == pytest.approx(9.0)  # 1.5 * (21.0 - 15.0)
    assert out < 0.0  # Raw output requests full stop (clamped to 0 downstream)

    # 5. t3 = t2 + 900s (06:15): Next sensor report during cooldown (23.0°C)
    # Anti-windup test (#326): even though previous output was saturated low (out <= 0),
    # I (68.8) is > neutral_i (-9.0). The integral MUST unwind!
    # Trapezoid between error at t2 (-2.9°C) and error at t3 (-2.0°C) -> average = -2.45°C
    # dI = 0.02 * (-2.45) * 900 = -44.1 -> I drops from 68.8 to 24.7
    t3 = t2 + 900.0
    out, updated = pid.calc(
        input_val=23.0,
        set_point=21.0,
        input_time=t3,
        last_input_time=t2,
        ext_temp=ext_temp,
    )
    assert pid.integral == pytest.approx(24.7)

    # 6. t4 = t3 + 1800s (06:45): Room stays warm at 22.5°C (Error = -1.5°C)
    # Trapezoid between -2.0 and -1.5 = -1.75°C over 1800s -> dI = 0.02 * (-1.75) * 1800 = -63.0
    # 24.7 - 63.0 = -38.3, but integral must clamp at i_min = out_min - external = -9.0
    t4 = t3 + 1800.0
    out, updated = pid.calc(
        input_val=22.5,
        set_point=21.0,
        input_time=t4,
        last_input_time=t3,
        ext_temp=ext_temp,
    )
    assert pid.integral == pytest.approx(-9.0)


def test_trapezoidal_rule_sudden_heat_spike():
    """Verify #329: sudden heat spike after a long stable period uses average error."""
    pid = PID(kp=10.0, ki=0.007, kd=0.0, out_min=0.0, out_max=100.0)
    t0 = 1000.0

    # Temperature stable at 19.96°C for a 20.0°C setpoint (Error = +0.04°C)
    pid.calc(input_val=19.96, set_point=20.0, input_time=t0, last_input_time=None)
    pid.integral = 7.9

    # 55 minutes later (3292s), an oven raises room temperature to 20.57°C (Error = -0.57°C)
    # Without trapezoid: 7.9 + 0.007 * (-0.57) * 3292 = -5.23 (sharp drop)
    # With trapezoid: average = 0.5 * (0.04 - 0.57) = -0.265°C
    # dI = 0.007 * (-0.265) * 3292 = -6.10666 -> I = 7.9 - 6.10666 = 1.79334
    t1 = t0 + 3292.0
    pid.calc(input_val=20.57, set_point=20.0, input_time=t1, last_input_time=t0)
    assert pid.integral == pytest.approx(1.79334, rel=1e-4)
