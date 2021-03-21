#!/usr/bin/env python3.7
#import subprocess
from cereal import car
from common.params import Params
from common.realtime import sec_since_boot
import os
#import time
#from math import floor
params = Params()
from common.travis_checker import travis
#from common.dp_conf import init_params_vals

if travis:
  PARAM_PATH = str(os.environ.get('HOME')) + "/.comma/params/d/"
else:
  PARAM_PATH = "/data/params/d/"
LAST_MODIFIED = str(PARAM_PATH) + "dp_last_modified"
#if not os.path.exists(LAST_MODIFIED):
#  os.makedirs(str(os.environ.get('HOME')) + "/.comma/params/d/", exist_ok=True)
#  print("dp_last_modified is " + str(floor(time.time())))
#  params.put('dp_last_modified',str(floor(time.time())))
#  init_params_vals(params)

#def is_online():
  #try:
    #return not subprocess.call(["ping", "-W", "4", "-c", "1", "117.28.245.92"])
  #except ProcessLookupError:
    #return False

def common_controller_ctrl(enabled, dragonconf, blinker_on, steer_req, v_ego):
  if enabled:
    if (dragonconf.dpSteeringOnSignal and blinker_on) or not dragonconf.dpLatCtrl:
      steer_req = 0 if isinstance(steer_req, int) else False
  return steer_req

def common_interface_atl(ret, atl):
  # dp
  enable_acc = ret.cruiseState.enabled
  if atl and ret.cruiseState.available:
    enable_acc = True
    if ret.gearShifter in [car.CarState.GearShifter.reverse, car.CarState.GearShifter.park]:
      enable_acc = False
    if ret.seatbeltUnlatched or ret.doorOpen:
      enable_acc = False
  return enable_acc

def common_interface_get_params_lqr(ret):
  if params.get('dp_lqr') == b'1':
    ret.lateralTuning.init('lqr')
    ret.lateralTuning.lqr.scale = 1500.0
    ret.lateralTuning.lqr.ki = 0.05

    ret.lateralTuning.lqr.a = [0., 1., -0.22619643, 1.21822268]
    ret.lateralTuning.lqr.b = [-1.92006585e-04, 3.95603032e-05]
    ret.lateralTuning.lqr.c = [1., 0.]
    ret.lateralTuning.lqr.k = [-110.73572306, 451.22718255]
    ret.lateralTuning.lqr.l = [0.3233671, 0.3185757]
    ret.lateralTuning.lqr.dcGain = 0.002237852961363602
  return ret


def get_last_modified(delay, old_check, old_modified):
  new_check = sec_since_boot()
  if old_check is None or new_check - old_check >= delay:
    return new_check, os.stat(LAST_MODIFIED).st_mtime
  else:
    return old_check, old_modified

def param_get_if_updated(param, type_of, old_val, old_modified):
  try:
    modified = os.stat(PARAM_PATH + param).st_mtime
  except OSError:
    return old_val, old_modified
  if old_modified != modified:
    new_val = param_get(param, type_of, old_val)
    new_modified = modified
  else:
    new_val = old_val
    new_modified = old_modified
  return new_val, new_modified

def param_get(param_name, type_of, default):
  try:
    val = params.get(param_name, encoding='utf8').rstrip('\x00')
    if type_of == 'bool':
      val = val == '1'
    elif type_of == 'int':
      val = int(val)
    elif type_of == 'float':
      val = float(val)
  except (TypeError, ValueError):
    val = default
  return val
