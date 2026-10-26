"""Authorized ID 2 minimum adjustment to 790; no powered movement."""
import dataclasses
import json
import os
import time
from pathlib import Path

import calibrate_follower_shoulder as scoped

# Enforce the narrower scope at both SDK write entry points.
scoped.ALLOWED = {'Lock', 'Min_Position_Limit'}
TARGET = Path('/calibration/robots/so101_follower/repaired-shoulder-1792448625156379989/cup_follower_repaired.json')


def main():
    bus = scoped.ShoulderCalibrationBus('/dev/so101-follower', {
        name: scoped.Motor(i, 'sts3215', scoped.MotorNormMode.RANGE_0_100)
        for i, name in enumerate(scoped.NAMES, 1)})
    directory = Path('/workspace/outputs/shoulder-minimum')/str(time.time_ns())
    directory.mkdir(parents=True)
    report = {'requested_minimum': 790, 'verified': False}
    original_lock = None
    try:
        bus.connect(handshake=False)
        report['torque_before'] = scoped.torque_off(bus)
        before = {name: dataclasses.asdict(c) for name, c in bus.read_calibration().items()}
        local = json.loads(TARGET.read_text())
        if before != local:
            raise RuntimeError('Motor and selected local calibration differ; no writes issued')
        joint = before[scoped.JOINT]
        if (joint['homing_offset'], joint['range_min'], joint['range_max']) not in (
                (1088, 799, 3296), (1088, 790, 3296)):
            raise RuntimeError('Unexpected shoulder calibration; no writes issued')
        original_lock = bus.read('Lock', scoped.JOINT, normalize=False)
        report.update(before=before, original_lock=original_lock)
        (directory/'before.json').write_text(json.dumps(report, indent=2)+'\n')
        (directory/'calibration-backup.json').write_text(TARGET.read_text())
        expected = json.loads(json.dumps(before))
        expected[scoped.JOINT]['range_min'] = 790
        if before != expected:
            bus.writes_authorized = True
            bus.write('Lock', scoped.JOINT, 0, normalize=False)
            scoped.torque_off(bus)
            bus.write('Min_Position_Limit', scoped.JOINT, 790, normalize=False)
        after = {name: dataclasses.asdict(c) for name, c in bus.read_calibration().items()}
        report.update(after=after, torque_after=scoped.torque_off(bus))
        if after != expected:
            raise RuntimeError('Readback differs from requested single-register change')
        if bus.writes_authorized:
            bus.write('Lock', scoped.JOINT, original_lock, normalize=False)
        if bus.read('Lock', scoped.JOINT, normalize=False) != original_lock:
            raise RuntimeError('Lock readback differs; local calibration not updated')
        temp = TARGET.with_suffix('.json.tmp')
        with temp.open('w') as stream:
            json.dump(after, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, TARGET)
        report['verified'] = True
        print('Verified follower ID 2 minimum=790, maximum=3296, offset=1088. Selected calibration file updated; all other calibration unchanged. Torque OFF.', flush=True)
    except BaseException as error:
        report['error'] = str(error)
        raise
    finally:
        if bus.writes_authorized:
            try:
                bus.write('Lock', scoped.JOINT, original_lock, normalize=False)
            except Exception as error:
                report['lock_restore_error'] = str(error)
                report['verified'] = False
        bus.port_handler.closePort()
        (directory/'report.json').write_text(json.dumps(report, indent=2)+'\n')
        print(f'Report: {directory}/report.json', flush=True)


if __name__ == '__main__':
    main()
