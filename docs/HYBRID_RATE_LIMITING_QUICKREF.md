# Hybrid Rate Limiting Quick Reference

**For developers implementing Story 8: Fix Aggressive Rate Limiting**

---

## Key Files to Modify

| File | Changes | Lines Affected |
|------|---------|----------------|
| `const.py` | Update constant, add new config keys | ~139, +4 new |
| `adaptive/learning.py` | Add cycle counter, update rate limiting | ~50-100 lines |
| `adaptive/persistence.py` | Save/restore cycle counter | ~20 lines |
| `climate.py` | Add config schema | ~10 lines |

---

## Code Changes Checklist

### 1. Constants (`const.py`)

```python
# Line 139: UPDATE
MIN_ADJUSTMENT_INTERVAL = 8  # Changed from 24

# NEW CONSTANTS (add after line 139)
MIN_CYCLES_BETWEEN_ADJUSTMENTS = 3

# NEW CONFIG KEYS (add to config section)
CONF_MIN_ADJUSTMENT_INTERVAL = "min_adjustment_interval"
CONF_MIN_CYCLES_BETWEEN_ADJUSTMENTS = "min_cycles_between_adjustments"
```

### 2. AdaptiveLearner (`adaptive/learning.py`)

**Add to `__init__`**:
```python
def __init__(self, max_history: int = MAX_CYCLE_HISTORY):
    # ... existing code ...
    self._last_adjustment_time: Optional[datetime] = None
    self._cycles_since_last_adjustment: int = 0  # ADD THIS
```

**Update `add_cycle_metrics`**:
```python
def add_cycle_metrics(self, metrics: CycleMetrics) -> None:
    self._cycle_history.append(metrics)
    self._cycles_since_last_adjustment += 1  # ADD THIS

    # FIFO eviction...
```

**Replace `_check_rate_limit`** (line 145-174):
```python
def _check_rate_limit(
    self,
    min_interval_hours: int = MIN_ADJUSTMENT_INTERVAL,
    min_cycles_since_adjustment: int = MIN_CYCLES_BETWEEN_ADJUSTMENTS,  # NEW
) -> bool:
    """
    Check if enough cycles AND time have passed since last adjustment.

    Args:
        min_interval_hours: Minimum hours between adjustments
        min_cycles_since_adjustment: Minimum cycles required (NEW)

    Returns:
        True if rate limited, False if OK to adjust
    """
    # Time gate
    time_ok = False
    hours_remaining = 0.0

    if self._last_adjustment_time is None:
        time_ok = True
    else:
        time_since_last = datetime.now() - self._last_adjustment_time
        min_interval = timedelta(hours=min_interval_hours)

        if time_since_last >= min_interval:
            time_ok = True
        else:
            hours_remaining = (min_interval - time_since_last).total_seconds() / 3600

    # Cycle gate (NEW)
    cycles_ok = self._cycles_since_last_adjustment >= min_cycles_since_adjustment
    cycles_needed = max(0, min_cycles_since_adjustment - self._cycles_since_last_adjustment)

    # Enhanced logging (NEW)
    if not time_ok and not cycles_ok:
        _LOGGER.info(
            f"PID adjustment rate limited: need {cycles_needed} more cycles "
            f"AND {hours_remaining:.1f}h more time"
        )
    elif not time_ok:
        _LOGGER.info(
            f"PID adjustment rate limited by time: {hours_remaining:.1f}h remaining "
            f"({self._cycles_since_last_adjustment} cycles ready)"
        )
    elif not cycles_ok:
        _LOGGER.info(
            f"PID adjustment rate limited by cycles: need {cycles_needed} more cycles "
            f"(time gate passed)"
        )

    # Return True if EITHER gate fails (AND logic)
    return not (time_ok and cycles_ok)
```

**Update `calculate_pid_adjustment`** (line 286):
```python
def calculate_pid_adjustment(
    self,
    current_kp: float,
    current_ki: float,
    current_kd: float,
    min_cycles: int = MIN_CYCLES_FOR_LEARNING,
    min_interval_hours: int = MIN_ADJUSTMENT_INTERVAL,
    min_cycles_since_adjustment: int = MIN_CYCLES_BETWEEN_ADJUSTMENTS,  # NEW
) -> Optional[Dict[str, float]]:
    # Check rate limiting first
    if self._check_rate_limit(min_interval_hours, min_cycles_since_adjustment):  # UPDATED
        return None

    # ... existing logic ...

    # Record adjustment time for rate limiting
    self._last_adjustment_time = datetime.now()
    self._cycles_since_last_adjustment = 0  # ADD THIS (reset counter)

    return {
        "kp": new_kp,
        "ki": new_ki,
        "kd": new_kd,
    }
```

**Add helper method** (optional, for testing):
```python
def get_cycles_since_adjustment(self) -> int:
    """Get number of cycles since last adjustment."""
    return self._cycles_since_last_adjustment
```

### 3. Persistence (`adaptive/persistence.py`)

**Update `save()` method** (~line 79):
```python
# Save AdaptiveLearner data
if adaptive_learner is not None:
    cycle_history = []
    for cycle in adaptive_learner._cycle_history:
        # ... existing cycle serialization ...

    data["adaptive_learner"] = {
        "cycle_history": cycle_history,
        "last_adjustment_time": (
            adaptive_learner._last_adjustment_time.isoformat()
            if adaptive_learner._last_adjustment_time is not None
            else None
        ),
        "max_history": adaptive_learner._max_history,
        "consecutive_converged_cycles": adaptive_learner._consecutive_converged_cycles,
        "pid_converged_for_ke": adaptive_learner._pid_converged_for_ke,
        "cycles_since_last_adjustment": adaptive_learner._cycles_since_last_adjustment,  # ADD
    }
```

**Update `restore()` method** (find adaptive_learner restore section):
```python
def restore(self, adaptive_learner=None, thermal_learner=None, ...):
    # ... load data ...

    if adaptive_learner is not None and "adaptive_learner" in data:
        learner_data = data["adaptive_learner"]

        # ... existing restoration ...

        # Restore cycles_since_last_adjustment (NEW)
        adaptive_learner._cycles_since_last_adjustment = learner_data.get(
            "cycles_since_last_adjustment", 0
        )

        # Migration: if missing and time passed, assume 3 cycles (NEW)
        if (adaptive_learner._cycles_since_last_adjustment == 0 and
                adaptive_learner._last_adjustment_time is not None):
            time_since = datetime.now() - adaptive_learner._last_adjustment_time
            if time_since.total_seconds() / 3600 >= 8:
                adaptive_learner._cycles_since_last_adjustment = 3
                _LOGGER.info("Migrated to hybrid rate limiting: assumed 3 cycles ready")
```

### 4. Configuration Schema (`climate.py`)

**Add to platform schema** (find PLATFORM_SCHEMA.extend):
```python
# Domain-level configuration
DOMAIN_PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    # ... existing config ...

    # Adaptive learning rate limiting (NEW)
    vol.Optional(
        const.CONF_MIN_ADJUSTMENT_INTERVAL,
        default=const.MIN_ADJUSTMENT_INTERVAL
    ): vol.All(int, vol.Range(min=1, max=168)),

    vol.Optional(
        const.CONF_MIN_CYCLES_BETWEEN_ADJUSTMENTS,
        default=const.MIN_CYCLES_BETWEEN_ADJUSTMENTS
    ): vol.All(int, vol.Range(min=1, max=20)),
})
```

**Pass to AdaptiveLearner** (in thermostat initialization):
```python
# When calling calculate_pid_adjustment()
adjustment = self._adaptive_learner.calculate_pid_adjustment(
    current_kp=self._pid_controller.kp,
    current_ki=self._pid_controller.ki,
    current_kd=self._pid_controller.kd,
    min_interval_hours=self._config.get(
        const.CONF_MIN_ADJUSTMENT_INTERVAL,
        const.MIN_ADJUSTMENT_INTERVAL
    ),
    min_cycles_since_adjustment=self._config.get(
        const.CONF_MIN_CYCLES_BETWEEN_ADJUSTMENTS,
        const.MIN_CYCLES_BETWEEN_ADJUSTMENTS
    ),
)
```

---

## Test Files to Create/Update

### New Test File: `tests/test_hybrid_rate_limiting.py`

```python
"""Tests for hybrid cycle + time based rate limiting."""

import pytest
from datetime import datetime, timedelta
from custom_components.adaptive_thermostat.adaptive.learning import AdaptiveLearner
from custom_components.adaptive_thermostat.adaptive.cycle_analysis import CycleMetrics


def create_cycle(overshoot=0.5):
    """Helper to create test cycle metrics."""
    return CycleMetrics(
        overshoot=overshoot,
        undershoot=0.1,
        settling_time=30,
        oscillations=0,
        rise_time=20,
    )


class TestHybridRateLimiting:
    """Test hybrid time + cycle rate limiting."""

    def test_time_gate_blocks_fast_adjustments(self):
        """Time < 8h blocks even with sufficient cycles."""
        learner = AdaptiveLearner()

        # Add 10 cycles (way more than needed)
        for _ in range(10):
            learner.add_cycle_metrics(create_cycle())

        # First adjustment succeeds
        result1 = learner.calculate_pid_adjustment(100, 0, 10)
        assert result1 is not None
        assert learner.get_cycles_since_adjustment() == 0

        # Add 5 more cycles immediately
        for _ in range(5):
            learner.add_cycle_metrics(create_cycle())

        # Second adjustment blocked by time (< 8h)
        result2 = learner.calculate_pid_adjustment(100, 0, 10)
        assert result2 is None  # Rate limited

    def test_cycle_gate_blocks_insufficient_data(self):
        """Insufficient cycles block even after time passes."""
        learner = AdaptiveLearner()

        # Add 3 cycles for first adjustment
        for _ in range(3):
            learner.add_cycle_metrics(create_cycle())

        result1 = learner.calculate_pid_adjustment(100, 0, 10)
        assert result1 is not None

        # Mock time to 10h later (time gate passes)
        learner._last_adjustment_time = datetime.now() - timedelta(hours=10)

        # Add only 1 cycle (need 3)
        learner.add_cycle_metrics(create_cycle())

        # Blocked by cycle gate
        result2 = learner.calculate_pid_adjustment(100, 0, 10)
        assert result2 is None

    def test_both_gates_pass_allows_adjustment(self):
        """Both time AND cycles passing allows adjustment."""
        learner = AdaptiveLearner()

        # First adjustment
        for _ in range(3):
            learner.add_cycle_metrics(create_cycle())
        result1 = learner.calculate_pid_adjustment(100, 0, 10)
        assert result1 is not None

        # Mock time + add cycles
        learner._last_adjustment_time = datetime.now() - timedelta(hours=8, seconds=1)
        for _ in range(3):
            learner.add_cycle_metrics(create_cycle())

        # Both gates pass
        result2 = learner.calculate_pid_adjustment(100, 0, 10)
        assert result2 is not None

    def test_cycle_counter_increments_on_add(self):
        """Counter increments each cycle."""
        learner = AdaptiveLearner()

        assert learner.get_cycles_since_adjustment() == 0

        learner.add_cycle_metrics(create_cycle())
        assert learner.get_cycles_since_adjustment() == 1

        learner.add_cycle_metrics(create_cycle())
        assert learner.get_cycles_since_adjustment() == 2

    def test_cycle_counter_resets_on_adjustment(self):
        """Counter resets after successful adjustment."""
        learner = AdaptiveLearner()

        for _ in range(5):
            learner.add_cycle_metrics(create_cycle())

        assert learner.get_cycles_since_adjustment() == 5

        learner.calculate_pid_adjustment(100, 0, 10)

        assert learner.get_cycles_since_adjustment() == 0

    def test_custom_interval_parameters(self):
        """Custom min_interval and min_cycles respected."""
        learner = AdaptiveLearner()

        # Add 2 cycles (less than default 3)
        for _ in range(2):
            learner.add_cycle_metrics(create_cycle())

        # With custom min_cycles=2, should succeed
        result = learner.calculate_pid_adjustment(
            100, 0, 10,
            min_cycles_since_adjustment=2
        )
        assert result is not None

    def test_boundary_conditions(self):
        """Test exact boundary (8h, 3 cycles)."""
        learner = AdaptiveLearner()

        # First adjustment
        for _ in range(3):
            learner.add_cycle_metrics(create_cycle())
        learner.calculate_pid_adjustment(100, 0, 10)

        # Exactly 3 cycles
        for _ in range(3):
            learner.add_cycle_metrics(create_cycle())

        # Exactly 8 hours (use slightly over to avoid clock precision issues)
        learner._last_adjustment_time = datetime.now() - timedelta(hours=8, seconds=1)

        # Should pass
        result = learner.calculate_pid_adjustment(100, 0, 10)
        assert result is not None
```

### Update Existing Tests

**`tests/test_learning.py`**:

Update these tests to account for new parameters:
- `test_min_adjustment_interval_constant_exists` → Update to assert 8
- `test_rate_limited_when_too_recent` → Add cycle counter logic
- `test_rate_limit_boundary` → Test both time AND cycle boundaries

---

## Verification Checklist

### Code Changes
- [ ] `const.py`: MIN_ADJUSTMENT_INTERVAL = 8
- [ ] `const.py`: New constants added
- [ ] `learning.py`: Cycle counter added to `__init__`
- [ ] `learning.py`: Counter increments in `add_cycle_metrics`
- [ ] `learning.py`: `_check_rate_limit` updated with cycle gate
- [ ] `learning.py`: Counter resets in `calculate_pid_adjustment`
- [ ] `persistence.py`: Save cycle counter
- [ ] `persistence.py`: Restore cycle counter with migration
- [ ] `climate.py`: Config schema updated

### Tests
- [ ] New test file created: `test_hybrid_rate_limiting.py`
- [ ] All 6 core tests pass
- [ ] Existing tests updated for new constant value
- [ ] Integration tests still pass
- [ ] Coverage > 90% for changed code

### Documentation
- [ ] CLAUDE.md updated with hybrid rate limiting
- [ ] Inline docstrings updated
- [ ] Log messages clear and actionable

### Manual Verification
- [ ] Install on test system
- [ ] Trigger 3 cycles
- [ ] Verify first adjustment after 12h (not 24h)
- [ ] Check logs for new messages
- [ ] Restart Home Assistant
- [ ] Verify counter persists

---

## Common Mistakes to Avoid

1. **OR instead of AND**: Rate limit check must require BOTH gates to pass
   ```python
   # WRONG
   return time_ok or cycles_ok

   # CORRECT
   return not (time_ok and cycles_ok)
   ```

2. **Forgetting to reset counter**: Must reset to 0 on successful adjustment
   ```python
   # In calculate_pid_adjustment after applying adjustment:
   self._cycles_since_last_adjustment = 0  # MUST HAVE THIS
   ```

3. **Incrementing in wrong place**: Counter increments on `add_cycle_metrics`, not `calculate_pid_adjustment`

4. **Missing migration logic**: Old installations need graceful upgrade path

5. **Hardcoded values**: Use constants and config, not magic numbers

---

## Log Messages Reference

**Rate limited by time**:
```
PID adjustment rate limited by time: 3.5h remaining (4 cycles ready)
```

**Rate limited by cycles**:
```
PID adjustment rate limited by cycles: need 2 more cycles (time gate passed)
```

**Rate limited by both**:
```
PID adjustment rate limited: need 1 more cycles AND 2.3h more time
```

**Adjustment successful**:
```
Overshoot >0.5°C detected: Kp *= 0.85
PID adjustment applied: Kp=85.0, Ki=0.0, Kd=10.0
```

---

## Performance Impact

**Memory**: +4 bytes per AdaptiveLearner instance (int counter)

**CPU**: Negligible (one additional integer comparison per adjustment check)

**Storage**: +1 field in JSON persistence (~10 bytes)

**Network**: None

---

## Rollback Procedure

If issues arise after deployment:

1. **Emergency rollback** (config-based):
   ```yaml
   adaptive_thermostat:
     min_adjustment_interval: 24
     min_cycles_between_adjustments: 100  # Effectively disables cycle gate
   ```

2. **Code rollback**:
   - Revert `const.py` line 139 to `MIN_ADJUSTMENT_INTERVAL = 24`
   - Cycle counter harmless if present but not used

3. **Full rollback**:
   - Git revert commit
   - Restart Home Assistant

---

## Support Resources

- Full plan: `PLAN_ADAPTIVE_RATE_LIMITING.md`
- Diagrams: `docs/diagrams/hybrid-rate-limiting.md`
- Proposal: `docs/RATE_LIMITING_PROPOSAL.md`
- Tests: `tests/test_hybrid_rate_limiting.py`

**Questions?** Review the detailed implementation plan first, then consult CLAUDE.md architecture section.
