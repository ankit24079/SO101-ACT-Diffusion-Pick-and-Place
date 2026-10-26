"""Torque-off voltage/position monitor for both grippers. No motor writes."""
import importlib.metadata
import argparse
import json
import select
import signal
import sys
import time
from pathlib import Path

from lerobot.motors import Motor, MotorNormMode
from lerobot.motors.feetech import FeetechMotorsBus

NAMES = ('shoulder_pan', 'shoulder_lift', 'elbow_flex', 'wrist_flex', 'wrist_roll', 'gripper')


class ReadOnlyBus(FeetechMotorsBus):
    def write(self, *args, **kwargs):
        raise RuntimeError('Motor writes forbidden during voltage monitoring')

    def _write(self, *args, **kwargs):
        raise RuntimeError('Motor writes forbidden during voltage monitoring')

    def sync_write(self, *args, **kwargs):
        raise RuntimeError('Motor writes forbidden during voltage monitoring')


def read(bus, role, register, name='gripper'):
    try:
        return bus.read(register, name, normalize=False)
    except Exception as error:
        raise RuntimeError(f'{role}/{name}/{register}: {error}') from error


def check_torque(bus, role):
    for name in NAMES:
        if read(bus, role, 'Torque_Enable', name) != 0:
            raise RuntimeError(f'{role}/{name}: torque not OFF. Stop manual handling; no writes issued.')


def interrupted(signum, frame):
    raise KeyboardInterrupt


def main(manual_arm='leader'):
    if importlib.metadata.version('lerobot') != '0.6.1':
        raise RuntimeError('Expected LeRobot 0.6.1')
    buses = {}
    report = {'status': 'started', 'powered': False, 'manual_arm': manual_arm, 'samples': [], 'limits_raw': {}, 'note': 'Torque-off manual gripper diagnostic, not a powered grasp or supply certification.'}
    out = Path('/workspace/outputs/gripper-voltage') / (str(time.time_ns())+'.json')
    out.parent.mkdir(parents=True,exist_ok=True)
    try:
        for role in ('leader', 'follower'):
            bus = ReadOnlyBus(f'/dev/so101-{role}', {name:Motor(i,'sts3215',MotorNormMode.RANGE_0_100) for i,name in enumerate(NAMES,1)})
            buses[role] = bus
            bus.connect(handshake=False)
            for name in NAMES:
                if bus.ping(name,raise_on_error=True) != bus.model_number_table['sts3215']:
                    raise RuntimeError(f'{role}/{name}: unexpected motor model')
            check_torque(bus,role)
            report['limits_raw'][role] = {'min':read(bus,role,'Min_Voltage_Limit'),'max':read(bus,role,'Max_Voltage_Limit')}
        print('Both arms report all torque OFF. No torque or calibration writes will be sent.',flush=True)
        print('Support the arms; keep fingers clear of jaws/pinch points; never force resistance.',flush=True)
        other = 'follower' if manual_arm == 'leader' else 'leader'
        input(f'Press ENTER to begin, then gently open/close ONLY the {manual_arm} gripper by hand. Leave {other} still: ')
        print('Monitoring BOTH grippers. Press ENTER when done. A register fault stops and preserves the report.',flush=True)
        start=time.monotonic()
        while True:
            if select.select([sys.stdin],[],[],0)[0]:
                sys.stdin.readline()
                report['status']='operator_finished'
                break
            row={'seconds':round(time.monotonic()-start,3)}
            report['samples'].append(row)
            for role,bus in buses.items():
                check_torque(bus,role)
                voltage=read(bus,role,'Present_Voltage')
                row[role]={'voltage_raw':voltage}
                limits=report['limits_raw'][role]
                if not limits['min'] <= voltage <= limits['max']:
                    raise RuntimeError(f'{role}/gripper: voltage register {voltage} outside {limits}')
                row[role]['position_raw']=read(bus,role,'Present_Position')
            print(json.dumps(row),flush=True)
            time.sleep(.1)
    except BaseException as error:
        report['status']='interrupted' if isinstance(error,KeyboardInterrupt) else 'error'
        report['error']=str(error)
        raise
    finally:
        for bus in buses.values():
            bus.port_handler.closePort()
        out.write_text(json.dumps(report,indent=2)+'\n')
        print(f'Voltage diagnostic saved: {out}. No motor settings changed.',flush=True)


if __name__=='__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--manual-arm', choices=('leader', 'follower'), default='leader')
    args = parser.parse_args()
    signal.signal(signal.SIGTERM,interrupted)
    main(args.manual_arm)
