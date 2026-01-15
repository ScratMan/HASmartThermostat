# Disturbance Rejection Architecture

## System Overview

```mermaid
flowchart TB
    subgraph "Environmental Sensors"
        OS[Outdoor Temp<br/>Sensor]
        WS[Wind Speed<br/>Sensor]
        OCC[Occupancy<br/>Sensors]
        SUN[Sun Position<br/>Calculator]
    end

    subgraph "Cycle Tracking"
        CT[CycleTrackerManager]
        TH[Temperature<br/>History]
        CT --> TH
    end

    subgraph "Disturbance Detection"
        DD[DisturbanceDetector]
        DS[Solar Gain<br/>Detection]
        DW[Wind Loss<br/>Detection]
        DO[Outdoor Swing<br/>Detection]
        DOCC[Occupancy Gain<br/>Detection]

        DD --> DS
        DD --> DW
        DD --> DO
        DD --> DOCC
    end

    subgraph "Cycle Metrics"
        CM[CycleMetrics]
        DF[DisturbanceFlags]
        CM --> DF
    end

    subgraph "Adaptive Learning"
        AL[AdaptiveLearner]
        CF[Cycle Filter<br/>exclude_disturbed=True]
        PR[PID Rules<br/>Evaluation]

        AL --> CF
        CF --> PR
    end

    subgraph "PID Controller"
        PID[PID Controller]
        KP[Kp Gain]
        KI[Ki Gain]
        KD[Kd Gain]

        PID --> KP
        PID --> KI
        PID --> KD
    end

    %% Data flow
    OS --> DD
    WS --> DD
    OCC --> DD
    SUN --> DD

    CT --> DD
    TH --> DD

    DD --> DF
    DF --> CM

    CM --> AL
    CF --> |Clean Cycles| PR
    PR --> |Adjusted Gains| PID

    %% Styling
    classDef sensor fill:#e1f5ff,stroke:#0277bd
    classDef detection fill:#fff3e0,stroke:#ef6c00
    classDef learning fill:#e8f5e9,stroke:#2e7d32
    classDef control fill:#f3e5f5,stroke:#6a1b9a

    class OS,WS,OCC,SUN sensor
    class DD,DS,DW,DO,DOCC,DF detection
    class AL,CF,PR learning
    class PID,KP,KI,KD control
```

## Detection Algorithm Flow

### Solar Gain Detection
```mermaid
flowchart TD
    START[Temperature History<br/>+ Cycle Times]

    CHECK_WINDOW{Window<br/>Orientation<br/>Sun-Exposed?}
    CHECK_WINDOW -->|No| NO_SOLAR[No Solar Gain]
    CHECK_WINDOW -->|Yes| CHECK_SPIKE

    CHECK_SPIKE{Overshoot<br/>&gt;0.5°C in<br/>Settling?}
    CHECK_SPIKE -->|No| NO_SOLAR
    CHECK_SPIKE -->|Yes| GET_SUN

    GET_SUN[Get Sun Position<br/>at Spike Time]
    GET_SUN --> CHECK_AZIMUTH

    CHECK_AZIMUTH{Sun Azimuth<br/>Matches Window<br/>±45°?}
    CHECK_AZIMUTH -->|No| NO_SOLAR
    CHECK_AZIMUTH -->|Yes| CHECK_ELEVATION

    CHECK_ELEVATION{Sun Elevation<br/>&gt;10°?}
    CHECK_ELEVATION -->|No| NO_SOLAR
    CHECK_ELEVATION -->|Yes| SOLAR_DETECTED

    SOLAR_DETECTED[Solar Gain Detected<br/>+ Evidence String]

    classDef decision fill:#fff3e0,stroke:#ef6c00
    classDef result fill:#e8f5e9,stroke:#2e7d32

    class CHECK_WINDOW,CHECK_SPIKE,CHECK_AZIMUTH,CHECK_ELEVATION decision
    class NO_SOLAR,SOLAR_DETECTED result
```

### Wind Loss Detection
```mermaid
flowchart TD
    START[Cycle Metrics<br/>+ Wind Sensor]

    CHECK_SENSOR{Wind Sensor<br/>Configured?}
    CHECK_SENSOR -->|No| NO_WIND[No Wind Loss]
    CHECK_SENSOR -->|Yes| GET_WIND

    GET_WIND[Get Avg Wind Speed<br/>During Cycle]
    GET_WIND --> CHECK_SPEED

    CHECK_SPEED{Wind Speed<br/>&gt;15 km/h?}
    CHECK_SPEED -->|No| NO_WIND
    CHECK_SPEED -->|Yes| CHECK_METRICS

    CHECK_METRICS{Slow Rise Time<br/>OR<br/>Undershoot?}
    CHECK_METRICS -->|No| NO_WIND
    CHECK_METRICS -->|Yes| WIND_DETECTED

    WIND_DETECTED[Wind Loss Detected<br/>+ Evidence String]

    classDef decision fill:#fff3e0,stroke:#ef6c00
    classDef result fill:#e8f5e9,stroke:#2e7d32

    class CHECK_SENSOR,CHECK_SPEED,CHECK_METRICS decision
    class NO_WIND,WIND_DETECTED result
```

### Outdoor Temperature Swing Detection
```mermaid
flowchart TD
    START[Cycle Start<br/>+ Cycle End<br/>+ Outdoor Sensor]

    CHECK_SENSOR{Outdoor Sensor<br/>Configured?}
    CHECK_SENSOR -->|No| NO_SWING[No Outdoor Swing]
    CHECK_SENSOR -->|Yes| GET_TEMPS

    GET_TEMPS[Get Outdoor Temp<br/>at Start and End]
    GET_TEMPS --> CALC_DELTA

    CALC_DELTA[Calculate<br/>Absolute Change]
    CALC_DELTA --> CHECK_DELTA

    CHECK_DELTA{Change<br/>&gt;2°C?}
    CHECK_DELTA -->|No| NO_SWING
    CHECK_DELTA -->|Yes| SWING_DETECTED

    SWING_DETECTED[Outdoor Swing Detected<br/>+ Evidence String]

    classDef decision fill:#fff3e0,stroke:#ef6c00
    classDef result fill:#e8f5e9,stroke:#2e7d32

    class CHECK_SENSOR,CHECK_DELTA decision
    class NO_SWING,SWING_DETECTED result
```

## Learning Filter Flow

### Cycle Filtering for PID Adjustment
```mermaid
flowchart TD
    START[calculate_pid_adjustment<br/>called]

    CHECK_HISTORY{Enough<br/>Cycles in<br/>History?}
    CHECK_HISTORY -->|No| RETURN_NONE[Return None]
    CHECK_HISTORY -->|Yes| CHECK_RATE

    CHECK_RATE{Rate<br/>Limited?}
    CHECK_RATE -->|Yes| RETURN_NONE
    CHECK_RATE -->|No| CHECK_ENABLED

    CHECK_ENABLED{exclude_disturbed<br/>_cycles=True?}
    CHECK_ENABLED -->|No| USE_ALL[Use All Cycles]
    CHECK_ENABLED -->|Yes| FILTER

    FILTER[Filter Out<br/>Disturbed Cycles]
    FILTER --> LOG_FILTERED

    LOG_FILTERED[Log: Filtered N<br/>disturbed cycles]
    LOG_FILTERED --> CHECK_CLEAN

    CHECK_CLEAN{Enough<br/>Clean Cycles?}
    CHECK_CLEAN -->|No| RETURN_NONE
    CHECK_CLEAN -->|Yes| USE_CLEAN

    USE_CLEAN[Use Clean Cycles<br/>for Metrics]
    USE_ALL --> CALC_METRICS
    USE_CLEAN --> CALC_METRICS

    CALC_METRICS[Calculate Avg<br/>Overshoot, Oscillations,<br/>Rise Time, etc.]

    CALC_METRICS --> CHECK_CONVERGED

    CHECK_CONVERGED{System<br/>Converged?}
    CHECK_CONVERGED -->|Yes| RETURN_NONE
    CHECK_CONVERGED -->|No| EVAL_RULES

    EVAL_RULES[Evaluate PID Rules]
    EVAL_RULES --> RESOLVE

    RESOLVE[Resolve Conflicts<br/>by Priority]
    RESOLVE --> RETURN_ADJ

    RETURN_ADJ[Return Adjusted<br/>Kp, Ki, Kd]

    classDef decision fill:#fff3e0,stroke:#ef6c00
    classDef process fill:#e1f5ff,stroke:#0277bd
    classDef result fill:#e8f5e9,stroke:#2e7d32

    class CHECK_HISTORY,CHECK_RATE,CHECK_ENABLED,CHECK_CLEAN,CHECK_CONVERGED decision
    class FILTER,LOG_FILTERED,CALC_METRICS,EVAL_RULES,RESOLVE process
    class RETURN_NONE,USE_ALL,USE_CLEAN,RETURN_ADJ result
```

## Data Model Relationships

```mermaid
classDiagram
    class CycleMetrics {
        +float overshoot
        +float undershoot
        +float settling_time
        +int oscillations
        +float rise_time
        +DisturbanceFlags disturbances
    }

    class DisturbanceFlags {
        +bool solar_gain
        +bool wind_loss
        +bool outdoor_temp_swing
        +bool occupancy_gain
        +bool any_disturbance
        +str solar_evidence
        +str wind_evidence
        +str outdoor_evidence
        +str occupancy_evidence
        +set_any_disturbance()
    }

    class DisturbanceDetector {
        -SunPositionCalculator sun_calculator
        -str outdoor_sensor_id
        -str wind_sensor_id
        -List~str~ occupancy_sensor_ids
        -str window_orientation
        -HomeAssistant hass
        +detect_disturbances() DisturbanceFlags
        -_detect_solar_gain() Tuple
        -_detect_wind_loss() Tuple
        -_detect_outdoor_temp_swing() Tuple
        -_detect_occupancy_gain() Tuple
    }

    class CycleTrackerManager {
        -DisturbanceDetector disturbance_detector
        -List temperature_history
        +_finalize_cycle()
    }

    class AdaptiveLearner {
        -List~CycleMetrics~ cycle_history
        +calculate_pid_adjustment() Dict
        -_filter_clean_cycles() List
    }

    CycleMetrics "1" *-- "1" DisturbanceFlags : contains
    DisturbanceDetector ..> DisturbanceFlags : creates
    CycleTrackerManager "1" --> "1" DisturbanceDetector : uses
    CycleTrackerManager ..> CycleMetrics : creates
    AdaptiveLearner "1" o-- "*" CycleMetrics : stores
```

## Sequence Diagram: Cycle Completion with Disturbance Detection

```mermaid
sequenceDiagram
    participant TH as TemperatureManager
    participant CT as CycleTrackerManager
    participant DD as DisturbanceDetector
    participant SUN as SunCalculator
    participant OS as OutdoorSensor
    participant WS as WindSensor
    participant AL as AdaptiveLearner

    Note over CT: Settling complete
    CT->>CT: _finalize_cycle()

    Note over CT: Validate cycle
    CT->>CT: _is_cycle_valid()

    Note over CT: Detect disturbances
    CT->>DD: detect_disturbances(temp_history, target, start, end)

    DD->>SUN: get_position_at_time(spike_time)
    SUN-->>DD: SunPosition(azimuth, elevation)

    DD->>DD: _detect_solar_gain()
    Note over DD: Check if sun azimuth<br/>matches window orientation

    DD->>OS: Get outdoor temp at start/end
    OS-->>DD: start_temp, end_temp
    DD->>DD: _detect_outdoor_temp_swing()

    DD->>WS: Get avg wind speed
    WS-->>DD: wind_speed
    DD->>DD: _detect_wind_loss()

    DD-->>CT: DisturbanceFlags(solar=True, wind=False, ...)

    Note over CT: Create metrics with disturbances
    CT->>CT: CycleMetrics(overshoot, ..., disturbances)

    CT->>AL: add_cycle_metrics(metrics)
    AL->>AL: Store in cycle_history

    CT->>AL: update_convergence_tracking(metrics)

    Note over AL: Later: PID adjustment
    AL->>AL: calculate_pid_adjustment()
    AL->>AL: Filter disturbed cycles
    Note over AL: Only clean cycles<br/>used for PID tuning

    AL-->>CT: Return adjusted PID gains
```

## Configuration Flow

```mermaid
flowchart LR
    subgraph "Config YAML"
        DC[Domain Config:<br/>disturbance_rejection:<br/>  enabled: true<br/>  wind_sensor: ...<br/>  wind_threshold: 15]
        ZC[Zone Config:<br/>outdoor_sensor: ...<br/>window_orientation: south<br/>occupancy_sensors: ...]
    end

    subgraph "Component Initialization"
        INIT[__init__.py]
        CLI[climate.py]
    end

    subgraph "Runtime Components"
        DD[DisturbanceDetector]
        CT[CycleTrackerManager]
    end

    DC --> INIT
    ZC --> CLI

    INIT --> |Pass config| CLI
    CLI --> |Instantiate with sensors| DD
    CLI --> |Pass detector| CT

    CT --> |Use during finalize| DD

    classDef config fill:#e8eaf6,stroke:#3f51b5
    classDef init fill:#fff3e0,stroke:#ef6c00
    classDef runtime fill:#e8f5e9,stroke:#2e7d32

    class DC,ZC config
    class INIT,CLI init
    class DD,CT runtime
```

## Rollback Safety

```mermaid
flowchart TB
    START[System Running with<br/>Disturbance Rejection]

    ISSUE{Issue<br/>Detected?}
    ISSUE -->|No| CONTINUE[Continue Operation]
    ISSUE -->|Yes| ASSESS

    ASSESS{Severity?}
    ASSESS -->|Minor| CONFIG[Update Config:<br/>enabled: false]
    ASSESS -->|Major| SERVICE[Service Call:<br/>set_disturbance_rejection<br/>enabled=false]
    ASSESS -->|Critical| ROLLBACK[Git Rollback:<br/>Revert to commit<br/>before PR]

    CONFIG --> RESTART[Restart HA]
    SERVICE --> IMMEDIATE[Immediate Effect<br/>No Restart]

    RESTART --> LEGACY
    IMMEDIATE --> LEGACY
    ROLLBACK --> LEGACY

    LEGACY[Legacy Behavior:<br/>All cycles used<br/>for learning]

    CONTINUE --> MONITOR
    LEGACY --> MONITOR

    MONITOR[Monitor via<br/>Sensor Attributes]

    classDef issue fill:#ffebee,stroke:#c62828
    classDef fix fill:#fff3e0,stroke:#ef6c00
    classDef ok fill:#e8f5e9,stroke:#2e7d32

    class ISSUE,ASSESS issue
    class CONFIG,SERVICE,ROLLBACK,RESTART,IMMEDIATE fix
    class CONTINUE,LEGACY,MONITOR ok
```

## Testing Strategy Layers

```mermaid
flowchart TB
    subgraph "Unit Tests"
        UT1[Detection Algorithm Tests<br/>test_disturbance_detection.py]
        UT2[Learning Filter Tests<br/>test_learning_disturbance_filtering.py]
        UT3[Cycle Analysis Tests<br/>test_cycle_analysis.py]
    end

    subgraph "Integration Tests"
        IT1[Cycle Tracking Integration<br/>test_integration_disturbance_cycle.py]
        IT2[End-to-End Learning Flow<br/>test_integration_cycle_learning.py]
    end

    subgraph "Validation Tests"
        VT1[Real-World Scenarios<br/>test_disturbance_validation.py]
        VT2[Sunny Winter Day Test]
        VT3[Windy Day Test]
        VT4[Clean Convergence Test]
    end

    subgraph "Utilities"
        UTIL[Synthetic Data Generator<br/>disturbance_simulator.py]
    end

    UTIL --> UT1
    UTIL --> UT2
    UTIL --> IT1
    UTIL --> VT1

    UT1 --> IT1
    UT2 --> IT2
    UT3 --> IT1

    IT1 --> VT1
    IT2 --> VT1

    VT1 --> VT2
    VT1 --> VT3
    VT1 --> VT4

    classDef unit fill:#e1f5ff,stroke:#0277bd
    classDef integration fill:#fff3e0,stroke:#ef6c00
    classDef validation fill:#e8f5e9,stroke:#2e7d32
    classDef util fill:#f3e5f5,stroke:#6a1b9a

    class UT1,UT2,UT3 unit
    class IT1,IT2 integration
    class VT1,VT2,VT3,VT4 validation
    class UTIL util
```
