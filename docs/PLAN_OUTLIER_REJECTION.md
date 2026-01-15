# Implementation Plan: Robust Outlier Rejection in Adaptive Learning

**Status**: Draft
**Created**: 2026-01-15
**Author**: Architecture Review
**Priority**: High - Improves learning robustness and prevents bad tuning from anomalous cycles

---

## 1. Problem Statement

### Current Issue

The adaptive learning system currently requires only 3 cycles (`MIN_CYCLES_FOR_LEARNING = 3`) before making PID adjustment recommendations. It uses simple arithmetic mean to calculate average metrics across these cycles. This approach is vulnerable to outliers - a single anomalous cycle can represent 33% of the data and dramatically skew the averages.

**Example Outlier Scenarios:**

1. **Sunny Day Effect**: A cycle on an unusually sunny day where solar gain through windows significantly reduces heating time
   - Normal rise_time: 45 minutes
   - Sunny day rise_time: 15 minutes (outlier)
   - Average with 3 cycles: (45 + 45 + 15) / 3 = 35 minutes
   - **Result**: System incorrectly thinks it's more responsive, may reduce Kp too much

2. **Window Left Open**: A cycle where someone briefly opened a window during the settling phase
   - Normal overshoot: 0.3°C
   - Window open overshoot: 1.2°C (outlier due to rapid heat loss)
   - Average with 3 cycles: (0.3 + 0.3 + 1.2) / 3 = 0.6°C
   - **Result**: Triggers overshoot rule unnecessarily, reduces Kp by 15%

3. **Unusual Outdoor Temperature**: Extreme cold snap or warm spell
   - Normal settling_time: 50 minutes
   - Extreme cold settling_time: 95 minutes (outlier)
   - Average with 3 cycles: (50 + 50 + 95) / 3 = 65 minutes
   - **Result**: Triggers slow settling rule, increases Kd unnecessarily

### Why This Matters

Bad PID tuning from outliers causes:
- Comfort issues (oscillations, overshoots)
- Energy waste (inefficient cycling)
- User frustration (unexpected behavior changes)
- Slow convergence (multiple adjustment cycles needed to recover)

### Current Code Location

```
custom_components/adaptive_thermostat/
├── const.py                           # MIN_CYCLES_FOR_LEARNING = 3
├── adaptive/
│   ├── learning.py                    # AdaptiveLearner.calculate_pid_adjustment()
│   │                                  # Uses statistics.mean() for averages
│   └── cycle_analysis.py              # CycleMetrics container class
└── tests/
    └── test_learning.py               # Current tests use clean data
```

---

## 2. Proposed Solution: Robust Statistics with Outlier Detection

### Overview

Implement a three-part solution:

1. **Increase minimum sample size**: Raise `MIN_CYCLES_FOR_LEARNING` from 3 to 6
2. **Use robust statistics**: Replace arithmetic mean with median (50th percentile)
3. **Outlier detection and exclusion**: Use MAD (Median Absolute Deviation) to identify and exclude outliers before calculating statistics

### Why This Approach?

**Median vs Mean:**
- Median is robust to outliers (50% of data can be extreme without affecting result)
- Mean is sensitive to outliers (one extreme value shifts the entire average)
- Example: [45, 45, 15] → Mean: 35, Median: 45 ✓

**MAD (Median Absolute Deviation):**
- Robust measure of statistical dispersion
- Not affected by outliers (unlike standard deviation)
- Formula: `MAD = median(|x_i - median(x)|)`
- Modified Z-score: `M_i = 0.6745 * (x_i - median(x)) / MAD`
- Common threshold: |M_i| > 3.5 indicates outlier

**Why 6 Cycles Minimum?**
- With MAD outlier detection, need 5-7 cycles for robust statistics
- 6 cycles gives good balance: enough data for outlier detection, not too slow to learn
- After removing 1-2 outliers, still have 4-5 valid cycles for median calculation
- Statistical rule of thumb: need at least 5 samples for reliable median

---

## 3. Detailed Implementation Plan

### 3.1 Phase 1: Add Robust Statistics Module

**File**: `custom_components/adaptive_thermostat/adaptive/robust_stats.py` (NEW)

**Functions to Implement:**

```python
def calculate_median(values: List[float]) -> float:
    """Calculate median of a list of values."""

def calculate_mad(values: List[float]) -> float:
    """Calculate Median Absolute Deviation (MAD)."""

def calculate_modified_z_scores(values: List[float]) -> List[float]:
    """Calculate modified Z-scores using MAD."""

def detect_outliers(
    values: List[float],
    threshold: float = 3.5
) -> List[int]:
    """
    Detect outliers using modified Z-score method.

    Returns:
        List of indices of outlier values
    """

def filter_outliers(
    values: List[float],
    threshold: float = 3.5
) -> Tuple[List[float], List[int]]:
    """
    Filter out outliers from a list of values.

    Returns:
        Tuple of (filtered_values, outlier_indices)
    """

def robust_average(
    values: List[float],
    threshold: float = 3.5
) -> Tuple[float, int]:
    """
    Calculate robust average (median) with outlier detection.

    Returns:
        Tuple of (median_value, num_outliers_removed)
    """
```

**Key Design Decisions:**

1. **Use modified Z-score instead of standard Z-score**
   - More robust to outliers in the calculation itself
   - Constant 0.6745 is conversion factor for normal distribution

2. **Threshold of 3.5 for outlier detection**
   - Conservative threshold (stricter than typical 2-3)
   - Reduces false positives (marking normal variance as outliers)
   - Based on Iglewicz and Hoaglin (1993) recommendation

3. **Return outlier indices for logging/debugging**
   - Allow system to log which cycles were excluded
   - Help diagnose patterns (e.g., all outliers on sunny days)

**Dependencies:**
- `statistics` module (stdlib) - for median calculation
- No external dependencies required

### 3.2 Phase 2: Update Constants

**File**: `custom_components/adaptive_thermostat/const.py`

**Changes:**

```python
# OLD:
MIN_CYCLES_FOR_LEARNING = 3

# NEW:
MIN_CYCLES_FOR_LEARNING = 6

# NEW: Outlier detection configuration
# Minimum cycles needed after outlier removal for reliable statistics
MIN_CYCLES_AFTER_OUTLIER_REMOVAL = 4

# Modified Z-score threshold for outlier detection
# Values with |modified_z_score| > threshold are considered outliers
# 3.5 is conservative (Iglewicz and Hoaglin 1993)
OUTLIER_DETECTION_THRESHOLD = 3.5

# Maximum percentage of cycles that can be marked as outliers
# Safety check to prevent removing too much data
MAX_OUTLIER_PERCENTAGE = 30  # 30% = 2 out of 6 cycles
```

**Rationale:**

- `MIN_CYCLES_AFTER_OUTLIER_REMOVAL = 4`: Ensures we still have enough valid data after filtering
- `OUTLIER_DETECTION_THRESHOLD = 3.5`: Conservative threshold prevents over-filtering
- `MAX_OUTLIER_PERCENTAGE = 30`: Safety valve if something goes wrong with detection

### 3.3 Phase 3: Refactor AdaptiveLearner

**File**: `custom_components/adaptive_thermostat/adaptive/learning.py`

**Method to Refactor**: `AdaptiveLearner.calculate_pid_adjustment()`

**Current Code (lines 219-238):**

```python
# Calculate average metrics from recent cycles
recent_cycles = self._cycle_history[-min_cycles:]

avg_overshoot = statistics.mean(
    [c.overshoot for c in recent_cycles if c.overshoot is not None]
) if any(c.overshoot is not None for c in recent_cycles) else 0.0

avg_undershoot = statistics.mean(
    [c.undershoot for c in recent_cycles if c.undershoot is not None]
) if any(c.undershoot is not None for c in recent_cycles) else 0.0

# ... similar for other metrics
```

**New Implementation:**

```python
from .robust_stats import robust_average

# Calculate robust average (median) metrics with outlier removal
recent_cycles = self._cycle_history[-min_cycles:]

# Extract metric values for outlier detection
overshoot_values = [c.overshoot for c in recent_cycles if c.overshoot is not None]
undershoot_values = [c.undershoot for c in recent_cycles if c.undershoot is not None]
settling_time_values = [c.settling_time for c in recent_cycles if c.settling_time is not None]
oscillation_values = [c.oscillations for c in recent_cycles]
rise_time_values = [c.rise_time for c in recent_cycles if c.rise_time is not None]

# Calculate robust averages with outlier detection
if overshoot_values:
    avg_overshoot, overshoot_outliers = robust_average(overshoot_values)
    if overshoot_outliers > 0:
        _LOGGER.info(f"Removed {overshoot_outliers} outlier(s) from overshoot data")
else:
    avg_overshoot = 0.0

# ... similar for other metrics

# Safety check: ensure we have enough valid cycles after outlier removal
valid_cycles_count = min_cycles - max(
    len([1 for v in overshoot_values if v != avg_overshoot]),
    # ... check for each metric
)

if valid_cycles_count < MIN_CYCLES_AFTER_OUTLIER_REMOVAL:
    _LOGGER.warning(
        f"Too many outliers detected ({min_cycles - valid_cycles_count}), "
        f"skipping PID adjustment until more cycles available"
    )
    return None
```

**Additional Logging:**

Add detailed logging to track outlier detection:

```python
# After calculating all robust averages
_LOGGER.info(
    f"Cycle metrics summary (from {min_cycles} cycles): "
    f"overshoot={avg_overshoot:.2f}°C ({overshoot_outliers} outliers), "
    f"undershoot={avg_undershoot:.2f}°C ({undershoot_outliers} outliers), "
    f"settling_time={avg_settling_time:.1f}min ({settling_outliers} outliers), "
    f"oscillations={avg_oscillations:.1f} ({oscillation_outliers} outliers), "
    f"rise_time={avg_rise_time:.1f}min ({rise_outliers} outliers)"
)
```

### 3.4 Phase 4: Update Tests

**File**: `tests/test_learning.py`

**New Test Class:**

```python
class TestOutlierDetection:
    """Tests for robust statistics and outlier detection in adaptive learning."""

    def test_robust_average_with_sunny_day_outlier(self):
        """Test that sunny day outlier doesn't skew rise time average."""
        learner = AdaptiveLearner()

        # 5 normal cycles + 1 sunny day outlier
        for _ in range(5):
            learner.add_cycle_metrics(CycleMetrics(
                rise_time=45.0,
                overshoot=0.3,
                settling_time=50.0,
                oscillations=1
            ))

        # Sunny day outlier - much faster rise
        learner.add_cycle_metrics(CycleMetrics(
            rise_time=15.0,  # Outlier
            overshoot=0.3,
            settling_time=50.0,
            oscillations=1
        ))

        # Should use median (45) not mean (40)
        adjustment = learner.calculate_pid_adjustment(100, 10, 20, min_cycles=6)
        # Verify that adjustment is based on 45 min rise time
        # (no slow response rule should trigger)
        assert adjustment is None  # Within acceptable range

    def test_robust_average_with_window_open_outlier(self):
        """Test that window open outlier doesn't trigger overshoot rule."""
        learner = AdaptiveLearner()

        # 5 normal cycles + 1 window open outlier
        for _ in range(5):
            learner.add_cycle_metrics(CycleMetrics(
                rise_time=45.0,
                overshoot=0.3,
                settling_time=50.0,
                oscillations=1
            ))

        # Window open outlier - excessive overshoot
        learner.add_cycle_metrics(CycleMetrics(
            rise_time=45.0,
            overshoot=1.2,  # Outlier
            settling_time=50.0,
            oscillations=1
        ))

        # Should use median overshoot (0.3°C) not mean (0.45°C)
        adjustment = learner.calculate_pid_adjustment(100, 10, 20, min_cycles=6)
        # Verify overshoot rule doesn't trigger
        assert adjustment is None or adjustment['kp'] == 100

    def test_too_many_outliers_safety_check(self):
        """Test that adjustment is skipped if too many outliers detected."""
        learner = AdaptiveLearner()

        # 3 outliers out of 6 cycles (50% - exceeds MAX_OUTLIER_PERCENTAGE)
        # This should never happen in practice but test safety valve
        learner.add_cycle_metrics(CycleMetrics(rise_time=15.0, overshoot=0.3,
                                              settling_time=50.0, oscillations=1))
        learner.add_cycle_metrics(CycleMetrics(rise_time=90.0, overshoot=0.3,
                                              settling_time=50.0, oscillations=1))
        learner.add_cycle_metrics(CycleMetrics(rise_time=20.0, overshoot=0.3,
                                              settling_time=50.0, oscillations=1))
        learner.add_cycle_metrics(CycleMetrics(rise_time=45.0, overshoot=0.3,
                                              settling_time=50.0, oscillations=1))
        learner.add_cycle_metrics(CycleMetrics(rise_time=45.0, overshoot=0.3,
                                              settling_time=50.0, oscillations=1))
        learner.add_cycle_metrics(CycleMetrics(rise_time=45.0, overshoot=0.3,
                                              settling_time=50.0, oscillations=1))

        adjustment = learner.calculate_pid_adjustment(100, 10, 20, min_cycles=6)
        # Should return None due to too many outliers
        assert adjustment is None

    def test_insufficient_cycles_after_outlier_removal(self):
        """Test that adjustment is skipped if outlier removal leaves too few cycles."""
        learner = AdaptiveLearner()

        # 6 cycles but 3 are outliers - leaves only 3 valid (< MIN_CYCLES_AFTER_OUTLIER_REMOVAL)
        learner.add_cycle_metrics(CycleMetrics(rise_time=45.0, overshoot=0.3,
                                              settling_time=50.0, oscillations=1))
        learner.add_cycle_metrics(CycleMetrics(rise_time=45.0, overshoot=0.3,
                                              settling_time=50.0, oscillations=1))
        learner.add_cycle_metrics(CycleMetrics(rise_time=45.0, overshoot=0.3,
                                              settling_time=50.0, oscillations=1))
        # 3 outliers
        learner.add_cycle_metrics(CycleMetrics(rise_time=10.0, overshoot=0.3,
                                              settling_time=50.0, oscillations=1))
        learner.add_cycle_metrics(CycleMetrics(rise_time=12.0, overshoot=0.3,
                                              settling_time=50.0, oscillations=1))
        learner.add_cycle_metrics(CycleMetrics(rise_time=90.0, overshoot=0.3,
                                              settling_time=50.0, oscillations=1))

        adjustment = learner.calculate_pid_adjustment(100, 10, 20, min_cycles=6)
        assert adjustment is None

    def test_median_vs_mean_comparison(self):
        """Test that median is used instead of mean for robustness."""
        learner = AdaptiveLearner()

        # Create dataset where mean != median
        rise_times = [40.0, 42.0, 45.0, 47.0, 48.0, 90.0]  # Last is outlier
        # Mean: 52.0, Median: 46.0

        for rise_time in rise_times:
            learner.add_cycle_metrics(CycleMetrics(
                rise_time=rise_time,
                overshoot=0.3,
                settling_time=50.0,
                oscillations=1
            ))

        # With robust statistics, should use median (46.0)
        # This should not trigger slow response rule (threshold > 60 min)
        adjustment = learner.calculate_pid_adjustment(100, 10, 20, min_cycles=6)
        assert adjustment is None  # No rule triggered
```

**File**: `tests/test_robust_stats.py` (NEW)

Full unit tests for the new robust statistics module:

```python
"""Tests for robust statistics and outlier detection."""

import pytest
from custom_components.adaptive_thermostat.adaptive.robust_stats import (
    calculate_median,
    calculate_mad,
    calculate_modified_z_scores,
    detect_outliers,
    filter_outliers,
    robust_average,
)


class TestMedianCalculation:
    """Tests for median calculation."""

    def test_median_odd_count(self):
        """Test median with odd number of values."""
        values = [1, 3, 5, 7, 9]
        assert calculate_median(values) == 5

    def test_median_even_count(self):
        """Test median with even number of values."""
        values = [1, 2, 3, 4]
        assert calculate_median(values) == 2.5

    def test_median_single_value(self):
        """Test median with single value."""
        assert calculate_median([42]) == 42

    def test_median_with_outliers(self):
        """Test that median is robust to outliers."""
        # Mean would be 31.4, median stays at 5
        values = [1, 3, 5, 7, 141]
        assert calculate_median(values) == 5


class TestMADCalculation:
    """Tests for Median Absolute Deviation calculation."""

    def test_mad_basic(self):
        """Test MAD calculation with known values."""
        values = [1, 2, 3, 4, 5]
        # Median = 3
        # Deviations = [2, 1, 0, 1, 2]
        # MAD = median([2, 1, 0, 1, 2]) = 1
        assert calculate_mad(values) == 1.0

    def test_mad_with_outlier(self):
        """Test that MAD is robust to outliers."""
        values = [1, 2, 3, 4, 100]
        # Median = 3
        # Deviations = [2, 1, 0, 1, 97]
        # MAD = median([2, 1, 0, 1, 97]) = 1
        assert calculate_mad(values) == 1.0

    def test_mad_zero(self):
        """Test MAD when all values are identical."""
        values = [5, 5, 5, 5]
        assert calculate_mad(values) == 0.0


class TestModifiedZScores:
    """Tests for modified Z-score calculation."""

    def test_modified_z_scores_basic(self):
        """Test modified Z-score calculation."""
        values = [1, 2, 3, 4, 5]
        z_scores = calculate_modified_z_scores(values)

        # Middle value should have Z-score of 0
        assert z_scores[2] == pytest.approx(0.0)

        # Symmetric around median
        assert abs(z_scores[0]) == pytest.approx(abs(z_scores[4]))

    def test_modified_z_scores_outlier(self):
        """Test that outliers have high absolute Z-scores."""
        values = [1, 2, 3, 4, 100]
        z_scores = calculate_modified_z_scores(values)

        # Outlier should have much higher absolute Z-score
        assert abs(z_scores[4]) > abs(z_scores[0])
        assert abs(z_scores[4]) > abs(z_scores[1])


class TestOutlierDetection:
    """Tests for outlier detection."""

    def test_no_outliers(self):
        """Test that normal data has no outliers."""
        values = [1, 2, 3, 4, 5]
        outliers = detect_outliers(values, threshold=3.5)
        assert len(outliers) == 0

    def test_single_outlier_high(self):
        """Test detection of single high outlier."""
        values = [1, 2, 3, 4, 100]
        outliers = detect_outliers(values, threshold=3.5)
        assert 4 in outliers  # Index of outlier
        assert len(outliers) == 1

    def test_single_outlier_low(self):
        """Test detection of single low outlier."""
        values = [50, 51, 52, 53, 1]
        outliers = detect_outliers(values, threshold=3.5)
        assert 4 in outliers
        assert len(outliers) == 1

    def test_multiple_outliers(self):
        """Test detection of multiple outliers."""
        values = [1, 2, 3, 100, 101]
        outliers = detect_outliers(values, threshold=3.5)
        assert len(outliers) == 2
        assert 3 in outliers
        assert 4 in outliers


class TestFilterOutliers:
    """Tests for outlier filtering."""

    def test_filter_removes_outliers(self):
        """Test that filter removes outliers."""
        values = [1, 2, 3, 4, 100]
        filtered, outlier_indices = filter_outliers(values, threshold=3.5)

        assert len(filtered) == 4
        assert 100 not in filtered
        assert outlier_indices == [4]

    def test_filter_preserves_order(self):
        """Test that filter preserves order of remaining values."""
        values = [5, 10, 15, 100, 20]
        filtered, _ = filter_outliers(values, threshold=3.5)

        assert filtered == [5, 10, 15, 20]


class TestRobustAverage:
    """Tests for robust average calculation."""

    def test_robust_average_no_outliers(self):
        """Test robust average with clean data."""
        values = [40, 42, 45, 47, 48, 50]
        avg, num_outliers = robust_average(values)

        assert avg == pytest.approx(46.0)  # Median
        assert num_outliers == 0

    def test_robust_average_with_outlier(self):
        """Test robust average filters outlier."""
        values = [40, 42, 45, 47, 48, 200]
        avg, num_outliers = robust_average(values)

        # Should exclude 200, median of [40, 42, 45, 47, 48] = 45
        assert avg == pytest.approx(45.0)
        assert num_outliers == 1

    def test_robust_average_rise_time_scenario(self):
        """Test robust average with rise time outlier (sunny day)."""
        # 5 normal cycles: 45 min, 1 sunny day: 15 min
        values = [45.0, 45.0, 45.0, 45.0, 45.0, 15.0]
        avg, num_outliers = robust_average(values)

        # Mean would be 40, median is 45 (correct)
        assert avg == pytest.approx(45.0)
        assert num_outliers == 1
```

### 3.5 Phase 5: Update Documentation

**Files to Update:**

1. **CLAUDE.md** - Architecture documentation

Add section:

```markdown
## Outlier Rejection in Adaptive Learning

The adaptive learning system uses robust statistics to handle anomalous cycles:

- **Minimum cycles**: 6 cycles required before PID adjustments
- **Robust statistics**: Uses median instead of mean (resistant to outliers)
- **Outlier detection**: Modified Z-score method with MAD (Median Absolute Deviation)
- **Threshold**: |Modified Z-score| > 3.5 indicates outlier (conservative)
- **Safety checks**:
  - Maximum 30% of cycles can be marked as outliers
  - Minimum 4 valid cycles required after outlier removal

**Common Outlier Scenarios:**
- Sunny days (faster heating due to solar gain)
- Windows/doors left open (unusual heat loss)
- Extreme weather (very cold or warm outdoor temperatures)
- Temporary obstructions (furniture moved near sensor)

**Modified Z-Score Formula:**
```
M_i = 0.6745 * (x_i - median(x)) / MAD
where MAD = median(|x_i - median(x)|)
```

This approach ensures that 1-2 anomalous cycles cannot corrupt the PID tuning process.
```

2. **README.md** - User documentation

Update "How It Works" section:

```markdown
### Robust Adaptive Learning

The thermostat collects performance metrics from each heating cycle and uses these to automatically tune the PID controller. To ensure reliability:

- **Requires 6 cycles** before making adjustments (was 3 in older versions)
- **Outlier detection** automatically excludes anomalous cycles (e.g., sunny days, windows left open)
- **Robust statistics** use median instead of average to resist outliers
- **Detailed logging** shows when outliers are detected and excluded

This means temporary unusual conditions won't corrupt your thermostat's tuning.
```

---

## 4. Implementation Sequence

**Phase 1: Foundation (Week 1)**
1. Create `robust_stats.py` module with full unit tests
2. Add new constants to `const.py`
3. Run tests to validate robust statistics implementation

**Phase 2: Integration (Week 1)**
4. Update `learning.py` to use robust statistics
5. Add detailed logging for outlier detection
6. Update existing tests in `test_learning.py`

**Phase 3: Validation (Week 2)**
7. Create comprehensive test suite for outlier scenarios
8. Test with synthetic data (inject outliers)
9. Code review and adjustments

**Phase 4: Documentation (Week 2)**
10. Update CLAUDE.md with architecture details
11. Update README.md with user-facing explanation
12. Add inline code comments

**Phase 5: Field Testing (Week 3-4)**
13. Deploy to test environments
14. Monitor logs for outlier detection patterns
15. Validate that outliers are correctly identified
16. Collect user feedback

---

## 5. Testing Strategy

### 5.1 Unit Tests

**File**: `tests/test_robust_stats.py`

- Test median calculation (odd/even counts, edge cases)
- Test MAD calculation (normal, all identical, with outliers)
- Test modified Z-score calculation
- Test outlier detection (no outliers, single, multiple)
- Test filter_outliers (removal, order preservation)
- Test robust_average (clean data, with outliers)

**Coverage Target**: 100% line coverage for `robust_stats.py`

### 5.2 Integration Tests

**File**: `tests/test_learning.py`

- Test `AdaptiveLearner` with outlier scenarios:
  - Sunny day outlier (fast rise time)
  - Window open outlier (high overshoot)
  - Extreme cold outlier (slow settling)
  - Multiple outliers in same dataset
- Test safety checks:
  - Too many outliers (>30%)
  - Insufficient valid cycles after removal (<4)
- Test logging output (verify outliers are reported)

### 5.3 Synthetic Data Testing

Create test scripts that inject realistic outliers:

```python
# tests/synthetic/test_outlier_scenarios.py

def test_sunny_day_sequence():
    """Simulate 10 cycles with 2 sunny days."""
    learner = AdaptiveLearner()

    # 8 normal cycles
    for i in range(8):
        learner.add_cycle_metrics(normal_cycle())

    # 2 sunny day outliers
    for i in range(2):
        learner.add_cycle_metrics(sunny_day_cycle())

    # Verify adjustments are based on normal cycles
    adjustment = learner.calculate_pid_adjustment(100, 10, 20)
    # ... assertions

def test_gradual_weather_change():
    """Simulate gradual temperature shift (not an outlier)."""
    # Should NOT detect as outliers

def test_mixed_outliers():
    """Test multiple different types of outliers."""
    # Sunny day + window open + extreme cold
```

### 5.4 Manual Testing Checklist

Before release, manually verify:

- [ ] Create 6 normal cycles, verify adjustment uses median
- [ ] Add 1 sunny day cycle, verify it's detected as outlier
- [ ] Add 2 outliers, verify they're both removed
- [ ] Add 3 outliers, verify safety check triggers (too many)
- [ ] Check logs show outlier detection messages
- [ ] Verify metrics displayed in HA UI are correct
- [ ] Test with real thermostat data (if available)

---

## 6. Rollback Plan

### If Issues Discovered

**Symptoms that might require rollback:**
- Learning stops working (no adjustments made)
- Too many false positives (normal cycles marked as outliers)
- Performance degradation (too slow)
- Unexpected crashes or errors

### Rollback Procedure

**Quick Rollback (revert constants):**

```python
# In const.py, temporarily revert:
MIN_CYCLES_FOR_LEARNING = 3  # Revert to old value
# Comment out outlier detection
```

**Full Rollback:**

```python
# In learning.py, revert calculate_pid_adjustment():
# Replace robust_average() calls with statistics.mean()

# OLD CODE (safe fallback):
avg_overshoot = statistics.mean(
    [c.overshoot for c in recent_cycles if c.overshoot is not None]
) if any(c.overshoot is not None for c in recent_cycles) else 0.0
```

**Git Revert:**

```bash
# If multiple commits involved, revert the entire feature branch
git revert <outlier-rejection-feature-branch>
git push origin main
```

### Feature Flag Option

**Add feature flag for gradual rollout:**

```python
# In const.py
CONF_ENABLE_OUTLIER_REJECTION = "enable_outlier_rejection"
DEFAULT_ENABLE_OUTLIER_REJECTION = True

# In learning.py
def calculate_pid_adjustment(self, ...):
    if self._enable_outlier_rejection:
        # Use robust statistics
        avg_overshoot, _ = robust_average(overshoot_values)
    else:
        # Use old method
        avg_overshoot = statistics.mean(overshoot_values)
```

This allows users to disable the feature if issues arise without code changes.

---

## 7. Success Criteria

### Metrics to Track

1. **Outlier Detection Rate**
   - Target: 5-15% of cycles flagged as outliers
   - Too low (<2%): May need lower threshold
   - Too high (>25%): May need higher threshold or data quality issues

2. **False Positive Rate**
   - Target: <5% of normal cycles incorrectly flagged
   - Monitor user reports of "good" cycles being excluded

3. **Learning Convergence Time**
   - Target: Similar or better than current (within 10%)
   - 6 cycles vs 3 cycles means 2x longer to first adjustment
   - But should result in better adjustments (fewer iterations needed)

4. **PID Stability**
   - Target: Fewer adjustment reversals (e.g., Kp up then down)
   - Track adjustment history for oscillating patterns

5. **User Satisfaction**
   - Target: No increase in reported issues
   - Monitor forum/issue tracker for complaints about learning

### Definition of Done

- [ ] All unit tests passing (100% coverage for robust_stats.py)
- [ ] All integration tests passing
- [ ] Synthetic outlier tests demonstrate correct filtering
- [ ] Documentation updated (CLAUDE.md, README.md, inline comments)
- [ ] Code reviewed by at least one other developer
- [ ] Deployed to test environment for 2 weeks
- [ ] No critical issues discovered in field testing
- [ ] Outlier detection logs show reasonable patterns (5-15% rate)
- [ ] No regressions in existing functionality

---

## 8. Future Enhancements

### Potential Improvements (Post-Launch)

1. **Adaptive Thresholds**
   - Adjust outlier threshold based on data quality
   - Lower threshold (more sensitive) when data is stable
   - Higher threshold (less sensitive) when data is noisy

2. **Per-Metric Thresholds**
   - Different thresholds for different metrics
   - Example: Rise time might have more outliers than overshoot
   - Could be: `OUTLIER_THRESHOLD_RISE_TIME = 4.0`, `OUTLIER_THRESHOLD_OVERSHOOT = 3.0`

3. **Outlier Pattern Analysis**
   - Track when outliers occur (time of day, day of week, weather)
   - Could detect systematic issues (e.g., all outliers on Sundays = someone opens windows)
   - Provide insights to user via sensor or notification

4. **Robust Variance Metrics**
   - Add IQR (Interquartile Range) alongside MAD
   - Provide confidence intervals for PID recommendations
   - Display in HA UI: "Confidence: High" vs "Confidence: Low (noisy data)"

5. **Ensemble Methods**
   - Combine multiple outlier detection methods
   - Example: MAD + IQR + Grubbs' test
   - Vote: Only mark as outlier if 2/3 methods agree

6. **Seasonal Adjustment**
   - Learn seasonal patterns (winter cycles different from summer)
   - Separate cycle history by season
   - Don't mark as outlier if consistent with season

---

## 9. References

### Statistical Methods

1. **Iglewicz, B. and Hoaglin, D. (1993)** - "How to Detect and Handle Outliers"
   - Source of modified Z-score method and 3.5 threshold

2. **Rousseeuw, P.J. and Croux, C. (1993)** - "Alternatives to the Median Absolute Deviation"
   - Theoretical foundation for MAD as robust scale estimator

### Similar Implementations

1. **scikit-learn RobustScaler** - Uses median and IQR for outlier-resistant scaling
2. **pandas.DataFrame.quantile()** - Robust percentile-based statistics
3. **scipy.stats.mstats.zscore(ddof=0)** - Modified Z-score implementation

### Home Assistant Community

- Forum discussions on thermostat learning issues
- User reports of "bad tuning after sunny day"
- Similar issues in other PID-based thermostats

---

## 10. Appendix: Example Scenarios

### Scenario A: Sunny Day Outlier

**Background**: User has large south-facing windows. On sunny days, solar gain significantly speeds up heating.

**Data**:
```python
# 5 normal days (cloudy)
rise_times = [45, 43, 47, 46, 44]  # Mean: 45, Median: 45

# 1 sunny day
rise_times.append(15)  # Outlier

# Without outlier rejection:
mean = 40.0  # 33% faster than reality
# System thinks: "Wow, I'm very responsive!"
# Action: Reduces Kp, making system sluggish on normal days

# With outlier rejection:
median = 45.0  # Correct
# System thinks: "My rise time is consistent"
# Action: No change needed
```

### Scenario B: Window Left Open

**Background**: User opens window for 10 minutes during settling phase.

**Data**:
```python
# 5 normal cycles
overshoot_values = [0.3, 0.2, 0.3, 0.3, 0.2]  # Mean: 0.26, Median: 0.3

# 1 window open cycle
overshoot_values.append(1.2)  # Outlier

# Without outlier rejection:
mean = 0.42  # 62% higher than reality
# System thinks: "Excessive overshoot!"
# Action: Reduces Kp by 15%, making system too sluggish

# With outlier rejection:
median = 0.3  # Correct
# System thinks: "Overshoot is acceptable"
# Action: No change needed
```

### Scenario C: Extreme Cold Snap

**Background**: Outdoor temperature drops to -20°C for one day.

**Data**:
```python
# 5 normal days (-5°C outdoor)
settling_times = [50, 52, 48, 51, 49]  # Mean: 50, Median: 50

# 1 extreme cold day (-20°C outdoor)
settling_times.append(95)  # Outlier

# Without outlier rejection:
mean = 57.5  # 15% slower than reality
# System thinks: "Settling is too slow"
# Action: Increases Kd by 15%, might cause oscillations

# With outlier rejection:
median = 50.0  # Correct
# System thinks: "Settling time is acceptable"
# Action: No change needed (or waits for Ke learning if outdoor temp matters)
```

---

## Summary

This implementation plan provides a comprehensive approach to adding robust outlier rejection to the adaptive learning system. The key changes are:

1. Increase minimum cycles from 3 to 6
2. Add robust statistics module with MAD-based outlier detection
3. Replace mean with median in learning calculations
4. Add comprehensive testing with realistic outlier scenarios
5. Implement safety checks and detailed logging
6. Provide rollback plan and feature flag option

**Expected Benefits:**
- More reliable PID tuning
- Better handling of anomalous conditions
- Reduced user complaints about bad tuning
- More stable long-term performance

**Risks:**
- Longer time to first adjustment (6 cycles vs 3)
- Potential for false positives (normal cycles marked as outliers)
- Complexity increase (more code to maintain)

**Mitigation:**
- Comprehensive testing with synthetic outliers
- Conservative threshold (3.5) to minimize false positives
- Feature flag for easy rollback
- Detailed logging for debugging

The plan is designed to be implemented incrementally with clear rollback options at each phase.
