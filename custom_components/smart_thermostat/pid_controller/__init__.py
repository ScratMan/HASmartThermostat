import math
import logging
from time import time
from collections import deque, namedtuple

_LOGGER = logging.getLogger(__name__)


# Based on Arduino PID Library
# See https://github.com/br3ttb/Arduino-PID-Library
class PID:
    error: float

    def __init__(self, kp, ki, kd, out_min=float('-inf'), out_max=float('+inf'), sampling_period=0,
                 cold_tolerance=0.3, hot_tolerance=0.3):
        """A proportional-integral-derivative controller.
            :param kp: Proportional coefficient.
            :type kp: float
            :param ki: Integral coefficient.
            :type ki: float
            :param kd: Derivative coefficient.
            :type kd: float
            :param out_min: Lower output limit.
            :type out_min: float
            :param out_max: Upper output limit.
            :type out_max: float
            :param sampling_period: time period between two PID calculations in seconds
            :type sampling_period: float
            :param cold_tolerance: time period between two PID calculations in seconds
            :type cold_tolerance: float
            :param hot_tolerance: time period between two PID calculations in seconds
            :type hot_tolerance: float
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
        self._out_min = out_min
        self._out_max = out_max
        self._integral = 0.0
        self._last_set_point = 0
        self._set_point = 0
        self._input = None
        self._input_time = None
        self._last_input = None
        self._last_input_time = None
        self.error = 0
        self._input_diff = 0
        self.dt = 0
        self._last_output = 0
        self.output = 0
        self.P = 0
        self.I = 0
        self.D = 0
        self._mode = 'AUTO'
        self.sampling_period = sampling_period
        self._cold_tolerance = cold_tolerance
        self._hot_tolerance = hot_tolerance

    @property
    def mode(self):
        return self._mode

    @mode.setter
    def mode(self, mode):
        assert mode.upper() in ['AUTO', 'OFF']
        self._mode = mode.upper()

    @property
    def integral(self):
        return self._integral

    @integral.setter
    def integral(self, i):
        assert isinstance(i, float), "Integral should be a float"
        self._integral = i
        self.I = i

    def set_pid_param(self, kp=None, ki=None, kd=None):
        """Set PID parameters."""
        if kp is not None and isinstance(kp, (int, float)):
            self._Kp = kp
        if ki is not None and isinstance(ki, (int, float)):
            self._Ki = ki
        if kd is not None and isinstance(kd, (int, float)):
            self._Kd = kd

    def clear_samples(self):
        """Clear the samples values and timestamp to restart PID from clean state after
        a switch off of the thermostat"""
        self._input = None
        self._input_time = None
        self._last_input = None
        self._last_input_time = None
        
    def calc(self, input_val, set_point, input_time=None, last_input_time=None):
        """Adjusts and holds the given setpoint.

        Args:
            input_val (float): The input value.
            set_point (float): The target value.
            input_time (float): The timestamp in seconds of the input value to compute dt
            last_input_time (float): The timestamp in seconds of the previous input value to
            compute dt

        Returns:
            A value between `out_min` and `out_max`.
        """
        if self.sampling_period != 0 and self._last_input_time is not None and \
                time() - self._input_time < self.sampling_period:
            return self.output, False  # If last sample is too young, keep last output value

        self._last_input = self._input
        if self.sampling_period == 0:
            self._last_input_time = last_input_time
        else:
            self._last_input_time = self._input_time
        self._last_output = self.output

        # Refresh with actual values
        self._input = input_val
        if self.sampling_period == 0:
            self._input_time = input_time
        else:
            self._input_time = time()
        self._last_set_point = self._set_point
        self._set_point = set_point

        if self.mode == 'OFF':  # If PID is off, simply switch between min and max output
            if input_val <= set_point - self._cold_tolerance:
                self.output = self._out_max
                _LOGGER.debug("PID is off and input lower than set point: heater ON")
                return self.output, True
            elif input_val >= set_point + self._hot_tolerance:
                self.output = self._out_min
                _LOGGER.debug("PID is off and input higher than set point: heater OFF")
                return self.output, True
            else:
                return self.output, False

        # Compute all the working error variables
        self.error = set_point - input_val
        if self._last_input is not None:
            self._input_diff = self._input - self._last_input
        else:
            self._input_diff = 0
        if self._last_input_time is not None:
            self.dt = self._input_time - self._last_input_time
        else:
            self.dt = 0

        # In order to prevent windup, only integrate if the process is not saturated and set point
        # is stable
        if self._out_min < self._last_output < self._out_max and \
                self._last_set_point == self._set_point:
            self._integral += self._Ki * self.error * self.dt
            self._integral = max(min(self._integral, self._out_max), self._out_min)

        self.P = self._Kp * self.error
        self.I = self._integral
        if self.dt != 0:
            self.D = -(self._Kd * self._input_diff) / self.dt
        else:
            self.D = 0.0

        # Compute PID Output
        output = self.P + self.I + self.D
        self.output = max(min(output, self._out_max), self._out_min)

        # Log some debug info
        _LOGGER.debug('P: %.2f', self.P)
        _LOGGER.debug('I: %.2f', self.I)
        _LOGGER.debug('D: %.2f', self.D)
        _LOGGER.debug('output: %.2f', self.output)

        return self.output, True


# Based on a fork of Arduino PID AutoTune Library
# See https://github.com/t0mpr1c3/Arduino-PID-AutoTune-Library
class PIDAutotune:
    """Determines viable parameters for a PID controller.

    Args:
        setpoint (float): The target value.
        out_step (float): The value by which the output will be
            increased/decreased when stepping up/down.
        sampletime (float): The interval between run() calls.
        loockback (float): The reference period for local minima/maxima.
        out_min (float): Lower output limit.
        out_max (float): Upper output limit.
        noiseband (float): Determines by how much the input value must
            overshoot/undershoot the setpoint before the state changes.
        time (function): A function which returns the current time in seconds.
    """
    PIDParams = namedtuple('PIDParams', ['Kp', 'Ki', 'Kd'])

    PEAK_AMPLITUDE_TOLERANCE = 0.05
    STATE_OFF = 'off'
    STATE_RELAY_STEP_UP = 'relay step up'
    STATE_RELAY_STEP_DOWN = 'relay step down'
    STATE_SUCCEEDED = 'succeeded'
    STATE_FAILED = 'failed'

    _tuning_rules = {
        # rule: [Kp_divisor, Ki_divisor, Kd_divisor]
        "ziegler-nichols": [34, 40, 160],
        "tyreus-luyben": [44,  9, 126],
        "ciancone-marlin": [66, 88, 162],
        "pessen-integral": [28, 50, 133],
        "some-overshoot": [60, 40,  60],
        "no-overshoot": [100, 40,  60],
        "brewing": [2.5, 6, 380]
    }

    def __init__(self, out_step=10, lookback=60,
                 out_min=float('-inf'), out_max=float('inf'), noiseband=0.5, time_func=time):
        if out_step < 1:
            raise ValueError('out_step must be greater or equal to 1')
        if out_min >= out_max:
            raise ValueError('out_min must be less than out_max')

        self._time = time_func
        self._sampletime = None
        self._last_sample_time = None
        self._sample_time_calc = []
        self._lookback = lookback
        self._inputs = deque(maxlen=10)
        self._inputs_timestamps = deque(maxlen=10)
        self._setpoint = None
        self._outputstep = out_step
        self._noiseband = noiseband
        self._out_min = out_min
        self._out_max = out_max
        self._state = PIDAutotune.STATE_OFF
        self._peak_timestamps = deque(maxlen=5)
        self._peaks = deque(maxlen=5)
        self._output = 0
        self._last_run_timestamp = 0
        self._peak_type = 0
        self._peak_count = 0
        self._initial_output = 0
        self._induced_amplitude = 0
        self._Ku = 0
        self._Pu = 0

    @property
    def state(self):
        """Get the current state."""
        return self._state

    @property
    def output(self):
        """Get the last output value."""
        return self._output

    @property
    def tuning_rules(self):
        """Get a list of all available tuning rules."""
        return self._tuning_rules.keys()

    @property
    def set_point(self):
        """Get the reference set point"""
        return self._setpoint

    @property
    def sample_time(self):
        """Get the sample time considered"""
        return self._sampletime

    @property
    def peak_count(self):
        """Get the number of peaks found"""
        return self._peak_count

    @property
    def buffer_full(self):
        """Get the filling percentage of the buffer"""
        if self._inputs is None:
            return 0
        return len(self._inputs) / float(self._inputs.maxlen)

    @property
    def buffer_length(self):
        """Get the total length of buffer"""
        if self._inputs is None:
            return 0
        return self._inputs.maxlen

    def get_pid_parameters(self, tuning_rule='ziegler-nichols'):
        """Get PID parameters.

        Args:
            tuning_rule (str): Sets the rule which should be used to calculate
                the parameters.
        """
        divisors = self._tuning_rules[tuning_rule]
        kp = self._Ku / divisors[0]
        ki = kp / (self._Pu / divisors[1])
        kd = kp * (self._Pu / divisors[2])
        return PIDAutotune.PIDParams(kp, ki, kd)

    def run(self, input_val, set_point, now=None):
        """To autotune a system, this method must be called periodically.

        Args:
            input_val (float): The input value.
            set_point (float): The target value to be considered.

        Returns:
            `true` if tuning is finished, otherwise `false`.
        """
        if now is None:
            now = self._time()
        if self._sampletime is None:
            # sample time is not defined, use first 5 temperature samples to measure it.
            if self._last_sample_time is None:
                self._last_sample_time = now
                return False
            self._sample_time_calc.append(now - self._last_sample_time)
            self._last_sample_time = now
            if len(self._sample_time_calc) < self._inputs.maxlen:
                return False
            self._sampletime = sum(self._sample_time_calc[5::]) / len(self._sample_time_calc[5::])
            self._setpoint = set_point
            self._inputs = deque(maxlen=round(self._lookback / self._sampletime))
            self._inputs_timestamps = deque(maxlen=round(self._lookback / self._sampletime))

        if self._state in [PIDAutotune.STATE_OFF, PIDAutotune.STATE_SUCCEEDED,
                           PIDAutotune.STATE_FAILED]:
            self._initTuner(input_val, now)
        elif (now - self._last_run_timestamp) < self._sampletime - 0.90:  # keep a 10% margin
            return False

        # check input and change relay state if necessary
        if (self._state == PIDAutotune.STATE_RELAY_STEP_UP
                and input_val > self._setpoint + self._noiseband):
            self._state = PIDAutotune.STATE_RELAY_STEP_DOWN
            _LOGGER.debug('switched state: %s', self._state)
            _LOGGER.debug('input: %.1f', input_val)
        elif (self._state == PIDAutotune.STATE_RELAY_STEP_DOWN
                and input_val < self._setpoint - self._noiseband):
            self._state = PIDAutotune.STATE_RELAY_STEP_UP
            _LOGGER.debug('switched state: %s', self._state)
            _LOGGER.debug('input: %.1f', input_val)

        # set output
        if (self._state == PIDAutotune.STATE_RELAY_STEP_UP):
            self._output = self._initial_output + self._outputstep
        elif self._state == PIDAutotune.STATE_RELAY_STEP_DOWN:
            self._output = self._initial_output - self._outputstep

        # respect output limits
        self._output = min(self._output, self._out_max)
        self._output = max(self._output, self._out_min)

        # identify peaks
        is_max = True
        is_min = True

        for val in self._inputs:
            is_max = is_max and (input_val >= val)
            is_min = is_min and (input_val <= val)

        self._inputs.append(input_val)
        self._inputs_timestamps.append(now)
        self._last_run_timestamp = now

        # we don't want to trust the maxes or mins until the input array is full
        if len(self._inputs) < self._inputs.maxlen:
            return False

        return self.analysis()
        # increment peak count and record peak time for maxima and minima


    def _initTuner(self, inputValue, timestamp):
        self._peak_type = 0
        self._peak_count = 0
        self._output = 0
        self._initial_output = 0
        self._Ku = 0
        self._Pu = 0
        self._inputs.clear()
        self._peaks.clear()
        self._peak_timestamps.clear()
        # self._peak_timestamps.append(timestamp)
        self._state = PIDAutotune.STATE_RELAY_STEP_UP

    def analysis(self):
        for index in range(self._inputs.maxlen):
            input_val = self._inputs[index]
            now = self._inputs_timestamps[index]
            # identify peaks
            is_max = True
            is_min = True

            for val in self._inputs:
                is_max = is_max and (input_val >= val)
                is_min = is_min and (input_val <= val)

            # increment peak count and record peak time for maxima and minima
            inflection = False

            # peak types:
            # -1: minimum
            # +1: maximum
            if is_max:
                if self._peak_type == -1:
                    inflection = True
                self._peak_type = 1
            elif is_min:
                if self._peak_type == 1:
                    inflection = True
                self._peak_type = -1

            # update peak times and values
            if inflection:
                self._peak_count += 1
                self._peaks.append(input_val)
                self._peak_timestamps.append(now)
                _LOGGER.debug('found peak: %.1f', input_val)
                _LOGGER.debug('peak count: %i', self._peak_count)

            # check for convergence of induced oscillation
            # convergence of amplitude assessed on last 4 peaks (1.5 cycles)
            self._induced_amplitude = 0

            if inflection and (self._peak_count > 4):
                abs_max = self._peaks[-2]
                abs_min = self._peaks[-2]
                for i in range(0, len(self._peaks) - 2):
                    self._induced_amplitude += abs(self._peaks[i] - self._peaks[i+1])
                    abs_max = max(self._peaks[i], abs_max)
                    abs_min = min(self._peaks[i], abs_min)

                self._induced_amplitude /= 6.0

                # check convergence criterion for amplitude of induced oscillation
                amplitude_dev = ((0.5 * (abs_max - abs_min) - self._induced_amplitude)
                                 / self._induced_amplitude)

                _LOGGER.debug('amplitude: %.2f', self._induced_amplitude)
                _LOGGER.debug('amplitude deviation: %.2f', amplitude_dev)

                if amplitude_dev < PIDAutotune.PEAK_AMPLITUDE_TOLERANCE:
                    self._state = PIDAutotune.STATE_SUCCEEDED

            # if the autotune has not already converged
            # terminate after 10 cycles
            if self._peak_count >= 20:
                self._output = 0
                self._state = PIDAutotune.STATE_FAILED
                return True

            if self._state == PIDAutotune.STATE_SUCCEEDED:
                self._output = 0

                # calculate ultimate gain
                self._Ku = 4.0 * self._outputstep / (self._induced_amplitude * math.pi)

                # calculate ultimate period in seconds
                period1 = self._peak_timestamps[3] - self._peak_timestamps[1]
                period2 = self._peak_timestamps[4] - self._peak_timestamps[2]
                self._Pu = 0.5 * (period1 + period2)
                return True
            return False
