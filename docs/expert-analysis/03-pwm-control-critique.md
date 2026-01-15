# Critical Analysis: PWM Control Strategy for On/Off Heaters

## Executive Summary

After analyzing the PWM implementation in this Home Assistant thermostat component, I've identified **significant equipment compatibility concerns** that could lead to premature failures in certain HVAC systems. While the implementation shows sophistication with adaptive learning and short-cycle protection, **it is fundamentally designed for valve/contactor-based systems and lacks critical protections for compressor-based equipment**.

## Findings

### ✅ What Works Well

1. **Adaptive PWM periods by heating type** - Reasonable defaults:
   - Floor hydronic: 15 min
   - Radiator: 10 min
   - Convector: 5 min
   - Forced air: 3 min

2. **Short-cycle detection and mitigation** (`adaptive/pwm_tuning.py`):
   - Monitors cycle times and increases PWM period if average < 10 min
   - Health monitoring alerts at < 15 min (warning) and < 10 min (critical)
   - Acknowledges "excessive valve wear" risk

3. **Configurable min_cycle_duration protection**:
   - Lines 669-676 enforce minimum on/off times
   - Dynamically extends cycle periods if too short
   - Default is 00:00:00 (disabled) but user-configurable

4. **Cycle time enforcement** (lines 366, 430):
   - Rejects premature on/off commands: "Cycle is too short"
   - Compares against `_min_off_cycle_duration` and `_min_on_cycle_duration`

### ⚠️ Critical Gaps for Real HVAC Equipment

#### 1. **Compressor-Based Systems (Heat Pumps, AC) - MAJOR RISK**

**Problem**: No compressor-specific protection whatsoever.

**Reality Check**:
- Most compressor systems require **5-10 minute minimum off-times** (not configurable default of 0)
- Startup current draw is 5-8x normal running current
- Short cycling causes:
  - Compressor overheating and premature failure
  - Thermal shock to refrigerant system
  - Contactor welding from high inrush current
  - Voided warranties (most manufacturers specify minimum off-time)

**Evidence from code**:
```python
DEFAULT_MIN_CYCLE_DURATION = '00:00:00'  # Line 11, const.py - ZERO protection by default
```

Even the "forced_air" heating type (which often uses heat pumps) has:
- PWM period: 3 minutes
- No forced minimum off-time
- No compressor delay logic

**Verdict**: ❌ **UNSAFE for heat pumps and AC units without user intervention**

#### 2. **Boiler/Furnace Startup Delays - PARTIAL PROTECTION**

**Problem**: No equipment-specific warm-up/purge cycle awareness.

**Reality Check**:
- Condensing boilers need 30-60s pre-purge cycles (combustion safety)
- Post-purge cycles prevent condensation damage
- Pump overrun (2-5 min) after boiler shuts off to dissipate heat

**What the system does**:
- Treats boilers as simple on/off switches
- `source_startup_delay` (30s default) at COORDINATOR level for main heat source
- No zone-level awareness of boiler startup sequences

**Example risk scenario**:
```
PWM duty cycle = 30%, PWM period = 5 min (convector setting)
- Boiler ON for: 1.5 minutes
- Boiler OFF for: 3.5 minutes
```

If boiler needs 1 minute startup + 2 minute overrun = 3 minutes total, it's getting only 1.5 min of actual heating per cycle.

**Verdict**: ⚠️ **RISKY for boilers with tight PWM periods** - Works if user configures appropriate min_cycle_duration, but no validation or warnings.

#### 3. **Thermal Shock to Hydronic Components**

**Problem**: Even with longer PWM periods, rapid cycling damages components.

**Reality Check**:
- Mixing valves, zone valves, actuators have **rated cycle limits** (e.g., 10,000-100,000 cycles lifetime)
- Thermal expansion/contraction fatigues pipe joints
- Cast iron heat exchangers can crack from thermal shock

**What the system does**:
- `ValveCycleTracker` class (pwm_tuning.py) counts cycles
- But NO limits enforced, NO lifetime tracking, NO maintenance alerts
- "Valve wear" mentioned in warnings but no actionable guidance

**Math check** (floor_hydronic at 50% duty):
```
PWM period: 15 min
Cycles per day: 48 (24 hrs × 4 cycles/hr ÷ 2 for 50% duty)
Cycles per heating season (180 days): 8,640 cycles
```

For a valve rated at 50,000 cycles = ~6 year lifespan. **Acceptable but not tracked**.

#### 4. **Contactor/Relay Wear**

**Problem**: No consideration of electrical contact ratings.

**Reality Check**:
- Residential contactors: 100,000-200,000 mechanical operations
- Inductive loads (motors, transformers) cause contact arcing
- Ratings are for RESISTIVE loads; actual lifetime much lower for HVAC

**Worst case** (forced_air at 50% duty, 3-min PWM):
```
Cycles per day: 240 (24 hrs × 20 cycles/hr ÷ 2)
Cycles per year: 87,600
Contactor lifetime (200k cycles): ~2.3 years
```

**Verdict**: ⚠️ **ACCEPTABLE** for properly-rated contactors, but users have NO guidance on sizing.

#### 5. **No Equipment Type Validation**

**Problem**: System assumes all entities are PWM-compatible.

**Example config risk**:
```yaml
climate:
  - platform: adaptive_thermostat
    heater: climate.heatpump_thermostat  # Nested climate entity!
    pwm: "00:05:00"  # Tries to PWM-cycle another thermostat
```

**What happens**:
- System attempts to rapidly cycle the heat pump's internal thermostat
- Bypasses ALL of the heat pump's built-in protections
- Equipment failure likely

**Verdict**: ❌ **NO VALIDATION** - Users can configure dangerous setups.

#### 6. **Missing: Pump Interlock Logic**

**Problem**: Hydronic systems require pump running BEFORE/AFTER heat source.

**Reality**:
- Boiler/heat exchanger damage if fired without flow
- Pump must run 2-5 min after heating stops (dissipate residual heat)

**What the system does**:
- Allows multiple switches: `main_heater_switch: [switch.boiler, switch.pump]`
- Turns all on/off simultaneously (line 260-264, heater_controller.py)
- **NO SEQUENCING**: No "pump on first, heat source 30s later" logic

**Verdict**: ⚠️ **RISKY** - Works if equipment has internal interlocks, fails if user relies on HA for sequencing.

### 🟡 Ambiguous/Unclear Design Decisions

#### 1. **PWM Period Auto-Extension**

Code behavior (lines 669-676):
```python
if 0 < time_on < self._min_on_cycle_duration:
    time_off *= self._min_on_cycle_duration / time_on
    time_on = self._min_on_cycle_duration
```

**Question**: This EXTENDS the total cycle period beyond configured PWM period. Is this intentional?

**Example**:
- PWM period = 5 min, PID output = 10% (time_on = 30s)
- min_on_cycle_duration = 180s (3 min)
- New cycle: 3 min ON + 27 min OFF = **30 min total** (6x longer than PWM period!)

**Implication**: PWM period becomes "minimum on-time" rather than "cycle period" when duty cycle is low. This is actually SAFER for equipment but may confuse users expecting consistent cycle timing.

#### 2. **Insufficient Documentation on Equipment Compatibility**

README.md states (line 225):
```
| Type | Description | Kp | Ki | Kd | PWM Period |
| forced_air | Forced air / HVAC | 1.2 | 0.08 | 2.0 | 3 min |
```

**Missing**:
- Warning that "forced_air" = 3-min cycles may damage compressor-based systems
- Guidance on identifying compressor vs. furnace systems
- Requirement to set min_off_cycle_duration for heat pumps

## Recommendations

### Immediate (Safety-Critical)

1. **Add compressor detection/warning**:
   ```python
   if heating_type == "forced_air" and min_off_cycle_duration < 300:
       _LOGGER.warning("Heat pump/AC systems require min_off_cycle_duration >= 300s")
   ```

2. **Update documentation** with equipment compatibility matrix:
   - ✅ Safe: Modulating valves, resistive heaters, simple contactors
   - ⚠️  Requires config: Boilers (set min_cycle_duration), hydronic actuators
   - ❌ Unsafe: Heat pumps (without min_off_cycle >=5 min), nested climate entities, compressors

3. **Validate entity types** - Reject PWM mode for `climate.*` entities (likely nested thermostats with own logic).

### Medium Priority

4. **Add pump sequencing** option:
   ```yaml
   pump_lead_time: 30  # Seconds pump runs before heat source
   pump_overrun_time: 120  # Seconds pump runs after heat source
   ```

5. **Cycle lifetime tracking**:
   - Persist `ValveCycleTracker` count across restarts
   - Create maintenance reminder sensor at 80% of rated cycles

6. **PWM period floor enforcement**:
   - Prevent PWM < 180s (3 min) for anything except direct resistive loads
   - Add `equipment_type` config option: `resistive`, `valve`, `contactor`, `compressor`

### Nice-to-Have

7. **Equipment profiles** database:
   ```python
   EQUIPMENT_PROFILES = {
       "heat_pump": {
           "min_off_cycle": 300,
           "min_on_cycle": 180,
           "pwm_min": 600,
           "startup_delay": 30
       },
       # ...
   }
   ```

## Conclusion

**Overall Assessment**: ⚠️ **Suitable for SOME systems, dangerous for OTHERS**

### Safe for:
- ✅ Modulating valves (number/light entities) with valve mode (pwm=0)
- ✅ Simple resistive heaters via contactors/relays
- ✅ Hydronic zone valves (if min_cycle_duration configured)
- ✅ Boiler systems (if min_cycle_duration >= startup+overrun time)

### Unsafe for (without additional config):
- ❌ Heat pumps (3-min forced_air PWM will kill compressor)
- ❌ Air conditioning compressors (same issue)
- ❌ Any system with built-in cycle protection (nested climate entities)
- ❌ Boilers WITHOUT proper min_cycle_duration set

### Key Issue:
The system is **sophisticated in PID control and adaptive learning**, but **naïve about real HVAC equipment constraints**. The `min_cycle_duration: '00:00:00'` default is a **landmine** - it works fine for valves, but will destroy compressor equipment.

**Recommendation**: This should NOT be used for compressor-based systems (heat pumps, AC) unless the user explicitly configures protection. Documentation must be much clearer about this limitation.
