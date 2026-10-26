"""Approved one-time range correction: follower gripper only; never enables torque."""
import dataclasses
import importlib.metadata
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from lerobot.motors import Motor, MotorNormMode
from lerobot.motors.feetech import FeetechMotorsBus


def save(path, data):
    with path.open('x') as stream:
        json.dump(data, stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def check_torque(bus):
    values = {name: bus.read('Torque_Enable', name, normalize=False) for name in bus.motors}
    if any(value != 0 for value in values.values()):
        raise RuntimeError(f'STOP: all follower motors must already have torque OFF: {values}')
    return values


if __name__ == '__main__':
    if importlib.metadata.version('lerobot') != '0.6.1':
        raise RuntimeError('Expected LeRobot 0.6.1')
    names = ('shoulder_pan', 'shoulder_lift', 'elbow_flex', 'wrist_flex', 'wrist_roll', 'gripper')
    bus = FeetechMotorsBus('/dev/so101-follower', {
        name: Motor(i, 'sts3215', MotorNormMode.RANGE_0_100)
        for i, name in enumerate(names, 1)
    })
    directory = Path('/workspace/outputs/motor-inspection')
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    reference = json.loads((directory / '20261015T221030807968Z.json').read_text())['arms']['follower']['stored_calibration_registers']
    observed = json.loads((directory / 'gripper-range-20261015T225843950292Z.json').read_text())
    if observed['status'] != 'complete':
        raise RuntimeError('Expected completed manual range check')
    sweep = [sample['position'] for sample in observed['stages']['manual_sweep']]
    if (min(sweep), max(sweep)) != (1031, 2496):
        raise RuntimeError('Manual range report differs from approved limits')
    try:
        bus.connect(handshake=False)
        for name in names:
            if bus.ping(name, raise_on_error=True) != bus.model_number_table['sts3215']:
                raise RuntimeError(f'Unexpected motor model: {name}')
        torque = check_torque(bus)
        before = {name: dataclasses.asdict(cal) for name, cal in bus.read_calibration().items()}
        expected = json.loads(json.dumps(reference))
        expected['gripper']['range_min'] = 1031
        expected['gripper']['range_max'] = 2496
        if before == expected:
            print('Range already set; no writes needed.')
        else:
            if before != reference:
                raise RuntimeError('Calibration changed since inspection. Stop for review; no writes issued.')
            backup = directory / f'before-gripper-range-{stamp}.json'
            original_lock = bus.read('Lock', 'gripper', normalize=False)
            save(backup, {'follower_calibration': before, 'torque_enable': torque, 'gripper_lock': original_lock, 'planned_gripper_range': [1031, 2496]})
            print(f'Backup saved: {backup}', flush=True)
            print('Writing ONLY follower ID 6: Min_Position_Limit=1031, Max_Position_Limit=2496', flush=True)
            # Feetech EEPROM limits require unlocking, as in the official
            # torque helpers. Preserve the original lock state; never enable torque.
            try:
                check_torque(bus)
                bus.write('Lock', 'gripper', 0, normalize=False)
                check_torque(bus)
                bus.write('Min_Position_Limit', 'gripper', 1031, normalize=False)
                check_torque(bus)
                bus.write('Max_Position_Limit', 'gripper', 2496, normalize=False)
            finally:
                bus.write('Lock', 'gripper', original_lock, normalize=False)
        after = {name: dataclasses.asdict(cal) for name, cal in bus.read_calibration().items()}
        after_torque = check_torque(bus)
        save(directory / f'after-gripper-range-{stamp}.json', {'follower_calibration': after, 'torque_enable': after_torque, 'verified': after == expected})
        if after != expected:
            raise RuntimeError('Readback differs from expected; stop for review. No automatic extra writes.')
        print('Verified gripper range 1031–2496; homing offset 860 and all other calibration unchanged. Torque remains OFF.')
    finally:
        bus.port_handler.closePort()
