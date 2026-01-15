# Hybrid Rate Limiting Visual Documentation

## Decision Flow Diagram

```mermaid
flowchart TD
    Start[Calculate PID Adjustment Request] --> HasCycles{Has 3+ cycles<br/>in history?}

    HasCycles -->|No| InsufficientData[Return None<br/>Insufficient data]
    HasCycles -->|Yes| CheckTime[Check Time Gate]

    CheckTime --> TimeElapsed{Time since last<br/>adjustment >= 8h?}

    TimeElapsed -->|No| LogTime[Log: Blocked by time<br/>X hours remaining]
    LogTime --> RateLimited[Return None<br/>Rate Limited]

    TimeElapsed -->|Yes| CheckCycles[Check Cycle Gate]

    CheckCycles --> CyclesCompleted{Cycles since last<br/>adjustment >= 3?}

    CyclesCompleted -->|No| LogCycles[Log: Blocked by cycles<br/>Need X more cycles]
    LogCycles --> RateLimited

    CyclesCompleted -->|Yes| CheckConvergence[Check Convergence]

    CheckConvergence --> IsConverged{System<br/>converged?}

    IsConverged -->|Yes| LogConverged[Log: System tuned<br/>Skip adjustment]
    LogConverged --> SkipAdjustment[Return None<br/>Already tuned]

    IsConverged -->|No| EvaluateRules[Evaluate PID Rules]

    EvaluateRules --> RulesApply{Any rules<br/>triggered?}

    RulesApply -->|No| NoAdjustment[Return None<br/>Metrics acceptable]

    RulesApply -->|Yes| ApplyRules[Apply Rules<br/>Calculate new PID]

    ApplyRules --> EnforceLimits[Enforce PID Limits]

    EnforceLimits --> ResetCounters[Reset:<br/>- cycles_since = 0<br/>- last_time = now]

    ResetCounters --> Success[Return new PID values]

    style Success fill:#90EE90
    style RateLimited fill:#FFB6C1
    style SkipAdjustment fill:#87CEEB
    style InsufficientData fill:#FFB6C1
    style NoAdjustment fill:#87CEEB
```

## Time + Cycle Gate States

```mermaid
stateDiagram-v2
    [*] --> Waiting: System starts/<br/>Adjustment made

    Waiting --> TimeOnly: Time >= 8h<br/>Cycles < 3

    Waiting --> CyclesOnly: Cycles >= 3<br/>Time < 8h

    Waiting --> BothReady: Time >= 8h<br/>AND Cycles >= 3

    TimeOnly --> BothReady: Complete 1-2<br/>more cycles

    CyclesOnly --> BothReady: Wait X<br/>more hours

    BothReady --> Evaluating: calculate_pid_adjustment()

    Evaluating --> Adjusted: Rules triggered<br/>New PID applied
    Evaluating --> NoChange: Converged OR<br/>No rules

    Adjusted --> Waiting: Counters reset
    NoChange --> Waiting: Counters unchanged

    note right of Waiting
        cycles_since_adjustment: int
        time_since_adjustment: timedelta
    end note

    note right of BothReady
        BOTH gates must pass
        to allow adjustment
    end note
```

## Timeline Comparison: Old vs New

```mermaid
gantt
    title PID Adjustment Timeline: 24h Wall Clock vs 8h Hybrid
    dateFormat HH:mm
    axisFormat %H:%M

    section Old (24h)
    Install           :milestone, m1, 00:00, 0h
    3 cycles (12h)    :done, old1, 00:00, 12h
    Wait...           :crit, old2, 12:00, 12h
    Adjustment 1      :milestone, m2, 24:00, 0h
    3 cycles (12h)    :done, old3, 24:00, 12h
    Wait...           :crit, old4, 36:00, 12h

    section New (8h+3cyc)
    Install           :milestone, m3, 00:00, 0h
    3 cycles (12h)    :done, new1, 00:00, 12h
    Adjustment 1      :milestone, m4, 12:00, 0h
    3 cycles (12h)    :done, new2, 12:00, 12h
    Adjustment 2      :milestone, m5, 24:00, 0h
    3 cycles (12h)    :done, new3, 24:00, 12h
    Adjustment 3      :milestone, m6, 36:00, 0h
```

**Key Insight**: In 48 hours, old system makes 2 adjustments, new system makes 4 adjustments (2x faster).

## Example Scenarios

```mermaid
sequenceDiagram
    participant User
    participant Thermostat
    participant Cycle Tracker
    participant Adaptive Learner
    participant Rate Limiter

    Note over User,Rate Limiter: Scenario 1: Fresh Install

    User->>Thermostat: Set target 20°C
    Thermostat->>Cycle Tracker: Start tracking

    loop Every 4 hours (floor heating)
        Cycle Tracker->>Adaptive Learner: add_cycle_metrics()
        Adaptive Learner->>Adaptive Learner: cycles_since += 1
    end

    Note over Adaptive Learner: After 12h: 3 cycles complete

    Thermostat->>Adaptive Learner: calculate_pid_adjustment()
    Adaptive Learner->>Rate Limiter: _check_rate_limit(8h, 3cyc)

    Rate Limiter-->>Rate Limiter: Time: 12h >= 8h ✓<br/>Cycles: 3 >= 3 ✓

    Rate Limiter-->>Adaptive Learner: Gates passed
    Adaptive Learner->>Adaptive Learner: Evaluate rules
    Adaptive Learner-->>Thermostat: New PID: Kp=85
    Adaptive Learner->>Adaptive Learner: cycles_since = 0<br/>last_time = now

    Note over User,Rate Limiter: Scenario 2: Too Soon

    loop 2 cycles (8h)
        Cycle Tracker->>Adaptive Learner: add_cycle_metrics()
    end

    Thermostat->>Adaptive Learner: calculate_pid_adjustment()
    Adaptive Learner->>Rate Limiter: _check_rate_limit(8h, 3cyc)

    Rate Limiter-->>Rate Limiter: Time: 8h >= 8h ✓<br/>Cycles: 2 < 3 ✗

    Rate Limiter-->>Adaptive Learner: Blocked by cycles
    Adaptive Learner-->>Thermostat: None (rate limited)
```

## Configuration Impact Matrix

```mermaid
graph TD
    Config[Configuration Options] --> Conservative
    Config --> Default
    Config --> Aggressive

    Conservative --> C1[min_interval: 12h<br/>min_cycles: 5]
    Default --> D1[min_interval: 8h<br/>min_cycles: 3]
    Aggressive --> A1[min_interval: 6h<br/>min_cycles: 2]

    C1 --> C2[Best for:<br/>- Slow systems<br/>- High noise<br/>- Unstable environment]
    D1 --> D2[Best for:<br/>- Most installations<br/>- Standard heating<br/>- Normal conditions]
    A1 --> A2[Best for:<br/>- Fast systems<br/>- Clean data<br/>- Experienced users]

    C2 --> C3[Convergence:<br/>4-7 days]
    D2 --> D3[Convergence:<br/>2-3 days]
    A2 --> A3[Convergence:<br/>1-2 days]

    style Conservative fill:#FFE4B5
    style Default fill:#90EE90
    style Aggressive fill:#FFB6C1
```

## Safety Gates Visualization

```mermaid
flowchart LR
    Input[PID Adjustment Request] --> Gate1[Gate 1:<br/>Minimum Data]

    Gate1 --> Check1{>= 3 cycles<br/>in history?}
    Check1 -->|No| Block1[❌ Blocked<br/>Insufficient data]
    Check1 -->|Yes| Gate2[Gate 2:<br/>Time Elapsed]

    Gate2 --> Check2{>= 8 hours<br/>since last?}
    Check2 -->|No| Block2[❌ Blocked<br/>Too soon]
    Check2 -->|Yes| Gate3[Gate 3:<br/>Cycle Count]

    Gate3 --> Check3{>= 3 cycles<br/>since last?}
    Check3 -->|No| Block3[❌ Blocked<br/>Need more cycles]
    Check3 -->|Yes| Gate4[Gate 4:<br/>Convergence]

    Gate4 --> Check4{System<br/>converged?}
    Check4 -->|Yes| Skip[⏭ Skip<br/>Already tuned]
    Check4 -->|No| Gate5[Gate 5:<br/>PID Limits]

    Gate5 --> Adjust[Apply Adjustment]

    Adjust --> Check5{New PID within<br/>limits?}
    Check5 -->|No| Clamp[⚠️ Clamp to limits]
    Check5 -->|Yes| Success[✅ Success]

    Clamp --> Success

    style Block1 fill:#FF6B6B
    style Block2 fill:#FF6B6B
    style Block3 fill:#FF6B6B
    style Skip fill:#4ECDC4
    style Success fill:#95E77D
```

## Convergence Timeline Projection

```mermaid
graph LR
    subgraph "Day 1"
        Install[Install] --> Cycle1[3 cycles<br/>0-12h]
        Cycle1 --> Adj1[Adj 1<br/>12h]
    end

    subgraph "Day 2"
        Adj1 --> Cycle2[3 cycles<br/>12-24h]
        Cycle2 --> Adj2[Adj 2<br/>24h]
        Adj2 --> Cycle3[3 cycles<br/>24-36h]
        Cycle3 --> Adj3[Adj 3<br/>36h]
    end

    subgraph "Day 3"
        Adj3 --> Cycle4[3 cycles<br/>36-48h]
        Cycle4 --> Adj4[Adj 4<br/>48h]
        Adj4 --> Cycle5[3 cycles<br/>48-60h]
        Cycle5 --> Converged[Converged<br/>60h]
    end

    style Install fill:#FFE4B5
    style Adj1 fill:#87CEEB
    style Adj2 fill:#87CEEB
    style Adj3 fill:#87CEEB
    style Adj4 fill:#87CEEB
    style Converged fill:#90EE90
```

**Projected Timeline for Floor Hydronic (4h cycles)**:
- Install → First Adjustment: 12 hours (3 cycles)
- First → Second: 12 hours (3 cycles + 8h time gate)
- Second → Third: 12 hours
- Third → Converged: ~12-24 hours
- **Total: 2.5-3 days** (vs 14 days with 24h interval)

## Rate Limiting State Machine

```mermaid
stateDiagram-v2
    [*] --> Initialized: Component starts

    Initialized --> Collecting: First heating cycle

    Collecting --> HasMinData: 3 cycles collected

    HasMinData --> WaitingTime: Time < 8h<br/>Cycles >= 3

    HasMinData --> WaitingCycles: Time >= 8h<br/>Cycles < 3

    HasMinData --> Ready: Time >= 8h<br/>AND Cycles >= 3

    WaitingTime --> Ready: Time passes
    WaitingCycles --> Ready: More cycles

    Ready --> Evaluating: calculate_pid_adjustment()

    Evaluating --> Converged: All metrics OK
    Evaluating --> Adjusting: Rules triggered

    Converged --> Monitoring: No changes needed
    Monitoring --> Collecting: External change

    Adjusting --> Collecting: Counters reset<br/>Start new cycle

    note right of Ready
        Only state where
        adjustments can occur
    end note

    note right of Adjusting
        cycles_since = 0
        last_adjustment_time = now
    end note
```
