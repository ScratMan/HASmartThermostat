# custom_components
missing feature test repository

## PID controller thermostat

### Installation:
1. go to <conf-dir> default /homeassistant/.homeassistant/ (it's where your configuration.yalm is)
2. clone this repository
3. Go into pid_controller/pid_controller and run sudo python3 setup.py install
4. Set up the smart_thermostat and have fun

### Usage:
pid controller will be called periodically.
If no pwm interval is definde. It will set the state of "heater" 0-"difference"
Else it will turn off and on the heater proportionally.

#### Autotune:
You can use the autotune feature to set the PID parameters.

Issue! I'couldn't yet save the settings to the configuration.yaml file.
The PID parmaters set by the autotune won't be stored and the process restarts everytime hassio is restarted.
To save the parameters read log, it will be shown like this:
LOGGER.info("Set Kd, Ki, Kd. Smart thermostat now runs on PID Controller." self.kp , self.ki, self.kd)

### Parameters:

#### Still same:

* name (Required): Name of thermostat
* heater (Required): entity_id for heater switch, must be a toggle device. Becomes air conditioning switch when ac_mode is set to True
* target_sensor (Required): entity_id for a temperature sensor, target_sensor.state must be temperature.
* min_temp (Optional): Set minimum set point available (default: 7)
* max_temp (Optional): Set maximum set point available (default: 35)
* target_temp (Optional): Set initial target temperature. Failure to set this variable will result in target temperature being set to null on startup. As of version 0.59, it will retain the target temperature set before restart if available.
* ac_mode (Optional): Set the switch specified in the heater option to be treated as a cooling device instead of a heating device.
* initial_operation_mode (Optional): Set the initial operation mode. Valid values are off or auto. Value has to be double quoted. If this parameter is not set, it is preferable to set a keep_alive value. This is helpful to align any discrepancies between generic_thermostat and heater state.
* away_temp (Optional): Set the temperature used by “away_mode”. If this is not specified, away_mode feature will not get activated.

#### Removed:

* min_cycle_duration (Optional):
* cold_tolerance (Optional):
* hot_tolerance (Optional):

#### Edited:

* keep_alive (Required): Set a keep-alive interval. Interval pid controller will be updated.

#### New:

* kp (Optional): Set PID parameter, p controll value.
* ki (Optional): Set PID parameter, i controll value.
* kd (Optional): Set PID parameter, d controll value.
* pwm (Optional): Set period time for pwm signal in minutes. If it's not set pwm is disabled.
* autotune (Optional): Chose a string for autotune settings.  If it's not set autotune is disabled.
tuning_rules

ruler | Kp_divisor, Ki_divisor, Kd_divisor
------------ | -------------
"ziegler-nichols" | 34, 40, 160
"tyreus-luyben" | 44,  9, 126
"ciancone-marlin" | 66, 88, 162
"pessen-integral" | 28, 50, 133
"some-overshoot" | 60, 40,  60
"no-overshoot" | 100, 40,  60
"brewing" | 2.5, 6, 380

* difference (Optional): Set analog output offset to 0. (default : 100). If it's 500 the output Value can be everything between 0, 500.
* noiseband (Optional): (default : 0.5), set noiseband (float): Determines by how much the input value must overshoot/undershoot the setpoint before the state changes.

#### configuration.yaml
```
climate:
  - platform: smart_thermostat
    name: Study
    heater: switch.study_heater
    target_sensor: sensor.study_temperature
    min_temp: 15
    max_temp: 21
    ac_mode: False
    target_temp: 17
    keep_alive:
      seconds: 5
    initial_operation_mode: "off"
    away_temp: 16
    kp : 5
    ki : 3
    kd : 2
    pwm : 10
    autotune : ziegler-nichols
    difference : 100
    noiseband : 0.5
```
### Help

The python PID module:
[https://github.com/hirschmann/pid-autotune](https://github.com/hirschmann/pid-autotune)

PID controller explained. Would recommoned to read some of it:
[https://controlguru.com/table-of-contents/](https://controlguru.com/table-of-contents/)
