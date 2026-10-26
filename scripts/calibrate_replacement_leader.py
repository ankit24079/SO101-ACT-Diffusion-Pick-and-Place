"""Reviewed manual calibration using LeRobot 0.6.1's leader calibrate method.

Only the leader is mapped. Avoid normal connect/configure side effects; preserve
existing motor IDs, baud registers, acceleration, PID and feedback configuration.
"""
import dataclasses
import importlib.metadata
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from lerobot.teleoperators.so_leader import SO101Leader, SO101LeaderConfig


def save(path, data):
    with path.open('x') as stream:
        json.dump(data,stream,indent=2)
        stream.write('\n');stream.flush();os.fsync(stream.fileno())


def main():
    if importlib.metadata.version('lerobot')!='0.6.1':
        raise RuntimeError('Review calibration for this LeRobot version')
    session=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    directory=Path('/calibration/teleoperators/so101_leader')/f'replacement-{session}'
    identity='cup_leader_replacement_20261019'
    calibration_file=directory/(identity+'.json')
    if calibration_file.exists():
        raise RuntimeError(f'Calibration already exists: {calibration_file}; stop for review instead of overwriting')
    leader=SO101Leader(SO101LeaderConfig(port='/dev/so101-leader',id=identity,calibration_dir=directory))
    bus=leader.bus
    reports=Path('/workspace/outputs/motor-inspection')
    reports.mkdir(parents=True,exist_ok=True)
    stamp=str(time.time_ns())
    try:
        # Bypass device.connect(), which invokes configure_motors().
        bus.connect(handshake=False)
        for name in bus.motors:
            if bus.ping(name,raise_on_error=True)!=bus.model_number_table['sts3215']:
                raise RuntimeError(f'Unexpected model: {name}')
            if bus.read('Torque_Enable',name,normalize=False)!=0:
                raise RuntimeError(f'{name}: torque must already be OFF; support arm and inspect first')
            low=bus.read('Min_Voltage_Limit',name,normalize=False)
            high=bus.read('Max_Voltage_Limit',name,normalize=False)
            voltage=bus.read('Present_Voltage',name,normalize=False)
            if not low<=voltage<=high:
                raise RuntimeError(f'{name}: voltage outside configured limits; no calibration writes')
        before={n:dataclasses.asdict(c) for n,c in bus.read_calibration().items()}
        save(reports/f'leader-before-calibration-{stamp}.json',{'calibration':before,'port':bus.port})
        print('Backed up current leader offsets/ranges. Follower is not mapped.',flush=True)
        print('Calibration disables torque and writes leader position mode, homing offsets and limits; torque-disable also writes Lock=0.',flush=True)
        print('No IDs, motor baud rates, firmware, PID or acceleration settings are changed.',flush=True)
        print('Support the leader, clear its reach and keep fingers clear of pinch points. Move it only by hand; never force resistance.',flush=True)
        if input('Type CALIBRATE LEADER to approve these writes and manual calibration: ')!='CALIBRATE LEADER':
            raise RuntimeError('Calibration not confirmed; no writes issued')
        # Official pinned-version routine: midpoint homing, then manually record
        # travel; wrist_roll uses the upstream full-turn 0..4095 convention.
        leader.calibrate()
        after={n:dataclasses.asdict(c) for n,c in bus.read_calibration().items()}
        local=json.loads(calibration_file.read_text())
        torque={n:bus.read('Torque_Enable',n,normalize=False) for n in bus.motors}
        verified=after==local and all(v==0 for v in torque.values())
        save(reports/f'leader-after-calibration-{stamp}.json',{'calibration':after,'local_file':str(calibration_file),'torque_enable':torque,'verified':verified})
        if not verified:
            raise RuntimeError('Calibration readback or torque-off check failed; do not teleoperate')
        print(f'Calibration verified and leader torque OFF. Saved {calibration_file}',flush=True)
        print('Old active local calibration has not been replaced. Review this result before teleoperation and verify persistence after a later power cycle.',flush=True)
    finally:
        # Close only; do not run device.disconnect() and its additional writes.
        bus.port_handler.closePort()


if __name__=='__main__':main()
