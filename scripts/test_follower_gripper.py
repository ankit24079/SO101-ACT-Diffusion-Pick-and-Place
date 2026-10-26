"""Explicitly approved follower-gripper-only test; no leader or arm movement."""
import dataclasses
import importlib.metadata
import json
import signal
import select
import sys
import time
from pathlib import Path

from lerobot.motors import Motor, MotorNormMode
from lerobot.motors.feetech import FeetechMotorsBus

NAMES = ('shoulder_pan', 'shoulder_lift', 'elbow_flex', 'wrist_flex', 'wrist_roll', 'gripper')


def stop(signum, frame):
    raise KeyboardInterrupt


def main():
    if importlib.metadata.version('lerobot') != '0.6.1':
        raise RuntimeError('Expected LeRobot 0.6.1')
    expected = json.loads(Path('/calibration/robots/so101_follower/cup_follower.json').read_text())
    if expected['gripper'] != {'id': 6, 'drive_mode': 0, 'homing_offset': 860, 'range_min': 1031, 'range_max': 2496}:
        raise RuntimeError('Local calibration differs from approved values')
    bus = FeetechMotorsBus('/dev/so101-follower', {n: Motor(i, 'sts3215', MotorNormMode.RANGE_0_100) for i,n in enumerate(NAMES,1)})
    attempted = False
    report = {'status': 'started', 'samples': [], 'torque_off_verified': False}
    directory = Path('/workspace/outputs/gripper-powered-test')
    directory.mkdir(parents=True,exist_ok=True)
    path = directory / (str(time.time_ns())+'.json')
    try:
        bus.connect(handshake=False)
        for name in NAMES:
            if bus.ping(name,raise_on_error=True) != bus.model_number_table['sts3215']:
                raise RuntimeError(f'Unexpected model: {name}')
            if bus.read('Torque_Enable',name,normalize=False) != 0:
                raise RuntimeError(f'{name}: torque must already be off')
        actual = {n:dataclasses.asdict(v) for n,v in bus.read_calibration().items()}
        if actual != expected:
            raise RuntimeError('Motor calibration mismatch. Restore approved limits first; no automatic writes.')
        if bus.read('Operating_Mode','gripper',normalize=False) != 0 or bus.read('Phase','gripper',normalize=False) & 0x10:
            raise RuntimeError('Unexpected gripper mode; no automatic configuration')
        low = bus.read('Min_Voltage_Limit','gripper',normalize=False)
        high = bus.read('Max_Voltage_Limit','gripper',normalize=False)
        def sample():
            voltage = bus.read('Present_Voltage','gripper',normalize=False)
            position = bus.read('Present_Position','gripper',normalize=False)
            if not low <= voltage <= high:
                raise RuntimeError(f'Voltage register {voltage} outside {low}..{high}')
            if not 1023 <= position <= 2504:
                raise RuntimeError(f'Position outside approved range: {position}')
            report['samples'].append({'monotonic_seconds':time.monotonic(),'position':position,'voltage_raw':voltage})
            return position
        sample()
        print('Only follower gripper ID 6 will be powered. Other joints remain unpowered.',flush=True)
        print('Remove objects; secure/support the arm; keep hands outside jaws. Power cutoff must be accessible.',flush=True)
        if input('Type CLEAR TO MOVE to test a small opening and closing: ') != 'CLEAR TO MOVE':
            raise RuntimeError('Movement not confirmed')
        for name in NAMES:
            if bus.read('Torque_Enable',name,normalize=False) != 0:
                raise RuntimeError('Torque state changed; stop')
        position = sample()
        bus.write('Goal_Position','gripper',min(2496,max(1031,position)),normalize=False)
        attempted = True
        bus.write('Torque_Enable','gripper',1,normalize=False)
        last = min(2496,max(1031,position))
        # Interior targets avoid driving into the measured mechanical endpoints.
        for target in (round(1031+.25*(2496-1031)),round(1031+.10*(2496-1031))):
            print(f'Moving gently toward raw position {target}...',flush=True)
            while abs(last-target)>1:
                tick=time.monotonic();position=sample()
                if abs(position-last)>round(.05*(2496-1031)):
                    raise RuntimeError(f'Gripper tracking error: goal {last}, observed {position}')
                last += max(-7,min(7,target-last))
                bus.write('Goal_Position','gripper',int(last),normalize=False)
                time.sleep(max(0,.1-(time.monotonic()-tick)))
            sample()
            print('Inspect without touching the powered gripper. Press ENTER to continue; Ctrl+C stops:',flush=True)
            while not select.select([sys.stdin],[],[],.1)[0]:
                sample()
            sys.stdin.readline()
        report['status']='complete'
    except BaseException as error:
        report['status']='interrupted' if isinstance(error,KeyboardInterrupt) else 'error'
        report['error']=str(error)
        raise
    finally:
        if attempted:
            try:
                bus.write('Torque_Enable','gripper',0,normalize=False)
                report['torque_off_verified']=bus.read('Torque_Enable','gripper',normalize=False)==0
                if not report['torque_off_verified']:
                    print('CUT FOLLOWER MOTOR POWER: torque remains enabled',flush=True)
                else:
                    print('Follower gripper torque OFF verified.',flush=True)
            except Exception as error:
                print(f'CUT FOLLOWER MOTOR POWER: torque shutdown/readback failed: {error}',flush=True)
        bus.port_handler.closePort()
        path.write_text(json.dumps(report,indent=2)+'\n')
        print(f'Gripper test report: {path}',flush=True)


if __name__=='__main__':
    signal.signal(signal.SIGTERM,stop)
    main()
