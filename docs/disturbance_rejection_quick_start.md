# Disturbance Rejection - Developer Quick Start

This guide provides quick reference for implementing disturbance rejection in adaptive learning.

## Problem Summary

**Before:** Solar gain causes 2°C overshoot → Learning reduces Kp → Next cycle (no sun) is sluggish → Learning increases Kp → Oscillates forever

**After:** Solar gain detected → Cycle excluded from learning → PID converges on clean cycles

## Key Concepts

### Disturbance Types

| Type | Symptom | Detection |
|------|---------|-----------|
| Solar Gain | Overshoot during settling | Sun azimuth matches window ± 45°, elevation >10° |
| Wind Loss | Slow rise, undershoot | Wind speed >15 km/h correlates with poor heating |
| Outdoor Swing | Oscillations, over/undershoot | Outdoor temp changes >2°C during cycle |
| Occupancy | Small overshoot (0.2-0.5°C) | Occupancy sensors active during cycle |

### Configuration Hierarchy

```
Domain Level (adaptive_thermostat:)
  └─ disturbance_rejection:
       ├─ enabled: true
       ├─ wind_sensor: sensor.outdoor_wind_speed
       ├─ wind_threshold: 15  # km/h
       └─ outdoor_temp_threshold: 2.0  # °C

Zone Level (climate:)
  ├─ outdoor_sensor: sensor.outdoor_temperature  # Already exists
  ├─ window_orientation: "south"  # Already exists
  └─ occupancy_sensors:  # NEW
       ├─ binary_sensor.living_room_motion
       └─ binary_sensor.living_room_occupancy
```

## Implementation Phases

### Phase 1: Detection Module (Independent)
**Goal:** Disturbance detection with no integration

**Files to Create:**
- `custom_components/adaptive_thermostat/adaptive/disturbance_detection.py`
- `tests/test_disturbance_detection.py`

**Key Classes:**
```python
@dataclass
class DisturbanceFlags:
    solar_gain: bool = False
    wind_loss: bool = False
    outdoor_temp_swing: bool = False
    occupancy_gain: bool = False
    any_disturbance: bool = False
    # Evidence strings for debugging
    solar_evidence: Optional[str] = None
    # ... more evidence fields

class DisturbanceDetector:
    def detect_disturbances(
        self,
        temperature_history: List[Tuple[datetime, float]],
        target_temp: float,
        cycle_start: datetime,
        cycle_end: datetime,
    ) -> DisturbanceFlags:
        """Main detection entry point."""
```

**Testing:**
```bash
pytest tests/test_disturbance_detection.py -v
```

### Phase 2: Data Model Update
**Goal:** Add disturbance field to CycleMetrics

**Files to Modify:**
- `custom_components/adaptive_thermostat/adaptive/cycle_analysis.py`

**Changes:**
```python
class CycleMetrics:
    def __init__(
        self,
        overshoot: Optional[float] = None,
        undershoot: Optional[float] = None,
        settling_time: Optional[float] = None,
        oscillations: int = 0,
        rise_time: Optional[float] = None,
        disturbances: Optional[DisturbanceFlags] = None,  # ADD THIS
    ):
        # ... existing fields ...
        self.disturbances = disturbances or DisturbanceFlags()  # ADD THIS
```

**Testing:**
```bash
pytest tests/test_cycle_analysis.py -v
```

### Phase 3: Cycle Tracker Integration
**Goal:** Detect disturbances during cycle finalization

**Files to Modify:**
- `custom_components/adaptive_thermostat/managers/cycle_tracker.py`

**Key Changes:**
```python
class CycleTrackerManager:
    def __init__(self, ..., disturbance_detector: Optional[DisturbanceDetector] = None):
        # ... existing init ...
        self._disturbance_detector = disturbance_detector

    async def _finalize_cycle(self) -> None:
        # ... existing validation ...

        # NEW: Detect disturbances
        disturbance_flags = None
        if self._disturbance_detector:
            disturbance_flags = self._disturbance_detector.detect_disturbances(
                temperature_history=self._temperature_history,
                target_temp=target_temp,
                cycle_start=self._cycle_start_time,
                cycle_end=datetime.now(),
            )

        # Create metrics with disturbance flags
        metrics = CycleMetrics(
            overshoot=overshoot,
            # ... other metrics ...
            disturbances=disturbance_flags,  # ADD THIS
        )
```

**Testing:**
```bash
pytest tests/test_cycle_tracker.py -v
pytest tests/test_integration_disturbance_cycle.py -v
```

### Phase 4: Learning Filter
**Goal:** Exclude disturbed cycles from PID adjustment

**Files to Modify:**
- `custom_components/adaptive_thermostat/adaptive/learning.py`

**Key Changes:**
```python
class AdaptiveLearner:
    def calculate_pid_adjustment(
        self,
        current_kp: float,
        current_ki: float,
        current_kd: float,
        min_cycles: int = MIN_CYCLES_FOR_LEARNING,
        min_interval_hours: int = MIN_ADJUSTMENT_INTERVAL,
        exclude_disturbed_cycles: bool = True,  # ADD THIS parameter
    ) -> Optional[Dict[str, float]]:
        # ... existing checks ...

        # NEW: Filter disturbed cycles
        if exclude_disturbed_cycles:
            clean_cycles = [
                c for c in self._cycle_history
                if not (c.disturbances and c.disturbances.any_disturbance)
            ]

            disturbed_count = len(self._cycle_history) - len(clean_cycles)
            if disturbed_count > 0:
                _LOGGER.info(
                    "Filtered %d disturbed cycles out of %d total",
                    disturbed_count,
                    len(self._cycle_history),
                )

            if len(clean_cycles) < min_cycles:
                _LOGGER.debug("Insufficient clean cycles for learning")
                return None

            recent_cycles = clean_cycles[-min_cycles:]
        else:
            recent_cycles = self._cycle_history[-min_cycles:]

        # ... rest of existing logic ...
```

**Testing:**
```bash
pytest tests/test_learning_disturbance_filtering.py -v
```

### Phase 5: Configuration & Services
**Goal:** Make disturbance rejection user-configurable

**Files to Modify:**
- `custom_components/adaptive_thermostat/const.py`
- `custom_components/adaptive_thermostat/__init__.py`
- `custom_components/adaptive_thermostat/climate.py`
- `custom_components/adaptive_thermostat/services.yaml`

**Constants to Add:**
```python
# const.py
CONF_DISTURBANCE_REJECTION = "disturbance_rejection"
CONF_DISTURBANCE_REJECTION_ENABLED = "enabled"
CONF_WIND_SENSOR = "wind_sensor"
CONF_WIND_THRESHOLD = "wind_threshold"
CONF_OUTDOOR_TEMP_THRESHOLD = "outdoor_temp_threshold"
CONF_OCCUPANCY_SENSORS = "occupancy_sensors"

DEFAULT_WIND_THRESHOLD = 15.0  # km/h
DEFAULT_OUTDOOR_TEMP_THRESHOLD = 2.0  # °C
SOLAR_GAIN_OVERSHOOT_MIN = 0.5  # °C
SOLAR_AZIMUTH_TOLERANCE = 45  # degrees
```

### Phase 6: Monitoring
**Goal:** Observable disturbance rejection metrics

**Files to Modify:**
- `custom_components/adaptive_thermostat/sensor.py`

**Sensor Attributes to Add:**
```python
# Add to learning metrics sensor
attributes = {
    # ... existing attributes ...
    "disturbance_rejection_enabled": self._enabled,
    "total_cycles": len(learner.cycle_history),
    "disturbed_cycles": sum(
        1 for c in learner.cycle_history
        if c.disturbances and c.disturbances.any_disturbance
    ),
    "disturbed_by_solar": sum(
        1 for c in learner.cycle_history
        if c.disturbances and c.disturbances.solar_gain
    ),
    # ... more disturbance counts ...
}
```

## Detection Algorithm Implementation

### Solar Gain Detection Template

```python
def _detect_solar_gain(
    self,
    temp_history: List[Tuple[datetime, float]],
    target_temp: float,
    cycle_start: datetime,
    cycle_end: datetime,
) -> Tuple[bool, Optional[str]]:
    """Detect solar gain disturbance."""

    # Check prerequisites
    if not self._sun_calculator:
        return False, None

    if self._window_orientation not in ["south", "east", "west", "southeast", "southwest", "roof"]:
        return False, None

    # Find temperature spikes in settling phase
    # (Implementation: iterate temp_history, find max temp after setpoint crossed)
    max_temp = None
    spike_time = None
    settling_started = False

    for timestamp, temp in temp_history:
        if not settling_started and temp >= target_temp - 0.05:
            settling_started = True

        if settling_started and (max_temp is None or temp > max_temp):
            max_temp = temp
            spike_time = timestamp

    if max_temp is None or spike_time is None:
        return False, None

    overshoot = max_temp - target_temp
    if overshoot < SOLAR_GAIN_OVERSHOOT_MIN:
        return False, None

    # Get sun position at spike time
    sun_pos = self._sun_calculator.get_position_at_time(spike_time)

    # Check elevation
    if sun_pos.elevation < self._min_sun_elevation:
        return False, None

    # Check azimuth match
    from .sun_position import ORIENTATION_AZIMUTH
    window_azimuth = ORIENTATION_AZIMUTH.get(self._window_orientation)

    if window_azimuth is None:  # roof/none
        # For roof/skylights, any azimuth is OK if elevation is high
        if sun_pos.elevation > 30:
            evidence = f"Sun elevation {sun_pos.elevation:.1f}° illuminating skylights at {spike_time.strftime('%H:%M')}"
            return True, evidence
        return False, None

    # Calculate azimuth difference (handle wrap-around at 0/360)
    azimuth_diff = abs(sun_pos.azimuth - window_azimuth)
    if azimuth_diff > 180:
        azimuth_diff = 360 - azimuth_diff

    if azimuth_diff <= SOLAR_AZIMUTH_TOLERANCE:
        evidence = (
            f"Sun azimuth {sun_pos.azimuth:.0f}° matched {self._window_orientation} windows "
            f"(target {window_azimuth}°) at {spike_time.strftime('%H:%M')}, "
            f"elevation {sun_pos.elevation:.1f}°"
        )
        return True, evidence

    return False, None
```

### Wind Loss Detection Template

```python
def _detect_wind_loss(
    self,
    temp_history: List[Tuple[datetime, float]],
    target_temp: float,
    rise_time: Optional[float],
) -> Tuple[bool, Optional[str]]:
    """Detect wind-induced heat loss."""

    if not self._wind_sensor_id or not self._hass:
        return False, None

    # Get wind speed during cycle
    # (Implementation: query sensor state, average over cycle duration)
    wind_state = self._hass.states.get(self._wind_sensor_id)
    if not wind_state or wind_state.state == "unknown":
        return False, None

    try:
        wind_speed = float(wind_state.state)
    except ValueError:
        return False, None

    # Check if wind is above threshold
    if wind_speed < self._wind_threshold:
        return False, None

    # Check if performance was degraded
    # Option 1: Slow rise time (requires expected_rise_time baseline)
    # Option 2: Presence of undershoot
    # Simplified: Just flag if wind is high and metrics show issues

    if rise_time and rise_time > 60:  # Arbitrary: >60 min is slow
        evidence = f"Wind speed {wind_speed:.1f} km/h during slow heating (rise time {rise_time:.1f} min)"
        return True, evidence

    # Could also check undershoot, but that requires passing it in
    # For now, just wind + slow heating

    return False, None
```

## Testing Checklist

### Unit Tests (Each Detection Algorithm)
- [ ] Positive case: Disturbance detected correctly
- [ ] Negative case: No disturbance when conditions not met
- [ ] Edge case: Missing sensors (graceful degradation)
- [ ] Edge case: Invalid sensor data (error handling)

### Integration Tests (Cycle Tracking)
- [ ] Disturbed cycle flagged correctly
- [ ] Clean cycle has no flags
- [ ] DisturbanceFlags persisted in CycleMetrics
- [ ] Logging shows disturbance evidence

### Learning Tests (Filtering)
- [ ] Disturbed cycles excluded from PID adjustment
- [ ] Insufficient clean cycles returns None
- [ ] Disturbance rejection can be disabled
- [ ] Clean cycles used correctly for metrics

### Validation Tests (Real-World Scenarios)
- [ ] Sunny winter day: Solar gain detected, Kp not reduced
- [ ] Windy day: Wind loss detected, Kp not increased
- [ ] Clean convergence: PID converges with clean cycles
- [ ] Mixed cycles: Learning uses clean subset

## Debugging Tips

### Enable Debug Logging
```yaml
# configuration.yaml
logger:
  default: info
  logs:
    custom_components.adaptive_thermostat.adaptive.disturbance_detection: debug
    custom_components.adaptive_thermostat.adaptive.learning: debug
    custom_components.adaptive_thermostat.managers.cycle_tracker: debug
```

### Check Disturbance Flags
```python
# In tests or logs, inspect:
metrics.disturbances.solar_gain
metrics.disturbances.solar_evidence
```

### Monitor Sensor Attributes
```yaml
# Developer Tools > States
sensor.adaptive_thermostat_living_room:
  disturbance_rejection_enabled: true
  total_cycles: 10
  disturbed_cycles: 3
  disturbed_by_solar: 2
  disturbed_by_wind: 1
```

### Test with Synthetic Data
```python
from tests.utils.disturbance_simulator import DisturbanceSimulator

# Generate solar gain cycle
history = DisturbanceSimulator.create_solar_gain_cycle(
    start_temp=18.0,
    target_temp=21.0,
    gain_time_offset_minutes=30,
    gain_magnitude=2.0,
)
```

## Common Pitfalls

### 1. Forgetting to Update `any_disturbance`
```python
# WRONG
flags = DisturbanceFlags()
flags.solar_gain = True
# flags.any_disturbance is still False!

# CORRECT
flags = DisturbanceFlags()
flags.solar_gain = True
flags.any_disturbance = True  # Or use a property/method
```

**Solution:** Use a method or property:
```python
@dataclass
class DisturbanceFlags:
    # ... fields ...

    def __post_init__(self):
        self.any_disturbance = any([
            self.solar_gain,
            self.wind_loss,
            self.outdoor_temp_swing,
            self.occupancy_gain,
        ])
```

### 2. Not Handling Missing Sensors Gracefully
```python
# WRONG
sun_pos = self._sun_calculator.get_position_at_time(spike_time)  # Crashes if None

# CORRECT
if not self._sun_calculator:
    return False, None

sun_pos = self._sun_calculator.get_position_at_time(spike_time)
```

### 3. Forgetting to Filter in Both Directions
```python
# WRONG: Only checks disturbances field exists
clean_cycles = [c for c in history if not c.disturbances]

# CORRECT: Also checks any_disturbance flag
clean_cycles = [
    c for c in history
    if not (c.disturbances and c.disturbances.any_disturbance)
]
```

### 4. Not Logging Evidence
```python
# WRONG
_LOGGER.info("Solar gain detected")

# CORRECT
_LOGGER.info("Solar gain detected: %s", disturbance_flags.solar_evidence)
```

## Performance Considerations

### Sun Position Calculations
- Cache sun position calculations (already implemented in `SunPositionCalculator`)
- Only calculate for cycles with overshoot (early exit)

### Sensor State Queries
- Minimize state queries (batch if possible)
- Handle unavailable sensors gracefully (don't spam logs)

### History Filtering
- Filter cycles once per PID adjustment, not per metric calculation
- Consider using generator expressions for large histories

## Rollback Procedure

If disturbance rejection causes issues:

1. **Quick disable (no restart):**
   ```yaml
   # Configuration.yaml
   adaptive_thermostat:
     disturbance_rejection:
       enabled: false
   ```

2. **Service call (immediate):**
   ```yaml
   service: adaptive_thermostat.set_disturbance_rejection
   data:
     entity_id: climate.living_room
     enabled: false
   ```

3. **Code rollback (nuclear option):**
   ```bash
   git revert <commit-hash>
   ```

## Resources

- **Full Plan:** `/PLAN_DISTURBANCE_REJECTION.md`
- **Architecture Diagrams:** `/docs/disturbance_rejection_architecture.md`
- **CLAUDE.md:** Project conventions and architecture
- **Existing Tests:** `tests/test_cycle_tracker.py`, `tests/test_learning.py`

## Questions?

Check the "Open Questions" section in `PLAN_DISTURBANCE_REJECTION.md` for design decisions and trade-offs.
