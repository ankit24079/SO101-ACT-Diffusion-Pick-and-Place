"""Supported-arm torque release only: never enables torque or writes goals."""
import json
import time
from pathlib import Path

from lerobot.motors import Motor, MotorNormMode
from lerobot.motors.feetech import FeetechMotorsBus

NAMES = ('shoulder_pan', 'shoulder_lift', 'elbow_flex', 'wrist_flex', 'wrist_roll', 'gripper')


def main():
    bus = FeetechMotorsBus('/dev/so101-follower', {
        name: Motor(i, 'sts3215', MotorNormMode.RANGE_0_100)
        for i, name in enumerate(NAMES, 1)})
    out = Path('/workspace/outputs/torque-release')
    out.mkdir(parents=True, exist_ok=True)
    report = {'torque_enable_commands': False, 'goal_commands': False, 'errors': [], 'verified_off': False}
    try:
        bus.connect(handshake=False)
        for name in NAMES:
            if bus.ping(name, raise_on_error=True) != bus.model_number_table['sts3215']:
                raise RuntimeError(f'Unexpected model for {name}; no writes issued')
        print('Support the follower so it cannot fall when torque is removed. No movement targets will be sent.', flush=True)
        if input('Type RELEASE TORQUE when supported: ') != 'RELEASE TORQUE':
            raise RuntimeError('Release not confirmed; no writes issued')
        for name in NAMES:
            try:
                bus.disable_torque(name, num_retry=2)
            except Exception as error:
                report['errors'].append(f'{name}: {error}')
        states = {}
        for name in NAMES:
            try:
                states[name] = bus.read('Torque_Enable', name, normalize=False, num_retry=2)
            except Exception as error:
                states[name] = None
                report['errors'].append(f'{name} readback: {error}')
        report['torque_enable_readback'] = states
        report['verified_off'] = all(v == 0 for v in states.values())
        if not report['verified_off']:
            raise RuntimeError('POWER OFF FOLLOWER: torque OFF could not be verified')
        print('All six follower motors: torque OFF verified. You can retry the official recording command.', flush=True)
    finally:
        bus.port_handler.closePort()
        path = out/(str(time.time_ns())+'.json')
        path.write_text(json.dumps(report, indent=2)+'\n')
        print(f'Torque-release report: {path}', flush=True)


if __name__ == '__main__':
    main()
