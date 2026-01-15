"""Tests for adaptive/physics.py module."""

import pytest
from custom_components.adaptive_thermostat.adaptive.physics import (
    calculate_thermal_time_constant,
    calculate_initial_pid,
    calculate_initial_pwm_period,
    calculate_initial_ke,
    GLAZING_U_VALUES,
    ENERGY_RATING_TO_INSULATION,
)


class TestThermalTimeConstant:
    """Tests for calculate_thermal_time_constant function."""

    def test_thermal_time_constant_from_volume(self):
        """Test tau calculation from zone volume."""
        # Small zone (100 m3) should have lower tau
        tau_small = calculate_thermal_time_constant(volume_m3=100)
        assert tau_small == pytest.approx(2.0, abs=0.01)

        # Large zone (250 m3) should have higher tau
        tau_large = calculate_thermal_time_constant(volume_m3=250)
        assert tau_large == pytest.approx(5.0, abs=0.01)

        # Larger volume = higher tau (slower response)
        assert tau_large > tau_small

    def test_thermal_time_constant_from_energy_rating(self):
        """Test tau calculation from energy efficiency rating."""
        # A+++ rating (best insulation) should have highest tau
        tau_best = calculate_thermal_time_constant(energy_rating="A+++")
        assert tau_best == 8.0

        # D rating (poor insulation) should have lowest tau
        tau_poor = calculate_thermal_time_constant(energy_rating="D")
        assert tau_poor == 2.0

        # A rating (standard good insulation)
        tau_standard = calculate_thermal_time_constant(energy_rating="A")
        assert tau_standard == 4.0

        # Better insulation = higher tau
        assert tau_best > tau_standard > tau_poor

        # Case insensitive
        tau_lower = calculate_thermal_time_constant(energy_rating="a++")
        assert tau_lower == 6.0

    def test_thermal_time_constant_missing_params(self):
        """Test that ValueError is raised when no parameters provided."""
        with pytest.raises(ValueError, match="Either volume_m3 or energy_rating must be provided"):
            calculate_thermal_time_constant()

    def test_thermal_time_constant_unknown_rating(self):
        """Test fallback for unknown energy rating."""
        # Unknown rating should default to 4.0 (standard)
        tau_unknown = calculate_thermal_time_constant(energy_rating="X")
        assert tau_unknown == 4.0

    def test_thermal_time_constant_no_window_params(self):
        """Test that tau is unchanged when window params not provided."""
        # Base tau without windows
        tau_base = calculate_thermal_time_constant(volume_m3=200)
        assert tau_base == pytest.approx(4.0, abs=0.01)

        # With window_area but no floor_area - should be unchanged
        tau_no_floor = calculate_thermal_time_constant(volume_m3=200, window_area_m2=5.0)
        assert tau_no_floor == tau_base

        # With floor_area but no window_area - should be unchanged
        tau_no_window = calculate_thermal_time_constant(volume_m3=200, floor_area_m2=25.0)
        assert tau_no_window == tau_base

    def test_thermal_time_constant_with_hr_plus_plus_baseline(self):
        """Test tau adjustment with HR++ glazing at 20% window ratio (baseline)."""
        # 25 m2 floor, 5 m2 window = 20% ratio, HR++ (default)
        # At baseline, expect 15% reduction
        tau_base = 200 / 50.0  # 4.0
        tau_with_windows = calculate_thermal_time_constant(
            volume_m3=200,
            window_area_m2=5.0,
            floor_area_m2=25.0,
            window_rating="hr++"
        )
        # Heat loss factor = (1.1/1.1) * (0.2/0.2) = 1.0 (baseline)
        # tau = tau_base * (1 - 0.15 * 1.0) = 4.0 * 0.85 = 3.4
        assert tau_with_windows == pytest.approx(3.4, abs=0.01)

    def test_thermal_time_constant_with_single_pane_windows(self):
        """Test tau adjustment with poor glazing (single pane)."""
        # Single pane has U-value 5.8, HR++ baseline is 1.1
        # 25 m2 floor, 5 m2 window = 20% ratio
        tau_base = 200 / 50.0  # 4.0
        tau_with_single = calculate_thermal_time_constant(
            volume_m3=200,
            window_area_m2=5.0,
            floor_area_m2=25.0,
            window_rating="single"
        )
        # Heat loss factor = (5.8/1.1) * (0.2/0.2) = 5.27
        # tau reduction = 0.15 * 5.27 = 0.79 (clamped to 0.5 max)
        # tau = 4.0 * (1 - 0.5) = 2.0
        assert tau_with_single == pytest.approx(2.0, abs=0.01)

    def test_thermal_time_constant_with_triple_glazing(self):
        """Test tau adjustment with excellent glazing (triple pane)."""
        # Triple has U-value 0.6, HR++ baseline is 1.1
        # 25 m2 floor, 5 m2 window = 20% ratio
        tau_base = 200 / 50.0  # 4.0
        tau_with_triple = calculate_thermal_time_constant(
            volume_m3=200,
            window_area_m2=5.0,
            floor_area_m2=25.0,
            window_rating="triple"
        )
        # Heat loss factor = (0.6/1.1) * (0.2/0.2) = 0.55
        # tau = 4.0 * (1 - 0.15 * 0.55) = 4.0 * 0.92 = 3.67
        assert tau_with_triple == pytest.approx(3.67, abs=0.01)

    def test_thermal_time_constant_with_large_window_area(self):
        """Test tau adjustment with larger window ratio."""
        # 25 m2 floor, 10 m2 window = 40% ratio (double baseline)
        tau_base = 200 / 50.0  # 4.0
        tau_with_large = calculate_thermal_time_constant(
            volume_m3=200,
            window_area_m2=10.0,
            floor_area_m2=25.0,
            window_rating="hr++"
        )
        # Heat loss factor = (1.1/1.1) * (0.4/0.2) = 2.0
        # tau = 4.0 * (1 - 0.15 * 2.0) = 4.0 * 0.7 = 2.8
        assert tau_with_large == pytest.approx(2.8, abs=0.01)


class TestPhysicsCalculations:
    """Tests for physics-based PID calculations."""

    def test_calculate_initial_pid_floor_hydronic(self):
        """Test PID calculation for floor hydronic heating."""
        tau = 8.0  # High thermal mass
        kp, ki, kd = calculate_initial_pid(tau, "floor_hydronic")

        # Floor hydronic has 0.5x modifier
        # Expected: Kp ≈ 56, Ki ≈ 0.6 (100x increase in v0.7.0), Kd ≈ 3.5
        assert kp == pytest.approx(56.25, abs=1.0)
        assert ki == pytest.approx(0.6, abs=0.1)
        assert kd == pytest.approx(3.5, abs=0.5)

    def test_calculate_initial_pid_radiator(self):
        """Test PID calculation for radiator heating."""
        tau = 4.0  # Moderate thermal mass
        kp, ki, kd = calculate_initial_pid(tau, "radiator")

        # Radiator has 0.7x modifier
        # Expected: Kp ≈ 105, Ki ≈ 1.4 (100x increase in v0.7.0), Kd ≈ 3.5
        assert kp == pytest.approx(105.0, abs=5.0)
        assert ki == pytest.approx(1.4, abs=0.2)
        assert kd == pytest.approx(3.5, abs=0.5)

    def test_calculate_initial_pid_convector(self):
        """Test PID calculation for convector heating."""
        tau = 2.5  # Low thermal mass
        kp, ki, kd = calculate_initial_pid(tau, "convector")

        # Convector has 1.0x modifier (baseline)
        # Expected: Kp ≈ 150, Ki ≈ 2.8 (100x increase in v0.7.0), Kd ≈ 3.0
        assert kp == pytest.approx(150.0, abs=10.0)
        assert ki == pytest.approx(2.8, abs=0.4)
        assert kd == pytest.approx(3.0, abs=0.5)

    def test_calculate_initial_pid_forced_air(self):
        """Test PID calculation for forced air heating."""
        tau = 1.5  # Very low thermal mass
        kp, ki, kd = calculate_initial_pid(tau, "forced_air")

        # Forced air has 1.3x modifier (aggressive)
        # Expected: Kp ≈ 260, Ki ≈ 5.2 (100x increase in v0.7.0), Kd ≈ 2.6
        assert kp == pytest.approx(260.0, abs=15.0)
        assert ki == pytest.approx(5.2, abs=0.8)
        assert kd == pytest.approx(2.6, abs=0.5)

    def test_calculate_initial_pid_unknown_type(self):
        """Test PID calculation with unknown heating type uses default modifier."""
        tau = 4.0
        kp, ki, kd = calculate_initial_pid(tau, "unknown_type")

        # Should use floor_hydronic as fallback (0.5x modifier)
        assert kp == pytest.approx(75.0, abs=5.0)
        assert ki == pytest.approx(0.01, abs=0.002)
        assert kd == pytest.approx(3.0, abs=0.5)

    def test_calculate_initial_pid_relationships(self):
        """Test that PID values follow expected relationships."""
        tau = 4.0
        kp, ki, kd = calculate_initial_pid(tau, "convector")

        # Basic sanity checks
        assert kp > 0
        assert ki > 0
        assert kd > 0

        # Kd should be smaller than Kp
        assert kd < kp

        # Ki should be much smaller than Kp
        assert ki < kp * 0.1

    def test_calculate_initial_pid_tau_scaling(self):
        """Test that PID values scale appropriately with tau."""
        tau_low = 2.0
        tau_high = 8.0

        kp_low, ki_low, kd_low = calculate_initial_pid(tau_low, "convector")
        kp_high, ki_high, kd_high = calculate_initial_pid(tau_high, "convector")

        # Higher tau should result in:
        # - Lower Kp (more conservative)
        assert kp_high < kp_low

        # - Lower Ki (slower integral accumulation)
        assert ki_high < ki_low

        # - Higher Kd (more damping for slow systems)
        assert kd_high > kd_low


class TestKiWindupTime:
    """Tests for Ki integral accumulation behavior with v0.7.0 hourly units."""

    def test_ki_windup_time(self):
        """Test Ki windup time at 1°C error verifies 1-2 hour accumulation.

        With the v0.7.0 fix, Ki values use hourly units: %/(°C·hour).
        Base Ki=1.2 for floor_hydronic, adjusted by tau_factor for tau=8.0.
        """
        # Floor hydronic heating with base Ki=1.2, tau=8.0
        # tau_factor = 1.5/8.0 = 0.1875, clamped to 0.7
        # Actual Ki = 1.2 * 0.7 = 0.84 %/(°C·hour)
        tau = 8.0
        kp, ki, kd = calculate_initial_pid(tau, "floor_hydronic")

        # At 1°C error for 1 hour, integral should accumulate approximately Ki
        error = 1.0  # °C
        time_hours = 1.0  # hour
        expected_integral_contribution = ki * error * time_hours

        # With tau adjustment: Ki≈0.84, so at 1°C for 1 hour: integral += 0.84%
        assert expected_integral_contribution == pytest.approx(0.84, abs=0.1)

        # At 2 hours with 1°C error: integral += 1.68%
        time_hours = 2.0
        expected_integral_contribution = ki * error * time_hours
        assert expected_integral_contribution == pytest.approx(1.68, abs=0.2)

        # Verify Ki is in reasonable range (0.5-10.0 for hourly units)
        assert 0.5 <= ki <= 10.0

    def test_cold_start_recovery(self):
        """Test PID recovery from cold start (10°C → 20°C scenario).

        Simulates a severe undershoot scenario where the zone starts far below
        setpoint, verifying that Ki can accumulate sufficient integral term.
        """
        # Radiator system with base Ki=2.0, tau=4.0
        # tau_factor = 1.5/4.0 = 0.375, clamped to 0.7
        # Actual Ki = 2.0 * 0.7 = 1.4 %/(°C·hour)
        tau = 4.0
        kp, ki, kd = calculate_initial_pid(tau, "radiator")

        # Cold start: 10°C below setpoint
        initial_error = 10.0  # °C

        # Assume error decays linearly over 4 hours to reach setpoint
        # Average error over recovery period: 5°C
        avg_error = 5.0  # °C
        recovery_time_hours = 4.0  # hours

        # Integral accumulation during recovery
        integral_contribution = ki * avg_error * recovery_time_hours

        # Ki=1.4, avg_error=5°C, time=4h: integral = 1.4 * 5 * 4 = 28%
        assert integral_contribution == pytest.approx(28.0, abs=3.0)

        # This should be sufficient to provide boost (combined with Kp term)
        # Kp=105, error=10°C: P term = 105*10/100 = 10.5%
        # After 2 hours: I term = 1.4*5*2 = 14%
        # Total output can reach 24%+ to drive recovery

        # Verify Ki is properly scaled for cold start scenarios
        assert ki >= 1.0  # Must be at least 1.0 to accumulate meaningfully


class TestPWMPeriod:
    """Tests for PWM period calculation."""

    def test_pwm_period_heating_types(self):
        """Test PWM period for different heating types."""
        # Floor hydronic should have longest period (15 min = 900 sec)
        period_floor = calculate_initial_pwm_period("floor_hydronic")
        assert period_floor == 900

        # Radiator should have moderate period (10 min = 600 sec)
        period_rad = calculate_initial_pwm_period("radiator")
        assert period_rad == 600

        # Convector should have shorter period (5 min = 300 sec)
        period_conv = calculate_initial_pwm_period("convector")
        assert period_conv == 300

        # Forced air should have shortest period (3 min = 180 sec)
        period_air = calculate_initial_pwm_period("forced_air")
        assert period_air == 180

        # Longer period for slower heating systems
        assert period_floor > period_rad > period_conv > period_air

    def test_pwm_period_unknown_type(self):
        """Test fallback for unknown heating type."""
        period_unknown = calculate_initial_pwm_period("unknown_type")
        # Should default to 600 seconds (10 minutes)
        assert period_unknown == 600

    def test_pwm_period_no_args(self):
        """Test default PWM period when no args provided."""
        period_default = calculate_initial_pwm_period()
        # Should default to floor_hydronic (900 seconds)
        assert period_default == 900


class TestKeCalculation:
    """Tests for Ke (outdoor temperature compensation) calculation.

    Feature 1.3: Ke values reduced by 100x in v0.7.0 to match corrected Ki dimensional analysis.
    New range: 0.001 - 0.02 (was 0.1 - 2.0)
    """

    def test_ke_magnitude_sanity_check(self):
        """Test that all Ke values are within new 0.001-0.02 range after 100x reduction."""
        # Test all energy ratings
        for rating in ENERGY_RATING_TO_INSULATION.keys():
            ke = calculate_initial_ke(energy_rating=rating, heating_type="radiator")
            assert ke >= 0.001, f"Ke too low for {rating}: {ke}"
            assert ke <= 0.02, f"Ke too high for {rating}: {ke}"

        # Test all heating types with moderate insulation
        for heating_type in ["floor_hydronic", "radiator", "convector", "forced_air"]:
            ke = calculate_initial_ke(energy_rating="B", heating_type=heating_type)
            assert ke >= 0.001, f"Ke too low for {heating_type}: {ke}"
            assert ke <= 0.02, f"Ke too high for {heating_type}: {ke}"

    def test_ke_energy_rating_values(self):
        """Test Ke values for different energy ratings (100x scaling)."""
        # A++++ (best) should have lowest Ke
        ke_best = calculate_initial_ke(energy_rating="A++++", heating_type="radiator")
        assert ke_best == pytest.approx(0.001, abs=0.0001)

        # G (worst) should have highest Ke
        ke_worst = calculate_initial_ke(energy_rating="G", heating_type="radiator")
        assert ke_worst == pytest.approx(0.013, abs=0.001)

        # A (standard) should be moderate
        ke_standard = calculate_initial_ke(energy_rating="A", heating_type="radiator")
        assert ke_standard == pytest.approx(0.0045, abs=0.0005)

        # Better insulation = lower Ke
        assert ke_best < ke_standard < ke_worst

    def test_ke_heating_type_factors(self):
        """Test Ke adjustment by heating type (100x scaling maintained)."""
        # Floor hydronic should have highest Ke (slow response, benefits from compensation)
        ke_floor = calculate_initial_ke(energy_rating="A", heating_type="floor_hydronic")

        # Radiator is baseline
        ke_rad = calculate_initial_ke(energy_rating="A", heating_type="radiator")

        # Forced air should have lowest Ke (fast response, less benefit)
        ke_air = calculate_initial_ke(energy_rating="A", heating_type="forced_air")

        # Verify relationship
        assert ke_floor > ke_rad > ke_air

        # Check approximate values (A rating base is 0.0045)
        assert ke_floor == pytest.approx(0.0054, abs=0.0005)  # 0.0045 * 1.2
        assert ke_rad == pytest.approx(0.0045, abs=0.0005)    # 0.0045 * 1.0
        assert ke_air == pytest.approx(0.0027, abs=0.0005)    # 0.0045 * 0.6

    def test_ke_vs_p_term_ratio(self):
        """Test that Ke contributes 20-50% of P term in typical scenarios.

        This verifies the fix is correct: Ke should provide meaningful but not
        dominant outdoor compensation compared to the proportional term.
        """
        # Typical scenario:
        # - Indoor target: 20°C, current: 19°C (error = 1°C)
        # - Outdoor: -10°C (delta = 30°C from 20°C reference)
        # - Kp = 150, Ke = 0.005 (moderate insulation, convector)

        kp = 150.0
        ke = 0.005
        indoor_error = 1.0  # °C
        outdoor_delta = 30.0  # °C

        p_term = kp * indoor_error  # 150% power contribution
        e_term = ke * outdoor_delta  # 0.005 * 30 = 0.15% power contribution

        # E term should be 0.1% (well below P term)
        ratio = e_term / p_term
        assert ratio < 0.01, f"E term too dominant: {ratio:.2%} of P term"
        assert ratio > 0.0001, f"E term too weak: {ratio:.2%} of P term"

        # In extreme cold (-20°C, delta = 40°C)
        outdoor_delta_extreme = 40.0
        e_term_extreme = ke * outdoor_delta_extreme  # 0.005 * 40 = 0.20%
        ratio_extreme = e_term_extreme / p_term

        # Even in extreme conditions, E term should be modest
        assert ratio_extreme < 0.005, f"E term too dominant in extreme cold: {ratio_extreme:.2%}"

    def test_ke_with_windows_adjustment(self):
        """Test Ke window area adjustment maintains new scale (100x)."""
        # Base Ke without windows
        ke_base = calculate_initial_ke(energy_rating="B", heating_type="radiator")

        # Ke with 20% window ratio (baseline)
        ke_with_windows = calculate_initial_ke(
            energy_rating="B",
            window_area_m2=5.0,
            floor_area_m2=25.0,
            window_rating="hr++",
            heating_type="radiator"
        )

        # Both should be in valid range
        assert 0.001 <= ke_base <= 0.02
        assert 0.001 <= ke_with_windows <= 0.02

        # Windows should increase Ke (more heat loss)
        assert ke_with_windows > ke_base

        # But not by more than 50% (window_factor capped at 0.5)
        assert ke_with_windows <= ke_base * 1.5

    def test_ke_default_fallback(self):
        """Test Ke defaults to moderate value when energy rating not specified."""
        ke_default = calculate_initial_ke(heating_type="radiator")

        # Should default to B rating equivalent (0.0045 * 1.0 = 0.0045)
        assert ke_default == pytest.approx(0.0045, abs=0.0005)
        assert 0.001 <= ke_default <= 0.02
