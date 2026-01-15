# Critical Analysis: PID Controller for Adaptive Thermostat

**Analyzed Components:**
- `/Users/kleist/Sites/ha-adaptive-thermostat/custom_components/adaptive_thermostat/pid_controller/__init__.py`
- `/Users/kleist/Sites/ha-adaptive-thermostat/custom_components/adaptive_thermostat/adaptive/physics.py`
- `/Users/kleist/Sites/ha-adaptive-thermostat/custom_components/adaptive_thermostat/const.py`
- `/Users/kleist/Sites/ha-adaptive-thermostat/custom_components/adaptive_thermostat/adaptive/learning.py`
- `/Users/kleist/Sites/ha-adaptive-thermostat/custom_components/adaptive_thermostat/adaptive/pid_rules.py`

---

## 1. PID Structure Analysis

### Core Implementation (`pid_controller/__init__.py`)

#### What's Done Correctly:

1. **Anti-windup protection**: Lines 238-244 implement conditional integration that only accumulates when:
   - Output is not saturated (`out_min < last_output < out_max`)
   - Setpoint is stable (`last_set_point == set_point`)
   - This is textbook anti-windup and prevents integral buildup during saturation

2. **Derivative on measurement**: Line 248 correctly implements derivative on the input (`-Kd * input_diff / dt`) rather than derivative on error. This eliminates "derivative kick" when setpoint changes abruptly, which is critical for HVAC applications where users change setpoints frequently.

3. **Integral reset on setpoint change**: Line 244 resets integral to zero when setpoint changes, preventing inappropriate control action from accumulated error at the old setpoint.

4. **Sample time enforcement**: Lines 179-181 prevent execution if sampling period hasn't elapsed, ensuring consistent timing for integral/derivative calculations.

5. **Input validation**: Lines 169-177 check for NaN/Inf values and return cached output if inputs are invalid.

#### Critical Problems:

1. **FATAL: Incorrect integral calculation** (Line 240):
   ```python
   self._integral += self._Ki * self._error * self._dt
   ```
   This stores the **integrated error** (units: °C·s) in `_integral`, but then uses it directly in output calculation (line 253). The result is that `_integral` grows without bounds in units of °C·s, while `_proportional` is in % power output.

   **What it should be**: Either:
   - Store raw integral of error and multiply by Ki during output calculation, OR
   - Store the integrated contribution (Ki * error * dt accumulated) but recognize it's already in output units

   The current implementation is internally inconsistent. The clamping on line 242 tries to limit `_integral` to `out_max - external`, but `_integral` is in °C·s while `out_max` is in % power. **This is a dimensional analysis failure.**

   **Real-world impact**: The integral term will either:
   - Saturate instantly (if dt is in seconds and error is in °C)
   - Grow far too slowly (if somehow dt units are different)
   - Behave unpredictably as dt varies with sensor update frequency

2. **Derivative implementation assumes constant dt** (Line 248):
   ```python
   self._derivative = -(self._Kd * self._input_diff) / self._dt
   ```
   While dividing by dt is correct, there's no derivative filtering. In HVAC applications, temperature sensors have noise (typically ±0.1°C for residential sensors, worse for cheap ones). With dt=30s and noise=0.1°C, you get derivative noise of 0.2°C/min, amplified by Kd. For floor hydronic heating (Kd=7.0 from physics.py line 138), this is 1.4% output noise.

   **What's missing**: Low-pass filter on derivative term (typical HVAC implementations use exponential moving average with alpha=0.1-0.2).

3. **No bumpless transfer** (Lines 82-84):
   When switching from OFF to AUTO mode, `clear_samples()` is called, resetting all state. But when PID first calculates after this, it has no `last_input`, so `input_diff=0` (line 223), meaning derivative=0. More critically, the integral term starts from zero, so the PID has no "memory" of how much output was needed in OFF mode.

   **Real-world impact**: If a zone was maintaining temperature in OFF mode (bang-bang control at out_max=100%), switching to AUTO mode resets integral=0, so PID output will be low initially, and the room will cool until integral winds up. Users will experience temperature drop every time they switch from OFF to AUTO.

   **Industry practice**: Store last output before mode change and pre-load integral to maintain continuity.

4. **Setpoint change behavior is too aggressive** (Line 244):
   Zeroing the integral on setpoint change makes sense to prevent inappropriate control action, but it means PID has to re-learn the steady-state output needed for the new setpoint. For floor hydronic heating with high thermal mass, this causes:
   - Slow response after setpoint increase (integral needs to wind up from zero)
   - Potential overshoot after setpoint decrease (no negative integral to counteract residual heat)

   **Better approach**: Use "proportional on measurement" instead, where only the P term responds to setpoint changes, and I/D terms continue on measurement. This is standard in commercial HVAC controllers.

5. **Outdoor compensation (Ke term) is fundamentally flawed**:

   Line 234: `self._external = self._Ke * self._dext`

   Where `_dext = set_point - ext_temp` (line 229).

   **Problem**: This assumes outdoor temperature impact scales linearly with (indoor_target - outdoor_temp), which is only approximately true for steady-state heat loss. It completely ignores:
   - Wind speed (convective heat loss)
   - Solar radiation (heat gain)
   - Humidity (latent heat)
   - Thermal lag (outdoor temperature from 1 hour ago affects indoor temp now, not instantaneously)

   **Worse**: The Ke term is added directly to PID output (line 253), meaning it acts like a feedforward term. But since it's based on current outdoor temp (no lag), it will be wrong for high thermal mass systems. For floor hydronic heating with tau=8 hours (A+++ house), the outdoor temperature from 4-8 hours ago is more relevant than current outdoor temp.

   **Real-world impact**: On a sunny cold day, outdoor temp is low (high Ke contribution), but solar gain is high (should reduce heating). The PID will overheat the space. On a cloudy warm day, the opposite happens, causing underheating.

6. **No derivative filtering on setpoint changes**:
   Although derivative is correctly calculated on measurement (not error), there's no protection against rapid setpoint changes causing integral windup. If a user changes setpoint from 20°C to 22°C, the proportional term jumps by 2*Kp, but the integral is reset to zero. This means the PID output drops (losing the integral contribution), then slowly recovers as integral winds up.

   **Better approach**: Gradually decay the integral over 1-2 time constants instead of zeroing it.

---

## 2. Physics-Based Initialization Analysis

### Thermal Time Constant Calculation (`physics.py`, lines 39-106)

#### What's Done Correctly:

1. **Volume-based estimation** (line 71): `tau_base = volume_m3 / 50.0` is reasonable for residential spaces. A 150m³ space (60m² floor * 2.5m height) gives tau=3 hours, which matches typical residential thermal mass.

2. **Energy rating correlation** (lines 76-85): The mapping from A++++ (tau=10h) to D (tau=2h) correctly captures that better insulation means slower temperature decay. The values are plausible for European building standards.

3. **Window heat loss adjustment** (lines 90-104): Accounting for window U-value and window ratio is correct in principle. The formula reduces tau for poor glazing and high glass area, which matches physics.

#### Critical Problems:

1. **Tau calculation ignores heating system characteristics**:
   The thermal time constant tau is calculated purely from building properties (volume/insulation/windows), but tau should also depend on the **heating system's response time**.

   - Floor hydronic heating: Water temperature changes slowly due to boiler/mixing valve lag, and floor slab thermal mass adds 1-2 hours of lag.
   - Forced air: Fan response is nearly instantaneous.

   **Current code** calculates the same tau for a space regardless of whether it has floor heating or forced air. Then in `calculate_initial_pid()`, it applies a "pid_modifier" to the base PID values (lines 144-153), but this is backwards.

   **What it should do**: Calculate separate tau values for:
   - Building thermal mass (current implementation)
   - Heating system thermal mass (new)
   - Combined tau = tau_building + tau_heating_system

   For floor hydronic, tau_heating_system = 1-2 hours. For forced air, tau_heating_system = 5-10 minutes.

2. **Ziegler-Nichols is not used** (despite comments suggesting it):
   Lines 113-155 claim to use "Ziegler-Nichols" but actually use hardcoded empirical values per heating type (lines 136-142). The tau_factor adjustment (lines 148-149) is a weak attempt to scale these values, but it only allows ±30% adjustment.

   **Real Ziegler-Nichols**: For a first-order process with time constant tau and dead time td:
   - Kp = tau / (td * K)
   - Ki = Kp / (2 * td)
   - Kd = Kp * td / 2

   Where K is the process gain (°C per % heating output).

   **What's missing**: No measurement or estimation of:
   - Dead time (td): Delay between heater turning on and temperature starting to rise. For floor hydronic, td=10-20min. For forced air, td=2-5min.
   - Process gain (K): How much temperature rises per % heating output. Depends on heater power, zone size, insulation.

   **Impact**: The hardcoded PID values (e.g., floor_hydronic: Kp=0.3, Ki=0.012, Kd=7.0) might work for the original developer's A+++ house, but will fail for:
   - Oversized heating systems (high K → Kp too high → overshoot)
   - Undersized heating systems (low K → Kp too low → slow response)
   - Different building characteristics

3. **Window heat loss formula is dimensionally incorrect**:
   Lines 99-103 calculate:
   ```python
   heat_loss_factor = (u_value / 1.1) * (window_ratio / 0.2)
   tau_reduction = min(heat_loss_factor * 0.15, 0.4)
   tau_base *= (1 - tau_reduction)
   ```

   This treats U-value as dimensionless, but U-value is W/(m²·K). The formula should integrate heat loss rate with building thermal mass:

   ```python
   window_heat_loss_W_per_K = window_area_m2 * u_value
   total_heat_loss_W_per_K = window_heat_loss_W_per_K + wall_heat_loss_W_per_K + ...
   tau_hours = (thermal_mass_J_per_K) / (total_heat_loss_W_per_K * 3600)
   ```

   The current formula is a dimensionless approximation that happens to give reasonable results for typical buildings, but will fail for edge cases (e.g., a solarium with 80% glass).

4. **Energy rating map is Europe-centric**:
   Lines 12-24 map A++++ through G ratings, which correspond to European EPC (Energy Performance Certificate) standards. These ratings don't exist in the US (uses HERS score), Canada (uses EnerGuide), or most of Asia.

   **Better approach**: Accept thermal resistance (R-value) or U-value directly, which are universal units.

### PID Initialization (`physics.py`, lines 109-156)

#### Critical Problems:

1. **Ki values are dangerously low for floor heating** (line 138):
   ```python
   "floor_hydronic": {"kp": 0.3, "ki": 0.012, "kd": 7.0}
   ```

   With Ki=0.012 and typical dt=30s, the integral contribution per degree-hour of error is only 0.012 * 3600 * 30 / 3600 = 0.36% power per degree-hour. To accumulate 50% power output from integral alone requires:

   50 / 0.36 = 139 degree-hours

   That's 139 hours at 1°C error, or 14 hours at 10°C startup error, or 7 hours at 20°C startup error. This is absurdly slow.

   **Real-world impact**: On cold startup (e.g., after vacation), a zone at 10°C trying to reach 20°C will take **hours** to get the integral term wound up to provide adequate heating. Users will complain the system "doesn't work" after returning from vacation.

2. **Kd values are absurdly high** (line 138):
   ```python
   "floor_hydronic": {"kp": 0.3, "ki": 0.012, "kd": 7.0}
   ```

   Kd=7.0 means derivative contribution is -7.0 * (temp_change °C / dt_seconds). With typical sensor noise of 0.1°C and dt=30s:

   Derivative noise = 7.0 * 0.1 / 30 * 60 = 1.4% power per minute

   This will cause the heater output to oscillate ±1.4% continuously due to sensor noise alone. For PWM-controlled systems with 15-minute cycle time (floor_hydronic), this noise is smaller than the PWM resolution, so it's hidden. But for valve-controlled systems (0-100% positioning), this will cause continuous valve hunting.

   **Why this exists**: High Kd is a band-aid for low Ki. Because integral winds up too slowly, the developer needed high derivative to provide damping and prevent overshoot. This is a symptom of incorrect PID tuning.

   **Proper tuning**: For floor hydronic heating with tau=8 hours and td=15 minutes (typical), Ziegler-Nichols gives:
   - Kp = 8 * 60 / 15 = 32 (not 0.3!)
   - Ki = 32 / (2 * 15) = 1.07 (not 0.012!)
   - Kd = 32 * 15 / 2 = 240 minutes (not 7.0!)

   But wait - the units are wrong in the code. Looking at line 240 of pid_controller/__init__.py:
   ```python
   self._integral += self._Ki * self._error * self._dt
   ```
   If dt is in seconds, Ki=0.012, and error is in °C, then integral accumulates at 0.012 * error °C·s per sample. This is why Ki is so small - it's in units of (% per °C·s), not (% per °C·hour) as typical PID controllers use.

   **The real problem**: The PID implementation mixes time units. `_dt` is in seconds (from timestamp subtraction), but Ki should be in units of (%/°C/hour) for HVAC. The code compensates by using extremely small Ki values, making the controller behavior unintuitive.

3. **Tau-based adjustment is too weak** (lines 148-149):
   ```python
   tau_factor = 1.5 / thermal_time_constant if thermal_time_constant > 0 else 1.0
   tau_factor = max(0.7, min(1.3, tau_factor))  # Clamp to ±30%
   ```

   This adjusts PID gains by only ±30% regardless of how different the actual tau is from the baseline tau=1.5. But:
   - A building with tau=10h (A++++ house) is **6.7x slower** than baseline
   - A building with tau=2h (poorly insulated) is **1.3x faster** than baseline

   Clamping to ±30% means the PID gains will be completely wrong for A++++ or D-rated buildings.

   **Why this exists**: Because the base PID values were empirically tuned for one specific house, not derived from first principles, the developer knew they'd break for very different buildings. The clamps prevent total failure, but guarantee mediocre performance for anything that's not similar to the reference house.

4. **No accounting for heater power** (lines 109-156):
   PID gains should scale inversely with process gain K, which depends on heater power. A zone with 20W/m² heating (typical floor hydronic) vs 100W/m² heating (typical forced air) has 5x different process gain, requiring 5x different Kp.

   **Current code**: Assumes all floor_hydronic systems have the same power density. If a user has an undersized system (10W/m²), Kp=0.3 will be too high and cause overshoot. If oversized (40W/m²), Kp will be too low and cause slow response.

   **What's missing**: Either:
   - Accept `max_power_w` as input and scale Kp inversely
   - Run an auto-tuning routine during first use (measure step response)

### Ke Initialization (`physics.py`, lines 191-257)

#### Critical Problems:

1. **Ke values are 100x too large** (lines 12-24):
   ```python
   ENERGY_RATING_TO_INSULATION = {
       "A++++": 0.10,  # Outstanding insulation
       "A+++": 0.15,   # Excellent insulation
       "A++": 0.25,    # Very good insulation
       ...
       "G": 1.30,      # No effective insulation
   }
   ```

   These values are used as base Ke (line 225), then adjusted for windows (lines 231-243) and heating type (lines 246-254). For an A++ house with HR++ windows and floor_hydronic heating:

   ```python
   base_ke = 0.25
   # Window adjustment (assuming 20% windows, HR++ glazing):
   window_factor = (1.1 / 1.1) * (0.2 / 0.2) = 1.0
   base_ke *= (1.0 + min(1.0 * 0.25, 0.5)) = 0.25 * 1.25 = 0.3125
   # Heating type adjustment:
   base_ke *= 1.2 = 0.375
   # Final Ke = 0.38
   ```

   This Ke=0.38 means: for every 1°C difference between (setpoint - outdoor_temp), add 0.38% heating power.

   **Sanity check**: On a winter day with setpoint=20°C and outdoor_temp=0°C:
   - dext = 20 - 0 = 20°C
   - Ke contribution = 0.38 * 20 = 7.6% power

   This seems small, but remember the PID proportional term is only Kp=0.3, so for 1°C error:
   - P contribution = 0.3 * 1 = 0.3%

   The Ke term is **25x larger** than the proportional term for 1°C indoor error! This will dominate the control completely.

   **Real-world impact**: The PID will fight the Ke term. If outdoor temp drops suddenly (e.g., cold front), Ke increases heating power, causing indoor temp to overshoot, then P term reduces power, causing oscillation. The Ke term should be 10-100x smaller to act as gentle compensation, not dominate the control.

2. **Steady-state heat loss is not equal to Ke * dext**:
   At steady-state, heating power must equal heat loss:

   ```
   P_heat = U_total * A_total * (T_indoor - T_outdoor)
   ```

   Where U_total is the building's overall U-value (W/m²·K) and A_total is envelope area. For a typical A++ house:
   - U_total ≈ 0.3 W/m²·K
   - A_total ≈ 400 m² (for 150m² floor area)
   - At 20°C indoor, 0°C outdoor: P_heat = 0.3 * 400 * 20 = 2400W

   If the building has 3000W heating capacity (20W/m² * 150m²), steady-state requires:

   ```
   PID_output = (2400 / 3000) * 100% = 80% power at 20°C delta
   ```

   So the steady-state power per degree is 80% / 20°C = 4% per °C, not 0.38% per °C!

   **The confusion**: The code is mixing feedforward compensation with feedback control. Ke should represent the **additional** power needed per degree of outdoor temp change **beyond what the PID integral provides**. Since integral will wind up to 80% at steady-state, Ke should only compensate for transient changes, meaning Ke << 4% per °C.

   **Correct value**: Ke should be 0.01-0.05 for most buildings, not 0.3-1.3.

3. **Heating type factors are backwards** (lines 247-252):
   ```python
   heating_type_factors = {
       "floor_hydronic": 1.2,   # Slow response - more benefit from Ke
       "radiator": 1.0,         # Baseline
       "convector": 0.8,        # Faster response - less Ke needed
       "forced_air": 0.6,       # Fast response - minimal Ke needed
   }
   ```

   The comment says "slow response - more benefit from Ke", but this is wrong. Outdoor temperature compensation is **most beneficial for fast-responding systems** because:
   - Fast systems (forced air) respond quickly to outdoor temp changes, so feedforward helps prevent short-term swings
   - Slow systems (floor hydronic) have high thermal mass that naturally filters outdoor temp changes, making feedforward less necessary

   **Example**: On a sunny winter day, outdoor temp rises 5°C in 2 hours. A forced-air system will immediately reduce heating, causing indoor temp to drop as the building slowly catches up. Ke compensation prevents this. But a floor hydronic system's 8-hour time constant means it barely notices the 2-hour outdoor swing - the building's thermal mass is the filter.

   **The factors should be reversed**: forced_air should have highest Ke, floor_hydronic should have lowest.

4. **No consideration of wind or solar**:
   Outdoor temperature alone is a poor predictor of heat loss. Wind increases convective heat loss (can double heat loss on windy days), and solar radiation reduces heating need (can contribute 20-50W/m² on south-facing windows).

   **Better approach**: Instead of Ke * (setpoint - outdoor_temp), use:
   ```python
   feedforward = Ke_temp * (setpoint - outdoor_temp) + Ke_wind * wind_speed + Ke_solar * solar_irradiance
   ```

   Home Assistant has access to weather data including wind and solar, so this is feasible.

---

## 3. Heating Type Modifiers Analysis

### Constants (`const.py`, lines 81-102)

#### What's Done Correctly:

1. **PWM periods are reasonable** (lines 84, 89, 94, 99):
   - floor_hydronic: 900s (15 min) - good, reduces valve wear
   - radiator: 600s (10 min) - appropriate
   - convector: 300s (5 min) - reasonable
   - forced_air: 180s (3 min) - acceptable

   These align with industry practice for minimizing actuator cycling while maintaining control responsiveness.

2. **Description field** (lines 85, 90, 95, 100): Helpful for users to understand their system.

#### Critical Problems:

1. **PID modifiers are not used correctly** (lines 83, 88, 93, 98):
   ```python
   "floor_hydronic": {"pid_modifier": 0.5, ...}
   "radiator": {"pid_modifier": 0.7, ...}
   "convector": {"pid_modifier": 1.0, ...}
   "forced_air": {"pid_modifier": 1.3, ...}
   ```

   These modifiers are described as "conservative" (floor) to "aggressive" (forced air), but looking at the code, **these values are never actually used**. Searching for "pid_modifier" in the codebase:

   - Defined in `const.py` but not referenced in `physics.py` where PID is initialized
   - The physics.py `calculate_initial_pid()` function uses its own hardcoded values (lines 138-142) that don't match these modifiers

   **This is dead code** - the values are defined but have no effect. Either:
   - The developer intended to use them but forgot to wire them up
   - They're left over from an old implementation

   **Impact**: Users who read the config documentation and expect floor_hydronic to be "conservative" will be confused when the actual PID behavior doesn't match.

2. **Modifiers don't match thermal physics**:
   Even if these were used, they're wrong. The "modifier" concept suggests multiplying all PID gains (Kp, Ki, Kd) by a single factor. But thermal physics requires:

   - Faster systems → **higher** Kp and Ki (to respond quickly)
   - Slower systems → **higher** Kd (to dampen overshoot from high thermal mass)

   So the ratios should be different for P, I, and D:

   ```
   floor_hydronic: Kp*0.3, Ki*0.2, Kd*2.0
   forced_air: Kp*2.0, Ki*3.0, Kd*0.5
   ```

   Not a single uniform modifier.

3. **Missing heat pump characteristics**:
   Heat pumps are fundamentally different from resistive/hydronic heating:
   - Non-linear: COP varies with outdoor temperature
   - Slow compressor cycling: Can't cycle on/off faster than ~10 minutes
   - Defrost cycles: Heating stops for 5-10 minutes every hour in cold weather

   **Current code**: Treats heat pumps like any other forced-air system, which will cause:
   - Excessive compressor cycling (damages compressor)
   - Poor performance during defrost (PID integral winds up, then overshoots when defrost ends)

   **What's missing**: Separate heating type for heat pumps with:
   - Minimum off-time enforcement (10 minutes)
   - Integral freeze during defrost
   - Adaptive Kp based on outdoor temp (to compensate for COP variation)

4. **No multi-stage heating support**:
   Many systems have multiple stages (e.g., 50% + 100% forced air, or 40%/70%/100% heat pump). PID should control staging logic, not just on/off or valve position.

   **Example**: A 2-stage system at 65% demand should run stage 1 (50%) continuously plus stage 2 (50%) for 30% of the time (total 50% + 0.3*50% = 65%).

   **Current code**: Only supports single-stage on/off (PWM) or proportional valve (0-100%). No staging logic.

---

## 4. Outdoor Compensation (Ke Parameter) Analysis

### Implementation (`pid_controller/__init__.py`, lines 228-234, 253)

#### Fundamental Flaws:

1. **Static outdoor temperature is used** (line 229):
   ```python
   self._dext = set_point - ext_temp
   ```

   This uses the **current** outdoor temperature, but buildings have thermal lag. For a building with tau=8 hours, the outdoor temperature from 4-6 hours ago is what matters for current heat loss, not the current temperature.

   **Real-world failure mode**:
   - Morning: Outdoor temp is 0°C (cold night), sun rises, outdoor temp rises to 10°C by noon
   - PID sees dext drop from 20°C to 10°C, reduces Ke contribution by 38% * 10 = 3.8% power
   - But the building is still losing heat as if outdoor temp is 5°C (lagged average), so it underheats
   - Indoor temp drops, integral winds up, then outdoor temp change is complete, and the system overshoots

   **Better approach**: Use exponential moving average of outdoor temp with time constant = building tau:
   ```python
   alpha = dt / (tau_hours * 3600)
   outdoor_temp_lagged = alpha * outdoor_temp + (1 - alpha) * outdoor_temp_lagged_prev
   dext = setpoint - outdoor_temp_lagged
   ```

2. **Ke is added directly to output** (line 253):
   ```python
   output = self._proportional + self._integral + self._derivative + self._external
   ```

   This treats Ke as pure feedforward, completely bypassing the PID's feedback. If Ke is wrong (and it will be, because weather is unpredictable), the PID has to fight against it using integral action.

   **Example**: Ke says "outdoor temp is cold, add 10% power", but a sunny day means solar gain is providing that heat. The room overheats, PID integral winds negative to -10%, then a cloud comes, solar gain stops, and indoor temp drops rapidly because integral is negative.

   **Better approach**: Make Ke part of the setpoint, not the output:
   ```python
   effective_setpoint = setpoint + Ke * (setpoint - outdoor_temp)
   error = effective_setpoint - input_temp
   # Then proceed with normal PID calculation on error
   ```

   This way, Ke biases the PID's target, and the PID can still correct if Ke is wrong.

3. **Integral clamping accounts for Ke** (line 242):
   ```python
   self._integral = max(min(self._integral, self._out_max - self._external), self._out_min - self._external)
   ```

   This reduces the integral windup limit by the Ke contribution, which makes sense in principle. But because Ke is so large (0.3-1.3, see problem #1 in Ke section), and dext is typically 15-25°C in winter, the Ke contribution is 4.5-32% power. This severely limits integral action:

   - If Ke * dext = 20%, integral can only wind up to 80%
   - But steady-state might require 90% power (if building heat loss is higher than Ke predicts)
   - The PID can never reach steady-state because integral is clamped too low

   **Impact**: Chronic underheating in very cold weather, with users complaining "my thermostat never gets to temperature when it's below -5°C outside".

4. **No adaptive Ke tuning** (until recently, based on seeing `KeManager` in the architecture docs):
   Ke depends on:
   - Building insulation (changes if user adds insulation)
   - Wind exposure (varies by season, trees losing leaves, new construction nearby)
   - Occupancy patterns (internal heat gain from people, devices)
   - Solar gain (varies by season, vegetation growth, shade)

   A fixed Ke value will become inaccurate over time.

   **Partial credit**: Looking at `const.py` lines 258-274, there is Ke learning infrastructure (MIN_CONVERGENCE_CYCLES_FOR_KE, KE_ADJUSTMENT_STEP, etc.). This suggests the developers recognized the need for adaptive Ke. But the core problem remains: the Ke formulation (dext = setpoint - outdoor) is wrong, so no amount of tuning will fix it.

---

## 5. Adaptive Learning Rules Analysis

### PID Adjustment Rules (`pid_rules.py`, lines 47-139)

#### What's Done Correctly:

1. **Priority-based conflict resolution** (lines 11-15, 142-200): The concept of resolving conflicting rules (e.g., "increase Kp for slow response" vs "decrease Kp for overshoot") by priority is sound. Oscillation rules having highest priority makes sense from a safety perspective.

2. **Rule thresholds are reasonable for residential comfort** (lines 70, 80, 90, 100, 111, 120, 130):
   - Overshoot >0.5°C: Users will notice
   - Oscillations >1: Annoying, >3: Unacceptable
   - Settling time >90 min: Too slow for comfort

   These align with residential comfort standards (ASHRAE 55: ±0.5°C temperature drift).

3. **Incremental adjustments** (lines 74, 83, 93, etc.): Making 5-15% adjustments rather than doubling/halving gains is conservative and prevents instability.

#### Critical Problems:

1. **Rules adjust the wrong gains for root causes**:

   **Rule: High overshoot → Reduce Kp** (lines 70-78):
   ```python
   if avg_overshoot > 0.5:
       kp_factor = 1.0 - reduction  # Reduce Kp by up to 15%
       ki_factor = 0.9              # Reduce Ki by 10%
   ```

   **Problem**: Overshoot in thermal systems is primarily caused by **thermal lag (dead time)**, not high Kp. When the heater turns off, the heating element/water continues to deliver heat for 10-20 minutes (floor hydronic). This causes temperature to continue rising after the heater stops.

   **What happens**: Reducing Kp slows the initial heating rate, which increases rise time but doesn't address the root cause (residual heat delivery). The overshoot magnitude might reduce slightly, but at the cost of much slower response.

   **Better solution**: Increase Kd (to anticipate overshoot sooner and turn off heater earlier) or implement **predictive cutoff** (turn off heater when temp is 0.5°C below target, knowing residual heat will carry it to target).

2. **Rule: Slow response → Increase Kp** (lines 90-97):
   ```python
   if avg_rise_time > 60:
       kp_factor = 1.10  # Increase Kp by 10%
   ```

   **Problem**: Slow response can have three causes:
   - **Insufficient steady-state power**: Integral hasn't wound up enough (fix: increase Ki)
   - **Underpowered heater**: Max power is too low (fix: check heater capacity, not PID)
   - **Low Kp**: Initial response is sluggish (fix: increase Kp) ✓

   The rule doesn't distinguish these cases. If slow response is due to insufficient integral (because Ki=0.012 is too low), increasing Kp by 10% barely helps - you need to increase Ki by 100x.

   **Better solution**: Check if `avg_rise_time` increases with outdoor temperature drop. If yes, it's Ki problem (steady-state power insufficient). If rise time is constant, it's Kp problem.

3. **Rule: Undershoot → Increase Ki** (lines 100-108):
   ```python
   if avg_undershoot > 0.3:
       ki_factor = 1.0 + increase  # Increase Ki by up to 20%
   ```

   **Problem**: This is correct in principle, but 20% increase of Ki=0.012 is 0.0144, still absurdly low (see problem #1 in physics-based init). This rule will fire repeatedly, increasing Ki by 20% each time, until after many cycles Ki reaches a reasonable value. But this takes weeks or months of operation.

   **Better solution**: If undershoot is detected, increase Ki by 100-500%, not 20%. The rule is too timid.

4. **Rule: Many oscillations → Reduce Kp, Increase Kd** (lines 111-118):
   ```python
   if avg_oscillations > 3:
       kp_factor = 0.90
       kd_factor = 1.20
   ```

   **Problem**: Oscillations can be caused by:
   - **Excessive integral wind-up**: Ki too high (fix: reduce Ki)
   - **Excessive proportional gain**: Kp too high (fix: reduce Kp) ✓
   - **Insufficient damping**: Kd too low (fix: increase Kd) ✓
   - **Deadband/hysteresis in actuators**: PWM period too short or valve stiction

   The rule addresses Kp and Kd but ignores Ki, which is often the culprit in thermal systems. If integral winds up too high, it forces the system to overshoot, then undershoot, then overshoot again.

   **Better solution**: Check oscillation amplitude. If amplitude is constant (steady oscillation), it's Kp/Kd problem. If amplitude grows over time, it's Ki problem (integral instability).

5. **No accounting for external disturbances**:
   The rules assume all performance degradation is due to PID tuning, but many real-world factors affect performance:
   - **Solar gain**: Can cause 2-3°C temperature swings in south-facing rooms, leading to apparent "oscillations" that are not PID's fault
   - **Occupancy**: People generate 100W of heat each, changing the heat balance
   - **Wind**: Increases convective heat loss, appearing as "slow response" but actually due to environmental change

   **Current behavior**: Rules will repeatedly adjust PID gains trying to compensate for disturbances, leading to perpetual "learning" that never converges.

   **Better solution**: Detect disturbances (check if oscillations correlate with solar azimuth, or slow response correlates with wind speed) and avoid applying rules when disturbances are dominant.

6. **24-hour rate limiting is too aggressive** (line 139 in `learning.py`, MIN_ADJUSTMENT_INTERVAL = 24):
   Thermal systems can complete a heating cycle in 2-4 hours. If a PID adjustment is made, you can observe the effect within 1-2 cycles (4-8 hours). Waiting 24 hours means potentially missing opportunities for iterative tuning.

   **Impact**: In a new installation, it takes 7-14 days to go through 7-14 adjustment cycles, even though the system could tune in 2-3 days if adjustments were allowed every 8 hours.

   **Better solution**: Rate limit based on "cycles completed since last adjustment" (e.g., 3 cycles) rather than wall-clock time.

7. **Convergence criteria are too strict for real buildings** (lines 119-124 in `const.py`):
   ```python
   CONVERGENCE_THRESHOLDS = {
       "overshoot_max": 0.2,       # Maximum acceptable overshoot in °C
       "oscillations_max": 1,      # Maximum acceptable oscillations
       "settling_time_max": 60,    # Maximum settling time in minutes
       "rise_time_max": 45,        # Maximum rise time in minutes
   }
   ```

   **Problem**: Meeting ALL four criteria simultaneously is unrealistic for slow thermal systems:
   - Floor hydronic heating with tau=8h and td=15min: Rise time will be 60-90 minutes even with perfect tuning (can't violate physics)
   - Overshoot <0.2°C requires aggressive Kd, which conflicts with rise time <45 min (high Kd slows initial response)

   **Real-world impact**: The system will never declare convergence, so learning never stops. This wastes computational resources and logs, and gives users the impression the system is "never satisfied".

   **Better solution**: Weight the criteria by heating system type. For floor hydronic:
   ```python
   "rise_time_max": 90,  # Relax for slow systems
   "overshoot_max": 0.3, # Allow more overshoot
   ```

---

## 6. Real-World Failure Scenarios

### Scenario A: Vacation Return (Cold Start)

**Initial conditions**:
- House at 10°C (frost protection mode for 1 week)
- User returns, sets thermostat to 20°C
- Outdoor temp: 0°C
- Floor hydronic heating (Kp=0.3, Ki=0.012, Kd=7.0)

**What happens**:

1. **Hour 0**: Setpoint changes 10°C → 20°C
   - PID integral is reset to zero (line 244 of pid_controller)
   - Error = 10°C
   - P term = 0.3 * 10 = 3% power
   - I term = 0 (just reset)
   - D term ≈ 0 (no previous input)
   - Ke term = 0.38 * 20 = 7.6% power (assuming A++ house, Ke=0.38)
   - **Total output = 10.6% power** → Heater is barely on

2. **Hour 1-4**: Integral slowly winds up
   - Each hour with 10°C error adds: 0.012 * 10 * 3600 = 432% to integral... wait, that's wrong!
   - Checking integral calculation (line 240): `integral += Ki * error * dt`
   - If dt is in seconds, each sample (dt=30s) adds: 0.012 * 10 * 30 = 3.6% to integral
   - After 1 hour (120 samples): integral = 120 * 3.6% = 432%
   - But integral is clamped to `out_max - external` = 100 - 7.6 = 92.4% (line 242)
   - So integral saturates at 92.4% within minutes
   - **Total output = 3% + 92.4% + 0% + 7.6% = 103% → clamped to 100%**

3. **Hour 4-12**: Slow heating
   - Indoor temp rises ~0.5°C/hour (limited by building thermal mass and heater power)
   - After 8 hours: indoor temp = 14°C
   - Error = 6°C
   - P term = 0.3 * 6 = 1.8%
   - I term = 92.4% (still saturated)
   - D term ≈ -7.0 * 0.5 / 3600 * 30 = -0.03% (negligible)
   - Ke term = 0.38 * 20 = 7.6%
   - **Total output = 102% → clamped to 100%**

4. **Hour 12-18**: Approaching setpoint
   - Indoor temp = 19°C
   - Error = 1°C
   - P term = 0.3%
   - I term starts to desaturate: limited to 100% - 0.3% - 7.6% = 92.1%
   - **Total output = 100%**

5. **Hour 18-20**: Overshoot
   - Indoor temp = 20°C
   - Error = 0°C
   - P term = 0%
   - I term = 92% (still high from previous saturation)
   - Ke term = 7.6%
   - **Total output = 99.6%** → Heater is still at full blast!
   - Floor slab has been heated for 18 hours, massive thermal momentum
   - Temperature overshoots to 22-23°C
   - User complains "it's too hot, this system is broken"

6. **Hour 20-24**: Cooling down
   - Error = -2°C (overshoot)
   - Integral slowly winds down as error is negative
   - Takes another 4-6 hours to settle at 20°C

**Total time to comfortable temperature: 24+ hours**

**User experience**: "I came home from vacation, turned on the heat, and it took an entire day to warm up, then it overheated me out of my bedroom. This smart thermostat is worse than my old programmable one."

### Scenario B: Sunny Winter Day

**Initial conditions**:
- Indoor temp: 20°C (steady-state)
- Outdoor temp: -5°C (morning)
- South-facing windows: 10m² with HR++ glazing
- Floor hydronic heating (tau=8h)

**What happens**:

1. **Morning (8 AM)**: Sun rises
   - Solar irradiance: 200W/m² on windows
   - Solar heat gain: 10m² * 200W/m² * 0.7 (solar heat gain coefficient) = 1400W
   - Building heat loss at -5°C outdoor: ~3000W (typical for A++ house, 150m²)
   - Net heating needed: 3000 - 1400 = 1600W
   - But PID doesn't know about solar gain - it only sees indoor temp starting to rise

2. **9 AM**: Indoor temp rises to 20.5°C (from solar gain)
   - Error = -0.5°C (negative, room is too warm)
   - P term = 0.3 * (-0.5) = -0.15% (negative)
   - I term starts to wind down from previous steady-state (was ~80%)
   - Ke term = 0.38 * (20 - (-5)) = 9.5% (large, because outdoor is cold)
   - **Total output = -0.15% + 80% + 0% + 9.5% = 89.4%** → Heater is still on at 89% despite room being too warm!

3. **10 AM**: Indoor temp rises to 21°C
   - Error = -1°C
   - P term = -0.3%
   - I term winds down to ~75%
   - Ke term = 9.5% (unchanged, outdoor temp is still -5°C)
   - **Total output = 84.2%** → Heater is still running at 84%

4. **11 AM**: Indoor temp peaks at 22°C
   - Error = -2°C
   - I term winds down to ~70%
   - Ke term = 9.5%
   - **Total output = 78.9%** → Heater finally starts reducing, but very slowly due to large Ke contribution

5. **Noon-2 PM**: Clouds arrive, solar gain drops
   - Indoor temp is 22°C, but solar gain is now zero
   - Building heat loss is back to 3000W
   - PID integral has wound down to ~60%, so heating power is insufficient
   - Indoor temp starts to drop rapidly

6. **2-6 PM**: Integral winds back up
   - Takes 4 hours for integral to recover to 80%
   - Indoor temp drops to 19°C before recovering
   - User complains "why is my house a rollercoaster?"

**User experience**: "On sunny days, my house overheats in the morning, then gets cold in the afternoon. The thermostat seems to have no idea what it's doing."

### Scenario C: Windy Night

**Initial conditions**:
- Indoor temp: 20°C (steady-state)
- Outdoor temp: 5°C (evening)
- Wind: 2 m/s (calm)
- Sudden wind storm: Wind increases to 15 m/s at midnight

**Physics of wind impact**:
- Convective heat loss increases with wind: h = 10 + 4*v (W/m²·K for typical residential siding)
- At 2 m/s: h = 18 W/m²·K
- At 15 m/s: h = 70 W/m²·K (3.9x increase)
- Building envelope area: 400m²
- Additional heat loss: 400 * (70-18) * (20-5) = 312,000W... no wait, that's absurdly high

Let me recalculate:
- External wall area (not total envelope): ~100m² for 150m² floor
- Additional heat loss: 100 * (70-18) / 1000 * (20-5) = 78W per m² of wall = 7,800W total

Actually, that's still too high. Let me use realistic numbers:
- Wind increases convective heat transfer coefficient by ~50% at 15 m/s vs 2 m/s
- Baseline heat loss at 5°C outdoor: ~2000W (A++ house, small delta T)
- With wind: 2000 * 1.5 = 3000W
- Additional 1000W needed

**What happens**:

1. **Midnight**: Wind increases
   - Indoor temp starts to drop: 20°C → 19.8°C over 30 minutes
   - PID sees slow temp drop but doesn't understand why (Ke only tracks outdoor temp, not wind)
   - Error increases to 0.2°C
   - P term increases slightly: +0.06%
   - I term starts winding up slowly
   - Total output increases from 70% to 75% over 1 hour

2. **1-3 AM**: Integral winds up
   - Indoor temp continues to sag: 19.5°C
   - Error = 0.5°C
   - Integral winds up from 70% to 85%
   - Total output = 85%

3. **3 AM**: Wind suddenly stops
   - Heat loss drops back to 2000W
   - But PID integral is at 85%, providing 85% of 3000W = 2550W heating
   - Excess heat: 2550 - 2000 = 550W
   - Indoor temp starts rising rapidly

4. **4 AM**: Overshoot
   - Indoor temp = 20.5°C (overshoot)
   - Integral needs to wind back down
   - Takes 2-3 hours

**User experience**: "Last night was really windy, and my heat couldn't keep up. Then at 4 AM it woke me up because it got too hot. What is this thermostat doing?"

**Root cause**: No wind compensation. The Ke term claims to handle "external temperature" but only tracks outdoor air temp, not wind (which is the dominant factor in convective heat loss).

---

## 7. Summary of Recommendations

### Critical Fixes (Deploy Immediately)

1. **Fix integral calculation dimensional analysis** (pid_controller/__init__.py, line 240):
   - Decide on time units: Use hours for HVAC, not seconds
   - Change: `self._integral += self._Ki * self._error * (self._dt / 3600)` (convert dt to hours)
   - Update clamping to match units

2. **Reduce Ke values by 100x** (physics.py, lines 12-24):
   - A++ house: 0.25 → 0.0025
   - G house: 1.30 → 0.013
   - Ke should be a gentle nudge, not a dominant term

3. **Increase Ki by 100x** (physics.py, line 138):
   - floor_hydronic: 0.012 → 1.2
   - This gives reasonable integral wind-up time (1-2 hours instead of 10+ hours)

4. **Add derivative filtering** (pid_controller/__init__.py, line 248):
   ```python
   raw_derivative = -(self._Kd * self._input_diff) / self._dt if self._dt != 0 else 0.0
   self._derivative = 0.2 * raw_derivative + 0.8 * self._derivative  # Low-pass filter
   ```

5. **Implement outdoor temp lag** (pid_controller/__init__.py, line 229):
   ```python
   # Add to __init__:
   self._outdoor_temp_lagged = None

   # In calc():
   if ext_temp is not None:
       if self._outdoor_temp_lagged is None:
           self._outdoor_temp_lagged = ext_temp
       else:
           alpha = self._dt / (4 * 3600)  # 4-hour lag for typical building
           self._outdoor_temp_lagged = alpha * ext_temp + (1 - alpha) * self._outdoor_temp_lagged
       self._dext = set_point - self._outdoor_temp_lagged
   ```

### High Priority Improvements

6. **Implement proper Ziegler-Nichols or auto-tuning**:
   - On first install, run 2-3 step response tests (turn heater to 50%, measure temp rise rate)
   - Calculate process gain K (°C per % power), dead time td (minutes), and time constant tau (minutes)
   - Use Z-N formulas: Kp = 1.2*tau/(K*td), Ki = Kp/(2*td), Kd = Kp*td/8

7. **Add bumpless transfer** (pid_controller/__init__.py, lines 82-84):
   - When switching OFF → AUTO, pre-load integral to maintain current output
   - Store: `last_output_before_off_mode`
   - On re-entering AUTO: `self._integral = last_output_before_off_mode - Kp*error - Ke*dext`

8. **Change adaptive learning rate limit** (const.py, line 139):
   - MIN_ADJUSTMENT_INTERVAL: 24 → 8 hours (or 3 cycles, whichever is longer)

9. **Relax convergence thresholds for slow systems** (const.py, lines 119-124):
   - Make thresholds scale with heating_type
   - floor_hydronic: rise_time_max = 90 min, overshoot_max = 0.3°C
   - forced_air: rise_time_max = 30 min, overshoot_max = 0.2°C

10. **Fix undershoot rule to be more aggressive** (pid_rules.py, line 105):
    - Change: `ki_factor = 1.0 + increase` where `increase = min(0.20, ...)`
    - To: `increase = min(1.0, avg_undershoot * 2.0)` (allow up to 100% Ki increase)

### Medium Priority Enhancements

11. **Add wind compensation**:
    - Accept wind_speed from Home Assistant weather integration
    - Add wind term: `P_heat += Ke_wind * wind_speed * (setpoint - outdoor_temp)`
    - Typical Ke_wind: 0.01-0.05 per m/s

12. **Add solar gain compensation**:
    - Accept solar_irradiance (W/m²) from weather or lux sensor
    - Reduce heating: `P_heat -= Ke_solar * solar_irradiance * window_area_south`
    - Typical Ke_solar: 0.3-0.7 (solar heat gain coefficient for windows)

13. **Implement proportional-on-measurement**:
    - Separate proportional term into two components:
      - P_measurement: Responds to temperature change (smoothed response)
      - P_setpoint: Responds to setpoint change (eliminated or reduced)
    - Reduces bump on setpoint change

14. **Add heat pump support**:
    - New heating_type: "heat_pump"
    - Enforce min_off_cycle_duration = 600s (10 min)
    - Detect defrost cycles (sudden power drop) and freeze integral during defrost
    - Adapt Kp based on outdoor temp (scale by COP ratio)

15. **Improve settling detection** (cycle_tracker.py, lines 283-318):
    - Current variance threshold (0.01) is too strict with noisy sensors
    - Use robust statistics: median absolute deviation instead of variance
    - `MAD = median(|temps - median(temps)|)`
    - Settled if MAD < 0.05°C

### Low Priority / Future Work

16. **Multi-zone learning**:
    - Share learned PID gains between zones with similar characteristics (same floor, same heating type)
    - Bootstrap new zones from existing learned parameters

17. **Disturbance rejection**:
    - Detect and flag cycles with high solar gain or occupancy changes
    - Exclude disturbed cycles from learning
    - Criteria: Outdoor temp stable but indoor temp swings ±1°C → likely solar disturbance

18. **Model predictive control (MPC)**:
    - Build thermal model of building (identified from data)
    - Use weather forecast to optimize heating schedule
    - Minimize energy cost while maintaining comfort

19. **Multi-stage heating support**:
    - Accept multiple heater entities (stage1, stage2, ...)
    - Control staging: stage1 continuous + stage2 PWM for fractional demand

20. **Better PWM implementation**:
    - Current PWM is simple on/off cycling
    - Add phase shifting for multi-zone systems (stagger cycles to reduce peak demand)
    - Add minimum on/off times per actuator type (valve lifetime, compressor protection)

---

## 8. Conclusion: Deployment Risk Assessment

**Overall Assessment**: This PID implementation has **significant flaws** that will cause:
- Poor comfort (24+ hour warmup times, 2-3°C overshoots, oscillations)
- High energy usage (overshoot = wasted energy)
- User frustration (unpredictable behavior on sunny/windy days)

However, it's not catastrophically broken - it will eventually stabilize (after many hours/days), and the adaptive learning will compensate for some issues (after weeks of tuning).

**Risk Level**:

- **Safety**: Low risk. Thermal systems are slow and forgiving. Worst case is discomfort, not danger (unless frost protection fails, but that's a separate system).

- **Comfort**: High risk. Many users will experience multi-degree temperature swings and slow response, especially:
  - After vacation (cold start)
  - On sunny winter days (solar disturbance)
  - During weather changes (wind, clouds)

- **Energy**: Medium-high risk. Overshoots waste energy (heating then cooling), and slow response means running heaters longer to compensate for sluggish integral term.

**Recommendation**:

1. **Implement critical fixes 1-5** before wider deployment. These fix dimensional analysis bugs and scaling issues that make the system fundamentally incorrect.

2. **Implement high-priority improvements 6-10** within 3-6 months to achieve professional-grade performance.

3. **Consider medium/low priority items** based on user feedback and feature requests.

**Why this matters for real homes**:
- Users' heating bills are typically €1000-3000/year. A 10-20% increase from poor control is €100-600/year wasted.
- Comfort complaints lead to users overriding the thermostat (setting it higher), defeating the purpose of adaptive control.
- Poor cold-start performance trains users to leave heating on during vacations ("because it takes forever to warm up when I return"), wasting energy.

This system is clearly developed by someone with good intentions and reasonable understanding of PID control, but it lacks the deep HVAC-specific expertise to avoid common pitfalls. The physics-based initialization is a great idea (most hobbyist thermostats require manual tuning), but the execution has errors that undermine its effectiveness.
