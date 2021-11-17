[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](
https://github.com/custom-components/hacs)

# HASmartThermostat
## Smart Thermostat with PID controller for Home Assistant
Create a virtual thermostat with accurate and reactive temperature control through PID controller.
[Principle of the PID controller.](https://en.wikipedia.org/wiki/PID_controller) 
Any heater or air conditioner unit with ON/OFF switch or pilot wire can be controlled using a pulse width modulation 
that depends on the temperature error and its variation over time.

![](https://github.com/ScratMan/HASmartThermostat/blob/master/climate_chart.png?raw=true)

## Installation:
I recommend using HACS for easier installation.

### Install using HACS:
Go to HACS, select Integrations, click the three dots menu and select 
"Custom repositories". Add the path to the Github repository in the first field, select Integration as category and
click Add. Once back in integrations panel, click the Install button on the Smart Thermostat PID card to install.
Set up the smart thermostat and have fun.

### Manual installation:
1. Go to <conf-dir> default /homeassistant/.homeassistant/ (it's where your configuration.yaml is)
2. Create <conf-dir>/custom_components/ directory if it does not already exist
3. Copy the smart_thermostat folder into <conf-dir>/custom_components/
4. Set up the smart_thermostat and have fun

## Configuration:
The smart thermostat can be added to Home Assistant after installation by adding a climate section to your
configuration.yaml file.

### Configuration example:
#### configuration.yaml
```
climate:
  - platform: smart_thermostat
    name: Smart Thermostat Example
    heater: switch.on_off_heater
    target_sensor: sensor.ambient_temperature
    min_temp: 7
    max_temp: 28
    ac_mode: False
    target_temp: 19
    keep_alive:
      seconds: 60
    away_temp: 14
    kp : 75
    ki : 0.001
    kd : 70000
    pwm : 00:15:00
```

## Usage:
The target sensor measures the ambient temperature while the heater switch controls an ON/OFF heating system.
The PID controller computes the amount of time the heater should remain ON over the PWM period to reach the temperature 
set point, in example with PWM set to 15 minutes, if output is 100% the heater will be kept on for the next 15 minutes 
PWM period. If PID output is 33%, the heater will be switched ON for 5 minutes only.

By default, the PID controller will be called each time the target sensor is updated. When using main powered sensor 
with high sampling rate, the _sampling_period_ parameter should be used to slow down the PID controller refresh rate.

By adjusting the Kp, Ki and Kd gains, you can tune the system response to your liking. You can find many tutorials for 
guidance on the web. Here are a few useful links:
* [PID Control made easy](https://www.eurotherm.com/temperature-control/pid-control-made-easy/)
* [Practical PID Process Dynamics with Proportional Pressure Controllers](
https://clippard.com/cms/wiki/practical-pid-process-dynamics-proportional-pressure-controllers)
* [PID Tuner](https://pidtuner.com/)
* [PID development blog from Brett Beauregard](http://brettbeauregard.com/blog/category/pid/)
* [PID controller explained](https://controlguru.com/table-of-contents/)

To make it quick and simple:
* Kp gain adjusts the proportional part of the error compensation. Higher values means 
stronger reaction to error. Increase the value for faster rise time.
* Ki gain adjusts the integral part. Integral compensates the residual error when temperature settles in a cumulative 
way. The longer the temperature remains below the set point, the higher the integral compensation will be. If your 
system settles below the set point, increase the Ki value. If it overshoots the set point, decrease the Ki value.
* Kd gain adjusts the derivative part of the compensation. Derivative compensates the inertia of the system. If the 
sensor temperature increases quickly between two samples, the PID will decrease the PWM level accordingly to limit the 
overshoot.

![](https://upload.wikimedia.org/wikipedia/commons/4/43/PID_en.svg)

PID output value is the weighted sum of the control terms:\
`error = set_point - current_temperature`\
`di = ` temperature change between last two samples\
`dt = ` time elapsed between last two samples\
`P = Kp * error`\
`I = last_I + (Ki * error * dt)`\
`D = -(Kd * di) / dt`\
`output = P + I + D`\
Output is then limited to 0% to 100% range to control the PWM.

### Autotune (not tested, not guaranteed to work):
You can use the autotune feature to find some working PID parameters.
Add the autotune: parameter with the desired tuning rule, and optionally set the noiseband and lookback duration if the 
default 2 hours doesn't match your HVAC system bandwidth.\
Restart Home Assistant to start the thermostat in autotune mode, make a step on the set point (positive for heating, 
negative for cooling) and wait for the autotune to finish by checking the _autotune_status_ attribute for success.\
The Kp, Ki and Kd gains will be shown in the attributes and shown in the log like this: **"Set Kp, Ki, Kd. Smart 
thermostat now runs on PID Controller."** followed by the three computed gains Kp, Ki and Kd respectively.

**Warning**: I'couldn't yet save the settings to the configuration.yaml file. The PID parameters set by the autotune 
won't be stored and the process restarts everytime Home Assistant is restarted.\ 
To save the parameters read attributes or log after autotune has finished, manually copy the values in the 
corresponding fields and remove the autotune parameter in the YAML configuration file before restarting Home Assistant.

## Parameters:
* **name** (Required): Name of the thermostat.
* **heater** (Required): entity_id for heater switch, must be a toggle device. Becomes air conditioning switch when 
ac_mode is set to True.
* **target_sensor** (Required): entity_id for a temperature sensor, target_sensor.state must be temperature.
* **keep_alive** (Required): sets update interval for the PWM pulse width. If interval is too big, the PWM granularity 
will be reduced, leading to lower accuracy of temperature control, can be float in seconds, or time hh:mm:ss.
* **kp** (Recommended): Set PID parameter, proportional (p) control value (default 100).
* **ki** (Recommended): Set PID parameter, integral (i) control value (default 0).
* **kd** (Recommended): Set PID parameter, derivative (d) control value (default 0). 
* **pwm** (Optional): Set period of the pulse width modulation. If too long, the response time of the thermostat will 
be too slow, leading to lower accuracy of temperature control. Can be float in seconds or time hh:mm:ss (default 15mn).
* **sampling_period** (Optional): interval between two computation of the PID. If set to 0, PID computation is called 
each time the temperature sensor sends an update. Can be float in seconds or time hh:mm:ss (default 0) 
* **target_temp_step** (Optional): the adjustment step of target temperature (valid are 0.1, 0.5 and 1.0, default 0.5 for Celsius 
and 1.0 for Fahrenheit)
* **precision** (Optional): the displayed temperature precision (valid are 0.1, 0.5 and 1.0, default 0.1 for Celsius 
and 1.0 for Fahrenheit)
* **min_temp** (Optional): Set minimum set point available (default: 7).
* **max_temp** (Optional): Set maximum set point available (default: 35).
* **target_temp** (Optional): Set initial target temperature. If not set target temperature will be set to null on 
startup.
* **ac_mode** (Optional): Set the switch specified in the heater option to be treated as a cooling device instead of a 
heating device. Should be a boolean (default: false).
* **away_temp** (Optional): Set the temperature used by the "Away" preset. If this is not specified, away_mode feature will not be available.
* **eco_temp** (Optional): Set the temperature used by the "Eco" preset. If this is not specified, eco feature will not be available.
* **boost_temp** (Optional): Set the temperature used by the "Boost" preset. If this is not specified, boost feature will not be available.
* **comfort_temp** (Optional): Set the temperature used by the "Comfort" preset. If this is not specified, comfort feature will not be available.
* **home_temp** (Optional): Set the temperature used by the "Home" preset. If this is not specified, home feature will not be available.
* **sleep_temp** (Optional): Set the temperature used by the "Sleep" preset. If this is not specified, sleep feature will not be available.
* **activity_temp** (Optional): Set the temperature used by the "Activity" preset. If this is not specified, activity feature will not be available.
* **autotune** (Optional): Set the name of the selected rule for autotune settings (ie "ziegler-nichols"). If it's not set, autotune is disabled. The following 
tuning_rules are available:

ruler | Kp_divisor, Ki_divisor, Kd_divisor
------------ | -------------
"ziegler-nichols" | 34, 40, 160
"tyreus-luyben" | 44,  9, 126
"ciancone-marlin" | 66, 88, 162
"pessen-integral" | 28, 50, 133
"some-overshoot" | 60, 40,  60
"no-overshoot" | 100, 40,  60
"brewing" | 2.5, 6, 380

* **noiseband** (Optional): set noiseband for autotune (float): Determines by how much the input value 
must overshoot/undershoot the set point before the state changes (default : 0.5).
* **lookback** (Optional): duration of the signal analysis for the autotune, need to have 5 cycles (temperature crossing
 the set point) included in the analysis period, can be float in seconds, or time hh:mm:ss (default 2 hours).


### Credits
This code is a fork from Smart Thermostat PID project:
[https://github.com/aendle/custom_components](https://github.com/aendle/custom_components) \
The python PID module with Autotune is based on pid-autotune:
[https://github.com/hirschmann/pid-autotune](https://github.com/hirschmann/pid-autotune)

