"""Configuration fixture for pytest."""

import sys
from pathlib import Path
import pytest

# Alignement du sys.path pour les imports custom_components
smart_thermostat_dir = Path(__file__).resolve().parent.parent
target_dir = smart_thermostat_dir.parent.parent
if not (target_dir / "custom_components").exists():
    target_dir = Path("/home/adrien/HomeAssistant/core/config")

if str(target_dir) not in sys.path:
    sys.path.insert(0, str(target_dir))


@pytest.fixture(autouse=True)
def expected_lingering_timers():
    """Allow lingering timers for background keep_alive tasks in tests."""
    return True
