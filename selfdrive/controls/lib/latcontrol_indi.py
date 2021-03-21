import math
import numpy as np

from cereal import log
from common.realtime import DT_CTRL
from common.numpy_fast import clip, interp
from common.op_params import opParams
from selfdrive.car.toyota.values import SteerLimitParams
from selfdrive.car import apply_toyota_steer_torque_limits
from selfdrive.controls.lib.drive_helpers import get_steer_max


class LatControlINDI():
  def __init__(self, CP, OP=None):
    self.angle_steers_des = 0.

    A = np.array([[1.0, DT_CTRL, 0.0],
                  [0.0, 1.0, DT_CTRL],
                  [0.0, 0.0, 1.0]])
    C = np.array([[1.0, 0.0, 0.0],
                  [0.0, 1.0, 0.0]])

    # Q = np.matrix([[1e-2, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 10.0]])
    # R = np.matrix([[1e-2, 0.0], [0.0, 1e3]])

    # (x, l, K) = control.dare(np.transpose(A), np.transpose(C), Q, R)
    # K = np.transpose(K)
    K = np.array([[7.30262179e-01, 2.07003658e-04],
                  [7.29394177e+00, 1.39159419e-02],
                  [1.71022442e+01, 3.38495381e-02]])

    self.K = K
    self.A_K = A - np.dot(K, C)
    self.x = np.array([[0.], [0.], [0.]])

    self.enforce_rate_limit = CP.carName == "toyota"

    if OP is None:
      OP = opParams()
    self.op_params = OP

    self.sat_count_rate = 1.0 * DT_CTRL
    self.reset()

  def reset(self):
    self.delayed_output = 0.
    self.output_steer = 0.
    self.sat_count = 0.0

  def _check_saturation(self, control, check_saturation, limit):
    saturated = abs(control) == limit

    if saturated and check_saturation:
      self.sat_count += self.sat_count_rate
    else:
      self.sat_count -= self.sat_count_rate

    self.sat_count = clip(self.sat_count, 0.0, 1.0)

    return self.sat_count > self.sat_limit

  def update(self, active, CS, CP, path_plan):
    if self.op_params.get('enable_indi_live'):
      self.sat_limit = self.op_params.get('steer_limit_timer')

      act_bp = self.op_params.get('indi_actuator_effectiveness_bp')
      act_v = self.op_params.get('indi_actuator_effectiveness_v')
      outer_bp = self.op_params.get('indi_outer_gain_bp')
      outer_v = self.op_params.get('indi_outer_gain_v')
      inner_bp = self.op_params.get('indi_inner_gain_bp')
      inner_v = self.op_params.get('indi_inner_gain_v')
      time_bp = self.op_params.get('indi_time_constant_bp')
      time_v = self.op_params.get('indi_time_constant_v')
    elif CP.lateralTuning.which() == 'indi':
      act_bp = CP.lateralTuning.indi.actuatorEffectivenessBP
      act_v = CP.lateralTuning.indi.actuatorEffectivenessV
      outer_bp = CP.lateralTuning.indi.outerLoopGainBP
      outer_v = CP.lateralTuning.indi.outerLoopGainV
      inner_bp = CP.lateralTuning.indi.innerLoopGainBP
      inner_v = CP.lateralTuning.indi.innerLoopGainV
      time_bp = CP.lateralTuning.indi.timeConstantBP
      time_v = CP.lateralTuning.indi.timeConstantV

      self.sat_limit = CP.steerLimitTimer

    self.G = interp(CS.vEgo, act_bp, act_v)
    self.outer_loop_gain = interp(CS.vEgo, outer_bp, outer_v)
    self.inner_loop_gain = interp(CS.vEgo, inner_bp, inner_v)
    self.RC = interp(CS.vEgo, time_bp, time_v)
    self.alpha = 1. - DT_CTRL / (self.RC + DT_CTRL)

    # Update Kalman filter
    y = np.array([[math.radians(CS.steeringAngle)], [math.radians(CS.steeringRate)]])
    self.x = np.dot(self.A_K, self.x) + np.dot(self.K, y)

    indi_log = log.ControlsState.LateralINDIState.new_message()
    indi_log.steerAngle = math.degrees(self.x[0])
    indi_log.steerRate = math.degrees(self.x[1])
    indi_log.steerAccel = math.degrees(self.x[2])

    if CS.vEgo < 0.3 or not active:
      indi_log.active = False
      self.output_steer = 0.0
      self.delayed_output = 0.0
    else:
      self.angle_steers_des = path_plan.angleSteers
      self.rate_steers_des = path_plan.rateSteers

      steers_des = math.radians(self.angle_steers_des)
      rate_des = math.radians(self.rate_steers_des)

      # Expected actuator value
      self.delayed_output = self.delayed_output * self.alpha + self.output_steer * (1. - self.alpha)

      # Compute acceleration error
      rate_sp = self.outer_loop_gain * (steers_des - self.x[0]) + rate_des
      accel_sp = self.inner_loop_gain * (rate_sp - self.x[1])
      accel_error = accel_sp - self.x[2]

      # Compute change in actuator
      g_inv = 1. / self.G
      delta_u = g_inv * accel_error

      # If steering pressed, only allow wind down
      if CS.steeringPressed and (delta_u * self.output_steer > 0):
        delta_u = 0

      # Enforce rate limit
      if self.enforce_rate_limit:
        steer_max = float(SteerLimitParams.STEER_MAX)
        new_output_steer_cmd = steer_max * (self.delayed_output + delta_u)
        prev_output_steer_cmd = steer_max * self.output_steer
        new_output_steer_cmd = apply_toyota_steer_torque_limits(new_output_steer_cmd, prev_output_steer_cmd, prev_output_steer_cmd, SteerLimitParams)
        self.output_steer = new_output_steer_cmd / steer_max
      else:
        self.output_steer = self.delayed_output + delta_u

      steers_max = get_steer_max(CP, CS.vEgo)
      self.output_steer = clip(self.output_steer, -steers_max, steers_max)

      indi_log.active = True
      indi_log.rateSetPoint = float(rate_sp)
      indi_log.accelSetPoint = float(accel_sp)
      indi_log.accelError = float(accel_error)
      indi_log.delayedOutput = float(self.delayed_output)
      indi_log.delta = float(delta_u)
      indi_log.output = float(self.output_steer)

      check_saturation = (CS.vEgo > 10.) and not CS.steeringRateLimited and not CS.steeringPressed
      indi_log.saturated = self._check_saturation(self.output_steer, check_saturation, steers_max)

    return float(self.output_steer), float(self.angle_steers_des), indi_log
