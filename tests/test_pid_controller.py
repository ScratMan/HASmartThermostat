"""Tests for PID controller."""
import pytest
import sys
from pathlib import Path

# Add parent directory to path to import pid_controller
sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components" / "adaptive_thermostat"))

from pid_controller import PID


class TestPIDController:
    """Test PID controller output calculation."""

    def test_pid_output_calculation(self):
        """Test basic PID output calculation."""
        # Create PID controller with known parameters
        pid = PID(kp=10, ki=0.5, kd=2, out_min=0, out_max=100)

        # Set initial conditions
        input_val = 20.0
        set_point = 22.0
        input_time = 0.0

        # Calculate output
        output, changed = pid.calc(input_val, set_point, input_time=input_time, last_input_time=None)

        # Should produce output since error exists (setpoint - input = 2.0)
        assert changed is True
        assert output > 0  # Should be heating
        assert 0 <= output <= 100  # Within bounds

        # Check error is correct
        assert pid.error == 2.0

        # Check proportional term
        assert pid.proportional == 20.0  # Kp * error = 10 * 2.0

    def test_pid_output_limits(self):
        """Test PID output respects min/max limits."""
        # Create PID with tight limits
        pid = PID(kp=100, ki=10, kd=5, out_min=0, out_max=50)

        # Large error should clamp to max
        output, _ = pid.calc(input_val=10.0, set_point=30.0, input_time=0.0)
        assert output <= 50.0
        assert output >= 0.0

        # Create PID with negative scenario
        pid2 = PID(kp=100, ki=10, kd=5, out_min=-50, out_max=100)

        # Negative error should produce appropriate output
        output2, _ = pid2.calc(input_val=30.0, set_point=10.0, input_time=0.0)
        assert output2 >= -50.0
        assert output2 <= 100.0

    def test_integral_windup_prevention(self):
        """Test integral windup prevention."""
        # Create PID controller
        pid = PID(kp=5, ki=1, kd=0, out_min=0, out_max=100)

        # First calculation establishes baseline
        output1, _ = pid.calc(input_val=20.0, set_point=25.0, input_time=0.0)
        initial_integral = pid.integral

        # Second calculation at output limit (simulate saturation)
        # Force output to be at max by making large error
        pid.calc(input_val=0.0, set_point=100.0, input_time=1.0)

        # Third calculation should not accumulate integral when saturated
        # The integral should be clamped
        output3, _ = pid.calc(input_val=0.0, set_point=100.0, input_time=2.0)

        # Output should be clamped at max
        assert output3 == 100.0

        # Integral should be limited to prevent windup
        assert pid.integral <= 100.0

    def test_pid_mode_off(self):
        """Test PID behavior when mode is OFF."""
        # Create PID controller
        pid = PID(kp=10, ki=0.5, kd=2, out_min=0, out_max=100,
                  cold_tolerance=0.3, hot_tolerance=0.3)

        # Set mode to OFF
        pid.mode = 'OFF'

        # Below setpoint - cold tolerance: should turn on (max output)
        output, changed = pid.calc(input_val=19.5, set_point=20.0, input_time=0.0)
        assert changed is True
        assert output == 100.0

        # Above setpoint + hot tolerance: should turn off (min output)
        output, changed = pid.calc(input_val=20.5, set_point=20.0, input_time=1.0)
        assert changed is True
        assert output == 0.0

        # Within tolerance band: should not change
        output, changed = pid.calc(input_val=20.1, set_point=20.0, input_time=2.0)
        assert changed is False

    def test_external_temperature_compensation(self):
        """Test ke parameter for outdoor temperature compensation."""
        # Create PID with outdoor compensation
        pid = PID(kp=10, ki=0.5, kd=2, ke=0.8, out_min=0, out_max=100)

        # Calculate with external temperature
        output_with_ext, _ = pid.calc(
            input_val=20.0,
            set_point=22.0,
            input_time=0.0,
            ext_temp=5.0
        )

        # External term should be: ke * (setpoint - ext_temp) = 0.8 * (22 - 5) = 13.6
        assert pid.external == pytest.approx(13.6, rel=0.01)

        # Output should include external compensation
        assert output_with_ext > 0

    def test_set_pid_parameters(self):
        """Test updating PID parameters."""
        pid = PID(kp=10, ki=0.5, kd=2, out_min=0, out_max=100)

        # Update parameters
        pid.set_pid_param(kp=20, ki=1.0, kd=5.0, ke=0.5)

        # Verify they were updated
        assert pid._Kp == 20
        assert pid._Ki == 1.0
        assert pid._Kd == 5.0
        assert pid._Ke == 0.5

    def test_clear_samples(self):
        """Test clearing PID samples."""
        pid = PID(kp=10, ki=0.5, kd=2, out_min=0, out_max=100)

        # Run a calculation
        pid.calc(input_val=20.0, set_point=22.0, input_time=0.0)

        # Clear samples
        pid.clear_samples()

        # Verify samples are cleared
        assert pid._input is None
        assert pid._input_time is None
        assert pid._last_input is None
        assert pid._last_input_time is None

    def test_sampling_period_mode_respects_timing(self):
        """Test that sampling period mode skips calculations when called too frequently.

        This tests the fix for the timing bug where time() - self._input_time was
        incorrectly used instead of time() - self._last_input_time.
        """
        from unittest.mock import patch

        # Create PID with 60 second sampling period
        pid = PID(kp=10, ki=0.5, kd=2, out_min=0, out_max=100, sampling_period=60)

        # Mock time() to control the timing
        mock_time = 1000.0

        with patch('pid_controller.time', return_value=mock_time):
            # First calculation should always run (no last_input_time yet)
            output1, changed1 = pid.calc(input_val=20.0, set_point=22.0)
            assert changed1 is True
            assert pid._input_time == 1000.0
            # After first call, _last_input_time is set from previous _input_time (was None)
            assert pid._last_input_time is None

        # Second call at t=1030 (30s later) - still runs because _last_input_time
        # becomes set after this call (it gets the previous _input_time)
        mock_time = 1030.0
        with patch('pid_controller.time', return_value=mock_time):
            output2, changed2 = pid.calc(input_val=20.5, set_point=22.0)
            assert changed2 is True  # Runs because _last_input_time was still None
            assert pid._last_input_time == 1000.0  # Now set from previous _input_time
            assert pid._input_time == 1030.0

        # Third call at t=1040 (10s after second call) - should be SKIPPED
        # because 10s < 60s sampling period
        mock_time = 1040.0
        with patch('pid_controller.time', return_value=mock_time):
            output3, changed3 = pid.calc(input_val=21.0, set_point=22.0)
            assert changed3 is False  # Skipped - too soon
            assert output3 == output2  # Returns cached output
            # Timestamps should NOT be updated when skipped
            assert pid._last_input_time == 1000.0
            assert pid._input_time == 1030.0

        # Fourth call at t=1100 (70s after second call's _last_input_time)
        # Should run: 1100 - 1000 = 100s > 60s sampling period
        mock_time = 1100.0
        with patch('pid_controller.time', return_value=mock_time):
            output4, changed4 = pid.calc(input_val=21.5, set_point=22.0)
            assert changed4 is True
            # Error is now 0.5 (22 - 21.5)
            assert pid.error == 0.5
            assert pid._last_input_time == 1030.0  # Updated to previous _input_time
            assert pid._input_time == 1100.0

    def test_event_driven_mode_timestamp_validation(self, caplog):
        """Test that event-driven mode logs warning when timestamp not provided.

        When sampling_period=0, the controller operates in event-driven mode
        and expects timestamps to be provided via input_time parameter.
        """
        import logging

        # Create PID in event-driven mode (sampling_period=0)
        pid = PID(kp=10, ki=0.5, kd=2, out_min=0, out_max=100, sampling_period=0)

        # Call without providing input_time - should log warning
        with caplog.at_level(logging.WARNING):
            output, changed = pid.calc(input_val=20.0, set_point=22.0)

        # Should have logged a warning about missing timestamp
        assert "event-driven mode" in caplog.text
        assert "input_time" in caplog.text

        # Should still calculate output (using time() as fallback)
        assert changed is True
        assert pid.error == 2.0

        # Clear log for next test
        caplog.clear()

        # Call with input_time provided - should NOT log warning
        with caplog.at_level(logging.WARNING):
            output2, changed2 = pid.calc(
                input_val=21.0,
                set_point=22.0,
                input_time=100.0,
                last_input_time=0.0
            )

        # No warning should be logged when timestamp is provided
        assert "event-driven mode" not in caplog.text
        assert changed2 is True

        # Verify dt was calculated correctly
        assert pid.dt == 100.0  # input_time - last_input_time = 100 - 0

    def test_integral_reset_on_setpoint_change_without_ext_temp(self):
        """Test that integral resets on setpoint change even without ext_temp.

        This tests the fix for inconsistent integral reset behavior where
        the integral was only reset when ext_temp was provided.
        """
        pid = PID(kp=10, ki=1.0, kd=0, out_min=0, out_max=100)

        # Build up integral with constant setpoint over multiple cycles
        pid.calc(input_val=20.0, set_point=22.0, input_time=0.0, last_input_time=None)
        pid.calc(input_val=20.5, set_point=22.0, input_time=1.0, last_input_time=0.0)
        pid.calc(input_val=21.0, set_point=22.0, input_time=2.0, last_input_time=1.0)

        # Integral should have accumulated (Ki=1.0, error reduces over time)
        integral_before = pid.integral
        assert integral_before != 0, "Integral should have accumulated"

        # Change setpoint WITHOUT providing ext_temp
        pid.calc(input_val=21.0, set_point=25.0, input_time=3.0, last_input_time=2.0)

        # Integral should be reset to 0 regardless of ext_temp presence
        assert pid.integral == 0, "Integral should be reset on setpoint change"

    def test_mode_switch_off_to_auto_clears_samples(self):
        """Test that switching from OFF to AUTO clears samples.

        When PID is in OFF mode, it uses simple bang-bang control. The timestamps
        and input values from OFF mode are stale and should not be used for
        derivative calculations when switching to AUTO mode.
        """
        pid = PID(kp=10, ki=0.5, kd=2, out_min=0, out_max=100)

        # Run some calculations in AUTO mode to populate samples
        pid.calc(input_val=20.0, set_point=22.0, input_time=0.0, last_input_time=None)
        pid.calc(input_val=20.5, set_point=22.0, input_time=1.0, last_input_time=0.0)

        # Verify samples exist
        assert pid._input is not None
        assert pid._input_time is not None
        assert pid._last_input is not None

        # Switch to OFF mode
        pid.mode = 'OFF'

        # Samples should still exist (OFF mode doesn't clear)
        assert pid._input is not None

        # Run in OFF mode (this won't update samples meaningfully)
        pid.calc(input_val=19.0, set_point=22.0, input_time=100.0)

        # Switch back to AUTO - this should clear samples
        pid.mode = 'AUTO'

        # Samples should be cleared for fresh PID calculation
        assert pid._input is None
        assert pid._input_time is None
        assert pid._last_input is None
        assert pid._last_input_time is None

        # First calculation after mode switch should work correctly
        output, changed = pid.calc(input_val=21.0, set_point=22.0, input_time=200.0)
        assert changed is True
        assert output > 0  # Should be heating

    def test_nan_inf_input_validation(self):
        """Test that NaN and Inf inputs return cached output without corrupting state.

        Invalid sensor readings (NaN, Inf) should not corrupt the PID controller
        state. Instead, the cached output should be returned.
        """
        import math

        pid = PID(kp=10, ki=0.5, kd=2, out_min=0, out_max=100)

        # First valid calculation to establish baseline
        output1, changed1 = pid.calc(
            input_val=20.0, set_point=22.0,
            input_time=0.0, last_input_time=None
        )
        assert changed1 is True
        baseline_output = output1

        # NaN input_val should return cached output
        output2, changed2 = pid.calc(
            input_val=float('nan'), set_point=22.0,
            input_time=1.0, last_input_time=0.0
        )
        assert changed2 is False
        assert output2 == baseline_output

        # Inf input_val should return cached output
        output3, changed3 = pid.calc(
            input_val=float('inf'), set_point=22.0,
            input_time=2.0, last_input_time=1.0
        )
        assert changed3 is False
        assert output3 == baseline_output

        # Negative Inf input_val should return cached output
        output4, changed4 = pid.calc(
            input_val=float('-inf'), set_point=22.0,
            input_time=3.0, last_input_time=2.0
        )
        assert changed4 is False
        assert output4 == baseline_output

        # NaN set_point should return cached output
        output5, changed5 = pid.calc(
            input_val=20.0, set_point=float('nan'),
            input_time=4.0, last_input_time=3.0
        )
        assert changed5 is False
        assert output5 == baseline_output

        # Inf set_point should return cached output
        output6, changed6 = pid.calc(
            input_val=20.0, set_point=float('inf'),
            input_time=5.0, last_input_time=4.0
        )
        assert changed6 is False
        assert output6 == baseline_output

        # NaN ext_temp should return cached output
        output7, changed7 = pid.calc(
            input_val=20.0, set_point=22.0,
            input_time=6.0, last_input_time=5.0,
            ext_temp=float('nan')
        )
        assert changed7 is False
        assert output7 == baseline_output

        # Inf ext_temp should return cached output
        output8, changed8 = pid.calc(
            input_val=20.0, set_point=22.0,
            input_time=7.0, last_input_time=6.0,
            ext_temp=float('inf')
        )
        assert changed8 is False
        assert output8 == baseline_output

        # Valid calculation after invalid inputs should work correctly
        output9, changed9 = pid.calc(
            input_val=21.0, set_point=22.0,
            input_time=8.0, last_input_time=0.0  # Use last valid time
        )
        assert changed9 is True
        # State should still be valid and produce reasonable output
        assert 0 <= output9 <= 100


class TestPIDIntegralDimensionalFix:
    """Test PID integral and derivative dimensional correctness (v0.7.0 fix).

    Tests verify that Ki and Kd parameters use hourly time units, not seconds.
    Ki should be in %/(°C·hour) and Kd in %/(°C/hour).
    """

    def test_integral_accumulation_hourly_units(self):
        """Test that integral accumulates correctly with hourly units.

        With Ki = 1.2 %/(°C·hour) and 1°C error for 1 hour (3600 seconds),
        the integral should accumulate 1.2%.
        """
        # Use floor hydronic typical values from physics.py (after 100x increase)
        pid = PID(kp=0.3, ki=1.2, kd=2.5, out_min=0, out_max=100)

        # First calculation establishes setpoint (integral will be reset to 0 due to setpoint change from 0->20)
        # Must pass both input_time and last_input_time for event-driven mode (sampling_period=0)
        output1, _ = pid.calc(input_val=19.0, set_point=20.0, input_time=0.0, last_input_time=None)
        assert abs(output1 - 0.3) < 0.01  # Proportional only: 0.3 * 1.0
        assert pid.integral == 0.0  # Reset due to setpoint change

        # Second calculation with small time step to establish _last_output > 0
        # Now setpoint is stable (20 -> 20), so integration can occur
        output2, _ = pid.calc(input_val=19.0, set_point=20.0, input_time=1.0, last_input_time=0.0)
        # Integral accumulation over 1 second = 1.2 * 1.0 * (1/3600) = 0.000333%
        assert pid.integral > 0, f"Expected integral > 0, got {pid.integral}"
        small_integral = pid.integral

        # Third calculation: maintain 1°C error for 1 hour (3600 seconds from time=1)
        # Expected additional accumulation: Ki * error * dt_hours = 1.2 * 1.0 * 1.0 = 1.2%
        output3, _ = pid.calc(input_val=19.0, set_point=20.0, input_time=3601.0, last_input_time=1.0)

        # Total integral = small_integral + 1.2 ≈ 1.2%
        assert abs(pid.integral - 1.2) < 0.01, f"Expected integral ~1.2, got {pid.integral}"

        # Verify proportional term is still correct
        assert abs(pid.proportional - 0.3) < 0.01  # Kp * error = 0.3 * 1.0

    def test_derivative_calculation_hourly_units(self):
        """Test that derivative calculates correctly with hourly rate units.

        With Kd = 2.5 %/(°C/hour) and 1°C change over 1 hour,
        the derivative should contribute -2.5% (negative of derivative of process variable).
        """
        # Disable derivative filter for this test (alpha=1.0 = no filtering)
        pid = PID(kp=0.3, ki=1.2, kd=2.5, out_min=-100, out_max=100, derivative_filter_alpha=1.0)

        # First reading at 20°C
        pid.calc(input_val=20.0, set_point=22.0, input_time=0.0, last_input_time=None)

        # Second reading 1 hour later at 21°C (heating by 1°C over 1 hour)
        # Rate of change = 1°C/hour
        # Derivative term = -Kd * rate = -2.5 * 1.0 = -2.5%
        output, _ = pid.calc(input_val=21.0, set_point=22.0, input_time=3600.0, last_input_time=0.0)

        # Check derivative term
        assert abs(pid.derivative - (-2.5)) < 0.01, f"Expected derivative ~-2.5, got {pid.derivative}"

    def test_floor_hydronic_realistic_scenario(self):
        """Test realistic floor hydronic scenario with 2-hour error accumulation.

        Simulates underfloor heating system starting cold and slowly heating up.
        Uses lower Kd to keep output in valid range for anti-windup testing.
        """
        # Floor hydronic: slow system with high thermal mass (lower Kd for this test)
        pid = PID(kp=0.3, ki=1.2, kd=0.8, out_min=0, out_max=100)

        # Start 3°C below setpoint (cold floor)
        pid.calc(input_val=18.0, set_point=21.0, input_time=0.0, last_input_time=None)
        initial_output = pid.proportional  # Only P term active
        assert abs(initial_output - 0.9) < 0.01  # 0.3 * 3.0

        # After 30 minutes (1800 seconds), temp rises to 18.5°C slowly
        # Error = 2.5°C, dt = 0.5 hours, rate of change = 1°C/hour
        # P = 0.3 * 2.5 = 0.75, I = 1.5, D = -0.8 * 1.0 = -0.8
        # Total = 0.75 + 1.5 - 0.8 = 1.45% (positive, allows continued integration)
        # Integral accumulation = 1.2 * 2.5 * 0.5 = 1.5%
        pid.calc(input_val=18.5, set_point=21.0, input_time=1800.0, last_input_time=0.0)
        assert abs(pid.integral - 1.5) < 0.01
        assert pid._output > 0, "Output should be positive to allow continued integration"

        # After 1 hour total, temp at 19.0°C (continuing slow rise)
        # Error = 2.0°C, additional dt = 0.5 hours
        # Additional accumulation = 1.2 * 2.0 * 0.5 = 1.2%
        # Total integral = 1.5 + 1.2 = 2.7%
        pid.calc(input_val=19.0, set_point=21.0, input_time=3600.0, last_input_time=1800.0)
        assert abs(pid.integral - 2.7) < 0.01
        assert pid._output > 0, "Output should remain positive"

        # After 2 hours total, temp at 19.8°C (approaching setpoint)
        # Error = 1.2°C, additional dt = 1.0 hours
        # Additional accumulation = 1.2 * 1.2 * 1.0 = 1.44%
        # Total integral = 2.7 + 1.44 = 4.14%
        pid.calc(input_val=19.8, set_point=21.0, input_time=7200.0, last_input_time=3600.0)
        assert abs(pid.integral - 4.14) < 0.02

        # Integral contribution should be meaningful but not overwhelming
        # After 2 hours with average 2°C error, integral accumulated ~4%
        # This is reasonable for a slow floor heating system


class TestPIDDerivativeFilter:
    """Test derivative term filtering to reduce sensor noise amplification.

    Tests verify EMA filtering of derivative term works correctly across
    different alpha values and reduces noise sensitivity.
    """

    def test_derivative_filter_noise_reduction(self):
        """Test that derivative filter reduces sensor noise amplification.

        Inject ±0.1°C noise on temperature readings and verify filtered
        derivative is more stable than unfiltered.
        """
        # Create two PIDs: one with filtering (alpha=0.15), one without (alpha=1.0)
        pid_filtered = PID(kp=10, ki=1.0, kd=5.0, out_min=0, out_max=100,
                          derivative_filter_alpha=0.15)
        pid_unfiltered = PID(kp=10, ki=1.0, kd=5.0, out_min=0, out_max=100,
                            derivative_filter_alpha=1.0)

        # Start at 20.0°C, target 22.0°C
        pid_filtered.calc(input_val=20.0, set_point=22.0, input_time=0.0, last_input_time=None)
        pid_unfiltered.calc(input_val=20.0, set_point=22.0, input_time=0.0, last_input_time=None)

        # Temperature readings with injected noise: 20.1 (noise +0.1), 20.15 (noise -0.05), 20.3 (noise +0.1)
        # Real trend: heating from 20.0 -> 20.1 -> 20.2 -> 20.3
        # Noisy readings: 20.0 -> 20.1 -> 20.15 -> 20.3

        # Reading 1: 20.1°C (rise of 0.1°C in 60s)
        pid_filtered.calc(input_val=20.1, set_point=22.0, input_time=60.0, last_input_time=0.0)
        pid_unfiltered.calc(input_val=20.1, set_point=22.0, input_time=60.0, last_input_time=0.0)
        deriv_filtered_1 = pid_filtered.derivative
        deriv_unfiltered_1 = pid_unfiltered.derivative

        # Reading 2: 20.15°C (apparent rise of only 0.05°C in 60s due to noise)
        # This should show noise impact
        pid_filtered.calc(input_val=20.15, set_point=22.0, input_time=120.0, last_input_time=60.0)
        pid_unfiltered.calc(input_val=20.15, set_point=22.0, input_time=120.0, last_input_time=60.0)
        deriv_filtered_2 = pid_filtered.derivative
        deriv_unfiltered_2 = pid_unfiltered.derivative

        # Reading 3: 20.3°C (large apparent rise of 0.15°C in 60s due to noise)
        pid_filtered.calc(input_val=20.3, set_point=22.0, input_time=180.0, last_input_time=120.0)
        pid_unfiltered.calc(input_val=20.3, set_point=22.0, input_time=180.0, last_input_time=120.0)
        deriv_filtered_3 = pid_filtered.derivative
        deriv_unfiltered_3 = pid_unfiltered.derivative

        # Calculate variance of derivative values (measure of noise)
        # Filtered should have lower variance (more stable)
        import statistics
        variance_filtered = statistics.variance([deriv_filtered_1, deriv_filtered_2, deriv_filtered_3])
        variance_unfiltered = statistics.variance([deriv_unfiltered_1, deriv_unfiltered_2, deriv_unfiltered_3])

        # Filtered derivative should be more stable (lower variance)
        assert variance_filtered < variance_unfiltered, \
            f"Filtered variance {variance_filtered} should be < unfiltered {variance_unfiltered}"

    def test_derivative_filter_alpha_range(self):
        """Test derivative filter behavior across alpha range 0.0 to 1.0.

        Alpha = 0.0: maximum filtering (derivative becomes constant)
        Alpha = 1.0: no filtering (raw derivative)
        Alpha = 0.5: moderate filtering
        """
        # Test alpha = 0.0 (maximum filtering)
        pid_max_filter = PID(kp=10, ki=1.0, kd=5.0, out_min=0, out_max=100,
                            derivative_filter_alpha=0.0)

        # First calculation
        pid_max_filter.calc(input_val=20.0, set_point=22.0, input_time=0.0, last_input_time=None)
        assert pid_max_filter.derivative == 0.0  # No previous derivative

        # Second calculation with temperature change
        pid_max_filter.calc(input_val=20.5, set_point=22.0, input_time=60.0, last_input_time=0.0)
        # With alpha=0.0: filtered = 0.0 * raw + 1.0 * 0.0 = 0.0
        # Derivative should remain 0 (maximum filtering suppresses all changes)
        assert pid_max_filter.derivative == 0.0

        # Test alpha = 1.0 (no filtering)
        pid_no_filter = PID(kp=10, ki=1.0, kd=5.0, out_min=0, out_max=100,
                           derivative_filter_alpha=1.0)

        pid_no_filter.calc(input_val=20.0, set_point=22.0, input_time=0.0, last_input_time=None)
        pid_no_filter.calc(input_val=20.5, set_point=22.0, input_time=60.0, last_input_time=0.0)

        # Calculate expected raw derivative
        # Rate = 0.5°C / 60s = 0.5°C / (60/3600)h = 30°C/h
        # Derivative = -Kd * rate = -5.0 * 30 = -150%
        expected_derivative = -150.0
        assert abs(pid_no_filter.derivative - expected_derivative) < 0.1

        # Test alpha = 0.5 (moderate filtering)
        pid_moderate = PID(kp=10, ki=1.0, kd=5.0, out_min=0, out_max=100,
                          derivative_filter_alpha=0.5)

        pid_moderate.calc(input_val=20.0, set_point=22.0, input_time=0.0, last_input_time=None)
        pid_moderate.calc(input_val=20.5, set_point=22.0, input_time=60.0, last_input_time=0.0)

        # With alpha=0.5: filtered = 0.5 * (-150) + 0.5 * 0.0 = -75
        assert abs(pid_moderate.derivative - (-75.0)) < 0.1

    def test_derivative_filter_disable(self):
        """Test that alpha=1.0 completely disables filter (raw derivative passthrough)."""
        # Alpha = 1.0 should give unfiltered derivative
        pid = PID(kp=10, ki=1.0, kd=5.0, out_min=0, out_max=100,
                 derivative_filter_alpha=1.0)

        # First calculation
        pid.calc(input_val=20.0, set_point=22.0, input_time=0.0, last_input_time=None)

        # Second calculation with 1°C change over 1 hour
        pid.calc(input_val=21.0, set_point=22.0, input_time=3600.0, last_input_time=0.0)

        # Raw derivative = -Kd * (1°C / 1 hour) = -5.0 * 1.0 = -5.0%
        # With alpha=1.0, filtered = 1.0 * raw + 0.0 * prev = raw
        assert abs(pid.derivative - (-5.0)) < 0.01

        # Third calculation with noise spike (0.2°C in 60 seconds)
        pid.calc(input_val=21.2, set_point=22.0, input_time=3660.0, last_input_time=3600.0)

        # Rate = 0.2°C / (60/3600)h = 12°C/h
        # Raw derivative = -5.0 * 12 = -60%
        # With alpha=1.0, should be unfiltered: -60%
        assert abs(pid.derivative - (-60.0)) < 0.1

    def test_derivative_filter_persistence_through_samples_clear(self):
        """Test that derivative filter resets when samples are cleared."""
        pid = PID(kp=10, ki=1.0, kd=5.0, out_min=0, out_max=100,
                 derivative_filter_alpha=0.15)

        # Build up filtered derivative
        pid.calc(input_val=20.0, set_point=22.0, input_time=0.0, last_input_time=None)
        pid.calc(input_val=20.5, set_point=22.0, input_time=60.0, last_input_time=0.0)
        pid.calc(input_val=21.0, set_point=22.0, input_time=120.0, last_input_time=60.0)

        # Derivative filter should have some value
        assert pid._derivative_filtered != 0.0

        # Clear samples (e.g., when switching modes OFF -> AUTO)
        pid.clear_samples()

        # Filtered derivative should be reset to 0
        assert pid._derivative_filtered == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
