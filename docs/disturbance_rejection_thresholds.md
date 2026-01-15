# Disturbance Rejection - Detection Thresholds Reference

Quick reference for all detection thresholds and their rationale.

## Solar Gain Detection

### Thresholds
| Parameter | Default | Rationale |
|-----------|---------|-----------|
| Minimum overshoot | 0.5°C | Below this is likely PID tuning, not solar |
| Azimuth tolerance | ±45° | Effective sun angle for window illumination |
| Minimum elevation | 10° | Below this, sun too low for significant gain |
| Phase requirement | Settling only | Rise phase temp increases are expected |

### Window Orientations Affected
- **High sensitivity:** South, East, West, Southeast, Southwest, Roof
- **Low sensitivity:** North (minimal direct sun)
- **No detection:** None (no windows)

### Algorithm Logic
```
IF window_orientation in [south, east, west, southeast, southwest, roof]:
    IF overshoot > 0.5°C during settling phase:
        IF sun_azimuth matches window_azimuth ± 45°:
            IF sun_elevation > 10°:
                → Solar gain detected
```

### Real-World Examples

#### Detected (True Positives)
- South window, 2°C overshoot at 12:00 (sun azimuth 180°, elevation 35°)
- East window, 1.5°C overshoot at 08:00 (sun azimuth 90°, elevation 15°)
- West window, 1°C overshoot at 17:00 (sun azimuth 270°, elevation 20°)
- Skylight, 3°C overshoot at 13:00 (any azimuth, elevation 60°)

#### Not Detected (True Negatives)
- North window, 2°C overshoot at 12:00 (sun azimuth 180°, wrong direction)
- South window, 0.3°C overshoot at 12:00 (overshoot too small, likely PID)
- South window, 2°C overshoot at 06:00 (sun elevation 3°, below horizon)
- South window, 2°C overshoot at 20:00 (sun azimuth 300°, wrong angle)

#### Edge Cases
- Cloudy day with intermittent sun: May miss detection (acceptable trade-off)
- Reflected light from buildings: May cause false positive (rare)
- Multiple window orientations in one zone: Use primary orientation (configuration)

## Wind Loss Detection

### Thresholds
| Parameter | Default | Rationale |
|-----------|---------|-----------|
| Wind speed | 15 km/h | Below this, convective loss negligible |
| Rise time threshold | 60 min | Above this indicates slow heating |
| Correlation window | Full cycle | Wind must be present during heating |

### Algorithm Logic
```
IF wind_sensor configured:
    IF avg_wind_speed > 15 km/h during cycle:
        IF rise_time > 60 min OR undershoot present:
            → Wind loss detected
```

### Real-World Examples

#### Detected (True Positives)
- Wind 25 km/h, rise time 75 min (normally 45 min)
- Wind 20 km/h, undershoot 0.5°C despite proper heating

#### Not Detected (True Negatives)
- Wind 10 km/h, rise time 75 min (wind too low, likely PID issue)
- Wind 25 km/h, rise time 40 min (heating performance OK despite wind)

#### Edge Cases
- Gusty wind (intermittent): Use average wind speed
- Wind sensor far from zone: May not represent local conditions
- Wind direction: Not considered (could be future enhancement)

## Outdoor Temperature Swing Detection

### Thresholds
| Parameter | Default | Rationale |
|-----------|---------|-----------|
| Temperature change | 2°C | Below this is normal daily variation |
| Measurement window | Cycle duration | Start to end comparison |
| Direction | Absolute | Both drops and rises detected |

### Algorithm Logic
```
IF outdoor_sensor configured:
    outdoor_start = get_outdoor_temp(cycle_start)
    outdoor_end = get_outdoor_temp(cycle_end)
    change = abs(outdoor_end - outdoor_start)

    IF change > 2°C:
        → Outdoor swing detected
```

### Real-World Examples

#### Detected (True Positives)
- Outdoor: -5°C → -8°C during 1-hour cycle (3°C drop)
- Outdoor: 10°C → 13°C during 90-min cycle (3°C rise, cold front passed)

#### Not Detected (True Negatives)
- Outdoor: 5°C → 6°C during cycle (1°C change, normal)
- Outdoor: 10°C → 8°C during cycle (2°C change, at threshold)

#### Edge Cases
- Very short cycles (<30 min): Less likely to see large outdoor changes
- Very long cycles (>2 hours): More likely to flag (acceptable)
- Sensor lag: Outdoor temp reported every 5-10 min (acceptable)

## Occupancy Gain Detection

### Thresholds
| Parameter | Default | Rationale |
|-----------|---------|-----------|
| Minimum overshoot | 0.2°C | Below this is noise |
| Maximum overshoot | 0.5°C | Above this is likely PID issue |
| Occupancy window | Cycle duration | Any occupancy during cycle |

### Algorithm Logic
```
IF occupancy_sensors configured:
    IF any_occupancy_sensor == ON during cycle:
        IF 0.2°C < overshoot < 0.5°C:
            → Occupancy gain detected
```

### Real-World Examples

#### Detected (True Positives)
- Motion sensor active 09:00-10:00, overshoot 0.3°C (2 people present)
- Occupancy sensor active during cycle, overshoot 0.4°C (internal heat)

#### Not Detected (True Negatives)
- Motion sensor active, overshoot 0.1°C (overshoot too small, noise)
- Motion sensor active, overshoot 1.5°C (overshoot too large, PID issue)
- Motion sensor OFF, overshoot 0.3°C (no occupancy, different cause)

#### Edge Cases
- Pet motion: May cause false positive (acceptable, internal heat is internal heat)
- Occupancy sensor lag: May miss short occupancy (acceptable trade-off)
- Multiple people: 0.5°C threshold may be too low (configurable in future)

## Threshold Tuning Guidelines

### When to Adjust Thresholds

#### Solar Gain
- **Increase azimuth tolerance (45° → 60°):** Wide-angle windows, reflected light
- **Decrease azimuth tolerance (45° → 30°):** Narrow windows, obstructed views
- **Increase elevation threshold (10° → 20°):** High-altitude locations, strong sun
- **Decrease elevation threshold (10° → 5°):** Low winter sun, high latitudes

#### Wind Loss
- **Increase wind threshold (15 → 20 km/h):** Well-insulated building
- **Decrease wind threshold (15 → 10 km/h):** Poorly-insulated, drafty building
- **Increase rise time threshold (60 → 90 min):** Slow heating system (underfloor)
- **Decrease rise time threshold (60 → 45 min):** Fast heating system (forced air)

#### Outdoor Swing
- **Increase threshold (2 → 3°C):** Stable climate, avoid false positives
- **Decrease threshold (2 → 1.5°C):** Rapid weather changes, maritime climate

#### Occupancy Gain
- **Increase max threshold (0.5 → 0.8°C):** High occupancy (offices, large families)
- **Decrease max threshold (0.5 → 0.3°C):** Low occupancy (single person)

### Configuration Override Example

```yaml
# constants.py override (requires code change)
SOLAR_GAIN_OVERSHOOT_MIN = 0.7  # Increase from 0.5°C
SOLAR_AZIMUTH_TOLERANCE = 60     # Increase from 45°
DEFAULT_WIND_THRESHOLD = 20.0    # Increase from 15 km/h

# User configuration (YAML)
adaptive_thermostat:
  disturbance_rejection:
    wind_threshold: 20  # Override default
    outdoor_temp_threshold: 3.0  # Override default
```

## Threshold Validation Process

### Step 1: Collect Real Data
Run system with disturbance rejection enabled, log all detections:

```python
_LOGGER.info(
    "Disturbance detected: solar=%s (%s), wind=%s (%s), outdoor=%s (%s)",
    flags.solar_gain, flags.solar_evidence,
    flags.wind_loss, flags.wind_evidence,
    flags.outdoor_temp_swing, flags.outdoor_evidence,
)
```

### Step 2: Analyze False Positives
Review cycles incorrectly flagged as disturbed:

```yaml
# Check sensor attributes
sensor.adaptive_thermostat_living_room:
  disturbed_cycles: 10
  # Review last 10 cycles manually
```

### Step 3: Analyze False Negatives
Review cycles with poor metrics that were NOT flagged:

```python
# Look for: high overshoot + no disturbance flag
for cycle in learner.cycle_history:
    if cycle.overshoot > 1.0 and not cycle.disturbances.any_disturbance:
        _LOGGER.warning("Potential false negative: %s", cycle)
```

### Step 4: Adjust Thresholds
Based on false positive/negative rate, adjust thresholds:

- **>10% false positives:** Increase thresholds (more conservative)
- **>20% false negatives:** Decrease thresholds (more sensitive)

### Step 5: Re-validate
Repeat validation with new thresholds until acceptable accuracy.

## Threshold Interaction Matrix

How multiple disturbances interact:

| Disturbance Combo | Detection Logic | Example |
|-------------------|-----------------|---------|
| Solar + Wind | Both flagged | Sunny + windy day, oscillations |
| Solar + Outdoor | Solar takes priority | Outdoor swing from sun heating |
| Wind + Outdoor | Both flagged | Cold front with high winds |
| Occupancy + Solar | Both flagged | People + sunny window |
| All four | All flagged | Complex disturbance environment |

**Note:** Multiple disturbances are independently detected. Evidence strings show all contributors.

## Performance Considerations

### Detection Complexity

| Detection | Complexity | Notes |
|-----------|------------|-------|
| Solar gain | O(n) | Iterate temperature history |
| Wind loss | O(1) | Single sensor query |
| Outdoor swing | O(1) | Two sensor queries |
| Occupancy | O(m) | Query m occupancy sensors |

Where:
- n = number of temperature samples in cycle (~30-60 for 15-30 min cycle)
- m = number of occupancy sensors (typically 1-3)

**Total:** O(n) per cycle, runs once during cycle finalization (acceptable overhead)

### Sensor Query Optimization

```python
# GOOD: Single query per cycle
wind_speed = self._hass.states.get(self._wind_sensor_id).state

# BAD: Query per temperature sample
for timestamp, temp in temp_history:
    wind_speed = self._hass.states.get(self._wind_sensor_id).state  # Don't do this!
```

### Caching

```python
# Sun position already cached by SunPositionCalculator (daily)
sun_pos = self._sun_calculator.get_position_at_time(spike_time)  # Fast lookup
```

## Debugging Threshold Issues

### Enable Detection Logging

```yaml
# configuration.yaml
logger:
  logs:
    custom_components.adaptive_thermostat.adaptive.disturbance_detection: debug
```

### Log Output Examples

#### Solar Gain Detected
```
Solar gain detected: Sun azimuth 180° matched south windows (target 180°) at 09:15, elevation 35°
```

#### Wind Loss Detected
```
Wind loss detected: Wind speed 25.0 km/h during slow heating (rise time 75.0 min)
```

#### False Positive (Wrong Detection)
```
# Review: Overshoot was 2°C, but sun azimuth was 220° (southwest), window is south (180°)
# Diagnosis: Azimuth tolerance too wide (45° allows 180±45 = 135-225°)
# Fix: Reduce SOLAR_AZIMUTH_TOLERANCE to 30°
```

#### False Negative (Missed Detection)
```
# Review: Outdoor temp dropped 2.5°C, but not flagged (threshold is 2°C)
# Diagnosis: At boundary, sensor rounding
# Fix: Consider reducing threshold to 1.8°C or accept (borderline case)
```

## Quick Reference Table

| Disturbance | Default Threshold | Typical Range | Unit | Adjustable? |
|-------------|-------------------|---------------|------|-------------|
| Solar overshoot | 0.5 | 0.3-1.0 | °C | Code only |
| Solar azimuth | ±45 | ±30-60 | degrees | Code only |
| Solar elevation | 10 | 5-20 | degrees | Code only |
| Wind speed | 15 | 10-25 | km/h | Config YAML |
| Wind rise time | 60 | 45-120 | minutes | Code only |
| Outdoor swing | 2.0 | 1.5-3.0 | °C | Config YAML |
| Occupancy min | 0.2 | 0.1-0.3 | °C | Code only |
| Occupancy max | 0.5 | 0.3-0.8 | °C | Code only |

**Note:** "Code only" means requires constant change and component reload. Future enhancement: Make all thresholds configurable in YAML.

---

**Reference Version:** 1.0
**Last Updated:** 2026-01-15
