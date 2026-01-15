"""Constants for Adaptive Thermostat"""
DOMAIN = "adaptive_thermostat"

DEFAULT_NAME = "Adaptive Thermostat"
DEFAULT_OUTPUT_PRECISION = 1
DEFAULT_OUTPUT_MIN = 0
DEFAULT_OUTPUT_MAX = 100
DEFAULT_OUT_CLAMP_LOW = 0
DEFAULT_OUT_CLAMP_HIGH = 100
DEFAULT_PWM = '00:15:00'
DEFAULT_MIN_CYCLE_DURATION = '00:00:00'
DEFAULT_TOLERANCE = 0.3
DEFAULT_KP = 100
DEFAULT_KI = 0
DEFAULT_KD = 0
DEFAULT_KE = 0
DEFAULT_SAMPLING_PERIOD = '00:00:00'
DEFAULT_CONTROL_INTERVAL = 60  # seconds - used when keep_alive not specified
DEFAULT_SENSOR_STALL = '06:00:00'
DEFAULT_OUTPUT_SAFETY = 5.0
DEFAULT_PRESET_SYNC_MODE = "none"

CONF_HEATER = "heater"
CONF_COOLER = "cooler"
CONF_INVERT_HEATER = 'invert_heater'
CONF_SENSOR = "target_sensor"
CONF_OUTDOOR_SENSOR = "outdoor_sensor"
CONF_MIN_TEMP = "min_temp"
CONF_MAX_TEMP = "max_temp"
CONF_TARGET_TEMP = "target_temp"
CONF_HOT_TOLERANCE = "hot_tolerance"
CONF_COLD_TOLERANCE = "cold_tolerance"
CONF_AC_MODE = "ac_mode"
CONF_FORCE_OFF_STATE = "force_off_state"
CONF_MIN_CYCLE_DURATION = "min_cycle_duration"
CONF_MIN_OFF_CYCLE_DURATION = "min_off_cycle_duration"
CONF_MIN_CYCLE_DURATION_PID_OFF = 'min_cycle_duration_pid_off'
CONF_MIN_OFF_CYCLE_DURATION_PID_OFF = 'min_off_cycle_duration_pid_off'
CONF_CONTROL_INTERVAL = "control_interval"
CONF_SAMPLING_PERIOD = "sampling_period"
CONF_SENSOR_STALL = 'sensor_stall'
CONF_OUTPUT_SAFETY = 'output_safety'
CONF_INITIAL_HVAC_MODE = "initial_hvac_mode"
CONF_PRESET_SYNC_MODE = "preset_sync_mode"
CONF_AWAY_TEMP = "away_temp"
CONF_ECO_TEMP = "eco_temp"
CONF_BOOST_TEMP = "boost_temp"
CONF_COMFORT_TEMP = "comfort_temp"
CONF_HOME_TEMP = "home_temp"
CONF_SLEEP_TEMP = "sleep_temp"
CONF_ACTIVITY_TEMP = "activity_temp"
CONF_PRECISION = "precision"
CONF_TARGET_TEMP_STEP = "target_temp_step"
CONF_OUTPUT_PRECISION = "output_precision"
CONF_OUTPUT_MIN = "output_min"
CONF_OUTPUT_MAX = "output_max"
CONF_OUT_CLAMP_LOW = "out_clamp_low"
CONF_OUT_CLAMP_HIGH = "out_clamp_high"
CONF_PWM = "pwm"
CONF_BOOST_PID_OFF = 'boost_pid_off'
CONF_DEBUG = 'debug'
DEFAULT_DEBUG = False
CONF_HEATING_TYPE = "heating_type"

# Heating system types
HEATING_TYPE_FLOOR_HYDRONIC = "floor_hydronic"
HEATING_TYPE_RADIATOR = "radiator"
HEATING_TYPE_CONVECTOR = "convector"
HEATING_TYPE_FORCED_AIR = "forced_air"

# Valid heating types
VALID_HEATING_TYPES = [
    HEATING_TYPE_FLOOR_HYDRONIC,
    HEATING_TYPE_RADIATOR,
    HEATING_TYPE_CONVECTOR,
    HEATING_TYPE_FORCED_AIR,
]

# Heating type characteristics lookup table
# Used by adaptive/physics.py for PID initialization
HEATING_TYPE_CHARACTERISTICS = {
    HEATING_TYPE_FLOOR_HYDRONIC: {
        "pid_modifier": 0.5,      # Very conservative
        "pwm_period": 900,        # 15 minutes
        "description": "Floor heating with water - high thermal mass, slow response",
    },
    HEATING_TYPE_RADIATOR: {
        "pid_modifier": 0.7,      # Moderately conservative
        "pwm_period": 600,        # 10 minutes
        "description": "Traditional radiators - moderate thermal mass",
    },
    HEATING_TYPE_CONVECTOR: {
        "pid_modifier": 1.0,      # Standard
        "pwm_period": 300,        # 5 minutes
        "description": "Convection heaters - low thermal mass, faster response",
    },
    HEATING_TYPE_FORCED_AIR: {
        "pid_modifier": 1.3,      # Aggressive
        "pwm_period": 180,        # 3 minutes
        "description": "Forced air heating - very low thermal mass, fast response",
    },
}

# Adaptive learning PID limits
# These ensure PID values stay within safe operating ranges
PID_LIMITS = {
    "kp_min": 10.0,
    "kp_max": 500.0,
    "ki_min": 0.0,
    "ki_max": 1000.0,  # Increased from 100.0 to 1000.0 in v0.7.0 (100x scaling for hourly units)
    "kd_min": 0.0,
    "kd_max": 200.0,
    "ke_min": 0.0,
    "ke_max": 0.02,  # Reduced from 2.0 to 0.02 in v0.7.0 (100x scaling)
}

# Convergence thresholds for adaptive learning
# System is considered "tuned" when ALL metrics are within these bounds
CONVERGENCE_THRESHOLDS = {
    "overshoot_max": 0.2,       # Maximum acceptable overshoot in °C
    "oscillations_max": 1,      # Maximum acceptable oscillations
    "settling_time_max": 60,    # Maximum settling time in minutes
    "rise_time_max": 45,        # Maximum rise time in minutes
}

# Rule priority levels for PID adjustment conflict resolution
# Higher priority = takes precedence when rules conflict
RULE_PRIORITY_OSCILLATION = 3   # Safety - prevent oscillation damage
RULE_PRIORITY_OVERSHOOT = 2     # Stability - avoid temperature swings
RULE_PRIORITY_SLOW_RESPONSE = 1  # Performance - improve comfort

# Minimum number of cycles required before adaptive learning can recommend PID changes
MIN_CYCLES_FOR_LEARNING = 3

# Maximum number of cycles to retain in history (FIFO eviction when exceeded)
MAX_CYCLE_HISTORY = 100

# Minimum interval between PID adjustments in hours (rate limiting)
MIN_ADJUSTMENT_INTERVAL = 24

# Segment detection noise tolerance
# Temperature fluctuations below this threshold are ignored as sensor noise
SEGMENT_NOISE_TOLERANCE = 0.05  # 0.05C default

# Rate bounds for segment validation (C/hour)
# Rates outside these bounds are rejected as physically impossible
SEGMENT_RATE_MIN = 0.1   # Minimum 0.1 C/hour (extremely slow, but physically possible)
SEGMENT_RATE_MAX = 10.0  # Maximum 10 C/hour (very fast forced air systems)

# System-level configuration
CONF_MAIN_HEATER_SWITCH = "main_heater_switch"
CONF_MAIN_COOLER_SWITCH = "main_cooler_switch"
CONF_SOURCE_STARTUP_DELAY = "source_startup_delay"
CONF_SYNC_MODES = "sync_modes"
CONF_LEARNING_WINDOW_DAYS = "learning_window_days"
CONF_WEATHER_ENTITY = "weather_entity"
CONF_NOTIFY_SERVICE = "notify_service"
CONF_PERSISTENT_NOTIFICATION = "persistent_notification"
CONF_HOUSE_ENERGY_RATING = "house_energy_rating"
CONF_SUPPLY_TEMP_SENSOR = "supply_temp_sensor"
CONF_RETURN_TEMP_SENSOR = "return_temp_sensor"
CONF_FLOW_RATE_SENSOR = "flow_rate_sensor"
CONF_VOLUME_METER_ENTITY = "volume_meter_entity"
CONF_FALLBACK_FLOW_RATE = "fallback_flow_rate"
CONF_ENERGY_METER_ENTITY = "energy_meter_entity"
CONF_ENERGY_COST_ENTITY = "energy_cost_entity"

# Per-zone configuration
CONF_AREA_M2 = "area_m2"
CONF_CEILING_HEIGHT = "ceiling_height"
CONF_WINDOW_AREA_M2 = "window_area_m2"
CONF_WINDOW_ORIENTATION = "window_orientation"
CONF_WINDOW_RATING = "window_rating"
CONF_DEMAND_SWITCH = "demand_switch"
CONF_LINKED_ZONES = "linked_zones"
CONF_LINK_DELAY_MINUTES = "link_delay_minutes"
CONF_MIN_LEARNING_EVENTS = "min_learning_events"
CONF_MIN_CYCLE_TIME_WARNING = "min_cycle_time_warning"
CONF_MIN_CYCLE_TIME_CRITICAL = "min_cycle_time_critical"
CONF_MAX_POWER_M2 = "max_power_m2"

# Contact sensor configuration
CONF_CONTACT_SENSORS = "contact_sensors"
CONF_CONTACT_ACTION = "contact_action"
CONF_CONTACT_DELAY = "contact_delay"
CONF_CONTACT_LEARNING_GRACE = "contact_learning_grace"

# Night setback configuration
CONF_NIGHT_SETBACK = "night_setback"
CONF_NIGHT_SETBACK_ENABLED = "enabled"
CONF_NIGHT_SETBACK_DELTA = "delta"
CONF_NIGHT_SETBACK_START = "start"
CONF_NIGHT_SETBACK_END = "end"
CONF_NIGHT_SETBACK_SOLAR_RECOVERY = "solar_recovery"
CONF_NIGHT_SETBACK_RECOVERY_DEADLINE = "recovery_deadline"
CONF_MIN_EFFECTIVE_ELEVATION = "min_effective_elevation"
DEFAULT_MIN_EFFECTIVE_ELEVATION = 10.0

# Contact action types
CONTACT_ACTION_PAUSE = "pause"
CONTACT_ACTION_FROST = "frost_protection"
CONTACT_ACTION_NONE = "none"

VALID_CONTACT_ACTIONS = [
    CONTACT_ACTION_PAUSE,
    CONTACT_ACTION_FROST,
    CONTACT_ACTION_NONE,
]

# Window orientations
WINDOW_ORIENTATION_NORTH = "north"
WINDOW_ORIENTATION_NORTHEAST = "northeast"
WINDOW_ORIENTATION_EAST = "east"
WINDOW_ORIENTATION_SOUTHEAST = "southeast"
WINDOW_ORIENTATION_SOUTH = "south"
WINDOW_ORIENTATION_SOUTHWEST = "southwest"
WINDOW_ORIENTATION_WEST = "west"
WINDOW_ORIENTATION_NORTHWEST = "northwest"
WINDOW_ORIENTATION_ROOF = "roof"

VALID_WINDOW_ORIENTATIONS = [
    WINDOW_ORIENTATION_NORTH,
    WINDOW_ORIENTATION_NORTHEAST,
    WINDOW_ORIENTATION_EAST,
    WINDOW_ORIENTATION_SOUTHEAST,
    WINDOW_ORIENTATION_SOUTH,
    WINDOW_ORIENTATION_SOUTHWEST,
    WINDOW_ORIENTATION_WEST,
    WINDOW_ORIENTATION_NORTHWEST,
    WINDOW_ORIENTATION_ROOF,
]

# Energy ratings
VALID_ENERGY_RATINGS = [
    "A++++", "A+++", "A++", "A+", "A", "B", "C", "D", "E", "F", "G"
]

# Default values for new configuration options
DEFAULT_SOURCE_STARTUP_DELAY = 30
DEFAULT_LINK_DELAY_MINUTES = 20  # ~25% of typical floor heating PWM cycle
DEFAULT_CONTACT_DELAY = 120
DEFAULT_CONTACT_LEARNING_GRACE = 300
DEFAULT_LEARNING_WINDOW_DAYS = 7
DEFAULT_MIN_LEARNING_EVENTS = 3
DEFAULT_MIN_CYCLE_TIME_WARNING = 15
DEFAULT_MIN_CYCLE_TIME_CRITICAL = 10
DEFAULT_MAX_POWER_M2 = 20
DEFAULT_CEILING_HEIGHT = 2.5
DEFAULT_WINDOW_RATING = "hr++"
DEFAULT_FALLBACK_FLOW_RATE = 0.5
DEFAULT_NIGHT_SETBACK_DELTA = 2.0
DEFAULT_VACATION_TARGET_TEMP = 12.0
DEFAULT_FROST_PROTECTION_TEMP = 5.0
DEFAULT_SYNC_MODES = True
DEFAULT_DEMAND_THRESHOLD = 5.0  # PID output % threshold for zone demand
DEFAULT_PERSISTENT_NOTIFICATION = True

# Ke Learning constants
# Minimum consecutive converged cycles before Ke learning activates
MIN_CONVERGENCE_CYCLES_FOR_KE = 3
# Minimum observations required for Ke correlation calculation
KE_MIN_OBSERVATIONS = 5
# Minimum outdoor temperature range (Celsius) for meaningful correlation
KE_MIN_TEMP_RANGE = 5.0
# Minimum hours between Ke adjustments (rate limiting)
KE_ADJUSTMENT_INTERVAL = 48
# Step size for Ke adjustments (reduced from 0.1 to 0.001 in v0.7.0 - 100x scaling)
KE_ADJUSTMENT_STEP = 0.001
# Minimum absolute correlation to consider Ke adjustment
KE_CORRELATION_THRESHOLD = 0.3
# Maximum observations to retain (FIFO eviction)
KE_MAX_OBSERVATIONS = 100
# Duration in minutes at target temperature to consider steady state
KE_STEADY_STATE_DURATION = 15
