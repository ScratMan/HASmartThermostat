"""Physics-based PID initialization for Adaptive Thermostat.

This module provides functions to calculate initial PID parameters based on
thermal properties of zones and heating system characteristics.
"""

from typing import Tuple, Optional, Dict


# Energy rating to insulation quality mapping
# Higher insulation = less impact from outdoor temperature = lower initial Ke
# Values scaled by 1/100 to match corrected Ki dimensional analysis (v0.7.0)
ENERGY_RATING_TO_INSULATION: Dict[str, float] = {
    "A++++": 0.001,   # Outstanding insulation - extremely minimal outdoor impact
    "A+++": 0.0015,   # Excellent insulation - minimal outdoor impact
    "A++": 0.0025,    # Very good insulation
    "A+": 0.0035,     # Good insulation
    "A": 0.0045,      # Standard good insulation
    "B": 0.0055,      # Moderate insulation
    "C": 0.007,       # Poor insulation - significant outdoor impact
    "D": 0.0085,      # Very poor insulation
    "E": 0.010,       # Minimal insulation
    "F": 0.0115,      # Below minimum standards
    "G": 0.013,       # No effective insulation
}


# Glazing U-values in W/(m²·K) - lower is better insulation
GLAZING_U_VALUES = {
    "single": 5.8,      # Single pane glass
    "double": 2.8,      # Standard double glazing
    "hr": 2.8,          # HR (same as double)
    "hr+": 1.8,         # HR+ improved
    "hr++": 1.1,        # HR++ high performance
    "hr+++": 0.6,       # Triple glazing
    "triple": 0.6,      # Alias for HR+++
}


def calculate_thermal_time_constant(
    volume_m3: Optional[float] = None,
    energy_rating: Optional[str] = None,
    window_area_m2: Optional[float] = None,
    floor_area_m2: Optional[float] = None,
    window_rating: str = "hr++",
) -> float:
    """Calculate thermal time constant (tau) in hours.

    The thermal time constant represents how quickly a zone responds to
    heating changes. It can be estimated from zone volume or energy rating,
    and adjusted for window heat loss.

    Args:
        volume_m3: Zone volume in cubic meters. If provided, tau is estimated
                   as volume_m3 / 50 (larger spaces respond more slowly).
        energy_rating: Building energy efficiency rating (A+++, A++, A+, A, B, C, D).
                       Higher ratings mean better insulation and slower cooling.
        window_area_m2: Total window/glass area in square meters.
        floor_area_m2: Zone floor area in square meters (needed for window ratio).
        window_rating: Glazing type (single, double, hr, hr+, hr++, hr+++, triple).
                       Higher ratings mean better insulation. Default: hr++.

    Returns:
        Thermal time constant in hours.

    Raises:
        ValueError: If neither volume_m3 nor energy_rating is provided.
    """
    if volume_m3 is not None:
        # Estimate tau based on zone volume
        # Larger spaces have higher thermal mass and respond more slowly
        tau_base = volume_m3 / 50.0
    elif energy_rating is not None:
        # Estimate tau based on energy efficiency rating
        # Better insulation = slower temperature changes = higher tau
        rating_map = {
            "A++++": 10.0,  # Outstanding insulation, extremely slow response
            "A+++": 8.0,  # Excellent insulation, very slow response
            "A++": 6.0,   # Very good insulation
            "A+": 5.0,    # Good insulation
            "A": 4.0,     # Standard good insulation
            "B": 3.0,     # Moderate insulation
            "C": 2.5,     # Poor insulation
            "D": 2.0,     # Very poor insulation, fast response
        }
        tau_base = rating_map.get(energy_rating.upper(), 4.0)
    else:
        raise ValueError("Either volume_m3 or energy_rating must be provided")

    # Adjust tau for window heat loss if window parameters provided
    if window_area_m2 and floor_area_m2 and floor_area_m2 > 0:
        # Get U-value for glazing type (default to HR++ if unknown)
        u_value = GLAZING_U_VALUES.get(window_rating.lower(), 1.1)

        # Window ratio: what fraction of floor area is glass
        window_ratio = window_area_m2 / floor_area_m2

        # Heat loss factor normalized to HR++ (U=1.1) at 20% window ratio as baseline
        # Higher U-value (worse insulation) and more glass = more heat loss = lower tau
        heat_loss_factor = (u_value / 1.1) * (window_ratio / 0.2)

        # Reduce tau by up to 40% for high glass area / poor insulation
        # Factor of 0.15 means: at baseline (HR++, 20% windows), reduction is 15%
        tau_reduction = min(heat_loss_factor * 0.15, 0.4)
        tau_base *= (1 - tau_reduction)

    return tau_base


def calculate_initial_pid(
    thermal_time_constant: float,
    heating_type: str = "floor_hydronic",
) -> Tuple[float, float, float]:
    """Calculate initial PID parameters using empirical heating system values.

    Uses empirically-derived base values for each heating type, with minor
    adjustments based on thermal time constant. These values are calibrated
    for real-world HVAC systems rather than theoretical Ziegler-Nichols.

    Args:
        thermal_time_constant: System thermal time constant in hours (tau).
        heating_type: Type of heating system. Valid values:
            - "floor_hydronic": Floor heating with water (very slow, high mass)
            - "radiator": Traditional radiators (moderate response)
            - "convector": Convection heaters (faster response)
            - "forced_air": Forced air heating (fast response)

    Returns:
        Tuple of (Kp, Ki, Kd) PID parameters.

    Notes:
        - Floor heating needs very low Ki (slow integration, avoid wind-up)
        - Floor heating needs high Kd (dampen slow oscillations)
        - Faster systems (convector, forced_air) can use higher Ki, lower Kd
    """
    # Empirical base values per heating type
    # Calibrated from real-world A+++ house with floor hydronic heating
    # v0.7.0: Ki values increased 100x after fixing dimensional analysis bug (hourly units)
    heating_params = {
        "floor_hydronic": {"kp": 0.3, "ki": 1.2, "kd": 7.0},   # Very slow, needs strong damping
        "radiator": {"kp": 0.5, "ki": 2.0, "kd": 5.0},          # Moderate response
        "convector": {"kp": 0.8, "ki": 4.0, "kd": 3.0},         # Faster response
        "forced_air": {"kp": 1.2, "ki": 8.0, "kd": 2.0},        # Fast response, low mass
    }

    params = heating_params.get(heating_type, heating_params["radiator"])

    # Minor tau-based adjustment (normalized to tau=1.5 as baseline)
    # Higher tau = slower system = slightly lower Kp/Ki, slightly higher Kd
    tau_factor = 1.5 / thermal_time_constant if thermal_time_constant > 0 else 1.0
    tau_factor = max(0.7, min(1.3, tau_factor))  # Clamp to ±30%

    Kp = params["kp"] * tau_factor
    Ki = params["ki"] * tau_factor
    Kd = params["kd"] / tau_factor  # Inverse: slower systems need more damping

    return (round(Kp, 4), round(Ki, 5), round(Kd, 2))


def calculate_initial_pwm_period(heating_type: str = "floor_hydronic") -> int:
    """Calculate initial PWM (Pulse Width Modulation) period in seconds.

    The PWM period determines how frequently the heating actuator cycles
    on/off. Longer periods reduce mechanical wear but slower response.

    Args:
        heating_type: Type of heating system. Valid values:
            - "floor_hydronic": Floor heating with water
            - "radiator": Traditional radiators
            - "convector": Convection heaters
            - "forced_air": Forced air heating

    Returns:
        PWM period in seconds.

    Notes:
        - Floor heating uses long periods to reduce valve cycling
        - Forced air can use shorter periods for faster response
    """
    # PWM period lookup table based on heating system characteristics
    # Longer periods = less wear, slower response
    # Shorter periods = faster response, more wear
    pwm_periods = {
        "floor_hydronic": 900,    # 15 minutes - minimize valve wear
        "radiator": 600,          # 10 minutes - moderate valve cycling
        "convector": 300,         # 5 minutes - faster response
        "forced_air": 180,        # 3 minutes - very fast response
    }

    return pwm_periods.get(heating_type, 600)  # Default to 10 minutes


def calculate_initial_ke(
    energy_rating: Optional[str] = None,
    window_area_m2: Optional[float] = None,
    floor_area_m2: Optional[float] = None,
    window_rating: str = "hr++",
    heating_type: str = "floor_hydronic",
) -> float:
    """Calculate initial Ke (outdoor temperature compensation) parameter.

    Ke adjusts the PID output based on outdoor temperature difference from
    a reference point. A well-tuned Ke reduces integral wind-up during
    outdoor temperature changes.

    The initial value is estimated based on:
    - Building energy rating (insulation quality)
    - Window area and rating (heat loss through glazing)
    - Heating system type (response characteristics)

    Args:
        energy_rating: Building energy efficiency rating (A+++, A++, A+, A, B, C, D, E, F, G).
                       Higher ratings mean better insulation and lower Ke.
        window_area_m2: Total window/glass area in square meters.
        floor_area_m2: Zone floor area in square meters (needed for window ratio).
        window_rating: Glazing type (single, double, hr, hr+, hr++, hr+++, triple).
                       Poorer glazing increases outdoor temperature impact.
        heating_type: Type of heating system. Slower systems (floor_hydronic)
                      benefit more from outdoor compensation.

    Returns:
        Initial Ke value (typically 0.001 - 0.008 for well-insulated buildings,
        0.008 - 0.015 for poorly insulated buildings). Scaled by 1/100 in v0.7.0
        to match corrected Ki dimensional analysis.
    """
    # Base Ke from energy rating
    if energy_rating:
        base_ke = ENERGY_RATING_TO_INSULATION.get(energy_rating.upper(), 0.0045)
    else:
        # Default to moderate insulation if not specified
        base_ke = 0.0045

    # Adjust for window heat loss
    if window_area_m2 and floor_area_m2 and floor_area_m2 > 0:
        # Get U-value for glazing type
        u_value = GLAZING_U_VALUES.get(window_rating.lower(), 1.1)

        # Window ratio: what fraction of floor area is glass
        window_ratio = window_area_m2 / floor_area_m2

        # Higher window ratio and worse glazing = more outdoor impact = higher Ke
        # Normalized to HR++ (U=1.1) at 20% window ratio as baseline
        window_factor = (u_value / 1.1) * (window_ratio / 0.2)

        # Adjust Ke up to +50% for high glass / poor insulation
        base_ke *= (1.0 + min(window_factor * 0.25, 0.5))

    # Adjust for heating system type
    # Slower systems benefit more from outdoor compensation
    # Values scaled by 1/100 to match corrected Ki dimensional analysis (v0.7.0)
    heating_type_factors = {
        "floor_hydronic": 1.2,   # Slow response - more benefit from Ke
        "radiator": 1.0,         # Baseline
        "convector": 0.8,        # Faster response - less Ke needed
        "forced_air": 0.6,       # Fast response - minimal Ke needed
    }
    type_factor = heating_type_factors.get(heating_type, 1.0)
    base_ke *= type_factor

    # Round to 4 decimal places (was 2, now more precision needed)
    return round(base_ke, 4)
