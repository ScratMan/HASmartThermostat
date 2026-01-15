import logging
import math
from time import time

_LOGGER = logging.getLogger(__name__)


# Based on Arduino PID Library
# See https://github.com/br3ttb/Arduino-PID-Library
class PID:
    error: float

    def __init__(self, kp, ki, kd, ke=0, out_min=float('-inf'), out_max=float('+inf'),
                 sampling_period=0, cold_tolerance=0.3, hot_tolerance=0.3, derivative_filter_alpha=0.15):
        """A proportional-integral-derivative controller.
            :param kp: Proportional coefficient.
            :type kp: float
            :param ki: Integral coefficient in units of %/(°C·hour).
            :type ki: float
            :param kd: Derivative coefficient in units of %/(°C/hour).
            :type kd: float
            :param ke: Outdoor temperature compensation coefficient.
            :type ke: float
            :param out_min: Lower output limit.
            :type out_min: float
            :param out_max: Upper output limit.
            :type out_max: float
            :param sampling_period: time period between two PID calculations in seconds
            :type sampling_period: float
            :param cold_tolerance: Temperature below setpoint to trigger heating when PID mode is OFF.
            :type cold_tolerance: float
            :param hot_tolerance: Temperature above setpoint to trigger cooling when PID mode is OFF.
            :type hot_tolerance: float
            :param derivative_filter_alpha: EMA filter alpha for derivative term (0.0-1.0).
                                           Lower values = more filtering. 1.0 = no filter.
            :type derivative_filter_alpha: float
        """
        if kp is None:
            raise ValueError('kp must be specified')
        if ki is None:
            raise ValueError('ki must be specified')
        if kd is None:
            raise ValueError('kd must be specified')
        if out_min >= out_max:
            raise ValueError('out_min must be less than out_max')

        self._Kp = kp
        self._Ki = ki
        self._Kd = kd
        self._Ke = ke
        self._out_min = out_min
        self._out_max = out_max
        self._proportional = 0.0
        self._integral = 0.0
        self._derivative = 0.0
        self._derivative_filtered = 0.0  # EMA-filtered derivative value
        self._derivative_filter_alpha = derivative_filter_alpha
        self._last_set_point = 0
        self._set_point = 0
        self._input = None
        self._input_time = None
        self._last_input = None
        self._last_input_time = None
        self._error = 0
        self._input_diff = 0
        self._dext = 0
        self._dt = 0
        self._last_output = 0
        self._output = 0
        self._proportional = 0
        self._derivative = 0
        self._external = 0
        self._mode = 'AUTO'
        self._sampling_period = sampling_period
        self._cold_tolerance = cold_tolerance
        self._hot_tolerance = hot_tolerance

    @property
    def mode(self):
        return self._mode

    @mode.setter
    def mode(self, mode):
        assert mode.upper() in ['AUTO', 'OFF']
        new_mode = mode.upper()
        # Clear samples when switching from OFF to AUTO to prevent stale data
        if self._mode == 'OFF' and new_mode == 'AUTO':
            self.clear_samples()
        self._mode = new_mode

    @property
    def out_max(self):
        return self._out_max

    @out_max.setter
    def out_max(self, out_max):
        self._out_max = out_max

    @property
    def out_min(self):
        return self._out_min

    @out_min.setter
    def out_min(self, out_min):
        self._out_min = out_min

    @property
    def sampling_period(self):
        return self._sampling_period

    @property
    def error(self):
        return self._error

    @property
    def proportional(self):
        return self._proportional

    @property
    def integral(self):
        return self._integral

    @integral.setter
    def integral(self, i):
        assert isinstance(i, float), "Integral should be a float"
        self._integral = i

    @property
    def derivative(self):
        return self._derivative

    @property
    def external(self):
        return self._external

    @property
    def dt(self):
        return self._dt

    def set_pid_param(self, kp=None, ki=None, kd=None, ke=None):
        """Set PID parameters."""
        if kp is not None and isinstance(kp, (int, float)):
            self._Kp = kp
        if ki is not None and isinstance(ki, (int, float)):
            self._Ki = ki
        if kd is not None and isinstance(kd, (int, float)):
            self._Kd = kd
        if ke is not None and isinstance(ke, (int, float)):
            self._Ke = ke

    def clear_samples(self):
        """Clear the samples values and timestamp to restart PID from clean state after
        a switch off of the thermostat"""
        self._input = None
        self._input_time = None
        self._last_input = None
        self._last_input_time = None
        self._derivative_filtered = 0.0
        
    def calc(self, input_val, set_point, input_time=None, last_input_time=None, ext_temp=None):
        """Adjusts and holds the given setpoint.

        Args:
            input_val (float): The input value.
            set_point (float): The target value.
            input_time (float): The timestamp in seconds of the input value to compute dt
            last_input_time (float): The timestamp in seconds of the previous input value to
            compute dt
            ext_temp (float): The outdoor temperature value.

        Returns:
            A value between `out_min` and `out_max`.
        """
        # Validate inputs for NaN and Inf values
        if math.isnan(input_val) or math.isinf(input_val):
            _LOGGER.warning("Invalid input_val received: %s. Returning cached output.", input_val)
            return self._output, False
        if math.isnan(set_point) or math.isinf(set_point):
            _LOGGER.warning("Invalid set_point received: %s. Returning cached output.", set_point)
            return self._output, False
        if ext_temp is not None and (math.isnan(ext_temp) or math.isinf(ext_temp)):
            _LOGGER.warning("Invalid ext_temp received: %s. Returning cached output.", ext_temp)
            return self._output, False

        if self._sampling_period != 0 and self._last_input_time is not None and \
                time() - self._last_input_time < self._sampling_period:
            return self._output, False  # If last sample is too young, keep last output value

        self._last_input = self._input
        if self._sampling_period == 0:
            self._last_input_time = last_input_time
        else:
            self._last_input_time = self._input_time
        self._last_output = self._output

        # Refresh with actual values
        self._input = input_val
        if self._sampling_period == 0:
            if input_time is None:
                _LOGGER.warning(
                    "PID controller in event-driven mode (sampling_period=0) but no "
                    "input_time provided. Using current time as fallback."
                )
                self._input_time = time()
            else:
                self._input_time = input_time
        else:
            self._input_time = time()
        self._last_set_point = self._set_point
        self._set_point = set_point

        if self.mode == 'OFF':  # If PID is off, simply switch between min and max output
            if input_val <= set_point - self._cold_tolerance:
                self._output = self._out_max
                _LOGGER.debug("PID is off and input lower than set point: heater ON")
                return self._output, True
            elif input_val >= set_point + self._hot_tolerance:
                self._output = self._out_min
                _LOGGER.debug("PID is off and input higher than set point: heater OFF")
                return self._output, True
            else:
                return self._output, False

        # Compute all the working error variables
        self._error = set_point - input_val
        if self._last_input is not None:
            self._input_diff = self._input - self._last_input
        else:
            self._input_diff = 0
        if self._last_input_time is not None:
            self._dt = self._input_time - self._last_input_time
        else:
            self._dt = 0
        if ext_temp is not None:
            self._dext = set_point - ext_temp
        else:
            self._dext = 0

        # Compensate losses due to external temperature
        self._external = self._Ke * self._dext

        # In order to prevent windup, only integrate if the process is not saturated and set point
        # is stable
        if self._out_min < self._last_output < self._out_max and \
                self._last_set_point == self._set_point:
            # Convert dt from seconds to hours for dimensional correctness
            # Ki has units of %/(°C·hour), so dt must be in hours
            dt_hours = self._dt / 3600.0
            self._integral += self._Ki * self._error * dt_hours
            # Take external temperature compensation into account for integral clamping
            self._integral = max(min(self._integral, self._out_max - self._external), self._out_min - self._external)
        if self._last_set_point != self._set_point:
            self._integral = 0  # Reset integral if set point has changed as system will need to converge to a new value

        self._proportional = self._Kp * self._error
        if self._dt != 0:
            # Convert dt to hours for dimensional correctness
            # Kd has units of %/(°C/hour), so dt must be in hours
            dt_hours = self._dt / 3600.0
            raw_derivative = -(self._Kd * self._input_diff) / dt_hours

            # Apply EMA filter to reduce sensor noise amplification
            # Formula: filtered = alpha * raw + (1 - alpha) * prev_filtered
            # alpha = 1.0 disables filter (no filtering)
            # alpha = 0.0 gives maximum filtering (derivative becomes constant)
            self._derivative_filtered = (
                self._derivative_filter_alpha * raw_derivative +
                (1.0 - self._derivative_filter_alpha) * self._derivative_filtered
            )
            self._derivative = self._derivative_filtered
        else:
            self._derivative = 0.0

        # Compute PID Output
        output = self._proportional + self._integral + self._derivative + self._external
        self._output = max(min(output, self._out_max), self._out_min)
        return self._output, True
