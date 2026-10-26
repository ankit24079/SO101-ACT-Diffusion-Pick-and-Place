"""Manual calibration scoped to follower shoulder_lift, motor ID 2.

Never enables torque, sends goals, or writes another motor. Existing calibration
files remain untouched; a new file requires review before activation.
"""
import dataclasses
import importlib.metadata
import json
import select
import sys
import time
from pathlib import Path

from lerobot.motors import Motor, MotorCalibration, MotorNormMode
from lerobot.motors.feetech import FeetechMotorsBus

NAMES = ('shoulder_pan', 'shoulder_lift', 'elbow_flex', 'wrist_flex', 'wrist_roll', 'gripper')
JOINT = 'shoulder_lift'
ALLOWED = {'Lock', 'Homing_Offset', 'Min_Position_Limit', 'Max_Position_Limit'}


class ShoulderCalibrationBus(FeetechMotorsBus):
    writes_authorized = False

    def write(self, register, motor, value, *args, **kwargs):
        if not self.writes_authorized or motor not in (JOINT, 2) or register not in ALLOWED:
            raise RuntimeError('Write blocked: only approved ID 2 calibration/Lock writes allowed')
        return super().write(register, motor, value, *args, **kwargs)

    def _write(self, address, length, motor_id, value, *args, **kwargs):
        allowed_addresses = {self.model_ctrl_table['sts3215'][r][0] for r in ALLOWED}
        if not self.writes_authorized or motor_id != 2 or address not in allowed_addresses:
            raise RuntimeError('Low-level write blocked outside ID 2 calibration scope')
        return super()._write(address, length, motor_id, value, *args, **kwargs)

    def sync_write(self, *args, **kwargs):
        raise RuntimeError('Group writes forbidden in scoped shoulder calibration')


def torque_off(bus):
    states = {name: bus.read('Torque_Enable', name, normalize=False) for name in NAMES}
    if any(states.values()):
        raise RuntimeError(f'All follower torque must already be OFF; support arm and release first: {states}')
    return states


def unwrap_delta(previous, current):
    if not 0 <= previous <= 4095 or not 0 <= current <= 4095:
        raise RuntimeError('Encoder reading outside single-turn 0..4095 range')
    return (current-previous+2048) % 4096-2048


def calibration_plan(old_offset, raw_positions):
    if len(raw_positions) < 10:
        raise RuntimeError('Too few measurements; repeat the slow manual sweep')
    unwrapped = [raw_positions[0]]
    for a, b in zip(raw_positions, raw_positions[1:]):
        delta = unwrap_delta(a, b)
        if abs(delta) > 512:
            raise RuntimeError('Movement/read gap too large; repeat slowly to avoid ambiguous encoder wrapping')
        unwrapped.append(unwrapped[-1]+delta)
    minimum, maximum = min(unwrapped), max(unwrapped)
    span = maximum-minimum
    if not 256 <= span < 4032:
        raise RuntimeError(f'Measured span {span} is too small or cannot fit single-turn calibration; no writes issued')
    centre = round((minimum+maximum)/2)
    target = 2047
    signed = lambda value: (value+2048) % 4096-2048
    offset = signed(old_offset+centre-target)
    if offset == -2048:  # Feetech sign-magnitude offset has only 11 magnitude bits.
        target -= 1
        offset = signed(old_offset+centre-target)
    plan = {'homing_offset': offset, 'range_min': target+minimum-centre,
            'range_max': target+maximum-centre}
    # Feetech's reviewed relation is reported position = actual - homing offset.
    predicted = [(p+old_offset-offset) % 4096 for p in raw_positions]
    if not all(plan['range_min'] <= p <= plan['range_max'] for p in predicted):
        raise RuntimeError('Proposed offset does not keep measured travel contiguous; no writes issued')
    return plan


def measure(bus, low, high, rows, allow_wrap):
    previous = None
    last_print = 0
    while True:
        if select.select([sys.stdin], [], [], 0)[0]:
            sys.stdin.readline()
            break
        torque_off(bus)
        voltage = bus.read('Present_Voltage', JOINT, normalize=False)
        if not low <= voltage <= high:
            raise RuntimeError('Shoulder voltage outside stored limits during manual sweep')
        position = bus.read('Present_Position', JOINT, normalize=False)
        rows.append({'seconds': time.monotonic(), 'position_raw': position, 'voltage_raw': voltage})
        if previous is not None:
            if abs(unwrap_delta(previous, position)) > 512:
                raise RuntimeError('Movement/read gap too large; stop and repeat slowly')
            if not allow_wrap and abs(position-previous) > 2048:
                raise RuntimeError('Encoder still wraps after correction; do not use this calibration')
        previous = position
        if time.monotonic()-last_print > .5:
            print(f'ID 2 reading={position}; samples={len(rows)}. Continue the comfortable sweep; ENTER finishes this stage.', flush=True)
            last_print = time.monotonic()
        time.sleep(.05)


def main():
    if importlib.metadata.version('lerobot') != '0.6.1':
        raise RuntimeError('Review calibration for the installed version')
    bus = ShoulderCalibrationBus('/dev/so101-follower', {
        name: Motor(i, 'sts3215', MotorNormMode.RANGE_0_100)
        for i, name in enumerate(NAMES, 1)})
    stamp = str(time.time_ns())
    directory = Path('/workspace/outputs/shoulder-calibration')/stamp
    directory.mkdir(parents=True, exist_ok=False)
    report = {'status': 'started', 'motor_id': 2, 'joint': JOINT,
              'torque_enable_commands': False, 'goal_commands': False,
              'active_calibration_replaced': False, 'samples': []}
    original_lock = None
    try:
        bus.connect(handshake=False)
        for name in NAMES:
            if bus.ping(name, raise_on_error=True) != bus.model_number_table['sts3215']:
                raise RuntimeError(f'{name}: unexpected motor model')
        report['torque_before'] = torque_off(bus)
        before = {name: dataclasses.asdict(c) for name, c in bus.read_calibration().items()}
        report['before'] = before
        original_lock = bus.read('Lock', JOINT, normalize=False)
        report['original_lock'] = original_lock
        if bus.read('Operating_Mode', JOINT, normalize=False) != 0:
            raise RuntimeError('ID 2 is not in position mode; no settings changed')
        if bus.read('Phase', JOINT, normalize=False) & 0x10:
            raise RuntimeError('ID 2 feedback mode needs review; no settings changed')
        low = bus.read('Min_Voltage_Limit', JOINT, normalize=False)
        high = bus.read('Max_Voltage_Limit', JOINT, normalize=False)
        voltage = bus.read('Present_Voltage', JOINT, normalize=False)
        if not low <= voltage <= high:
            raise RuntimeError('Shoulder voltage outside stored limits')
        # Persist the original registers BEFORE any write or user movement.
        (directory/'before.json').write_text(json.dumps(report, indent=2)+'\n')
        print(f'Original follower calibration backed up: {directory}/before.json', flush=True)
        print('Only ID 2 Lock, homing offset and position limits may be written. No torque-enable, goal, mode, PID, voltage-limit, ID or baud writes.', flush=True)
        print('No midpoint pose is needed. First we MEASURE with no writes: support the arm and gently move ONLY the FIRST HINGE ABOVE THE ROTATING BASE from one comfortable end of travel to the other and back. Never force resistance.', flush=True)
        input('Press ENTER when supported to begin READ-ONLY measurement: ')
        print('Measuring now. Press ENTER after the full comfortable sweep. Crossing 0/4095 is tracked in this measurement stage.', flush=True)
        measurement = report['measurement_samples'] = []
        measure(bus, low, high, measurement, allow_wrap=True)
        plan = calibration_plan(before[JOINT]['homing_offset'], [r['position_raw'] for r in measurement])
        report['plan'] = plan
        (directory/'measured-plan.json').write_text(json.dumps(report, indent=2)+'\n')
        print(f'Measured ID 2 calibration proposal: {plan}. Only this motor will change; no powered movement.', flush=True)
        while True:
            answer = input('Keep supporting the arm. Type CALIBRATE MOTOR 2 to apply the measured proposal (or Q to cancel): ').strip()
            if answer.casefold() == 'calibrate motor 2':
                break
            if answer.casefold() in ('q', 'cancel', 'quit'):
                report['status'] = 'cancelled'
                print('Cancelled. No motor settings changed.', flush=True)
                return
            print('No writes issued. Type CALIBRATE MOTOR 2 to apply the displayed proposal, or Q to cancel.', flush=True)
        torque_off(bus)
        bus.writes_authorized = True
        bus.write('Lock', JOINT, 0, normalize=False)
        expected = json.loads(json.dumps(before))
        expected[JOINT].update(plan)
        torque_off(bus)
        bus.write_calibration({JOINT: MotorCalibration(**expected[JOINT])}, cache=False)
        print('Correction applied, torque still OFF. Repeat the SAME comfortable sweep to verify continuous readings, then press ENTER. No midpoint positioning is needed.', flush=True)
        measure(bus, low, high, report['samples'], allow_wrap=False)
        values = [row['position_raw'] for row in report['samples']]
        if len(values) < 10 or max(values)-min(values) < .8*(plan['range_max']-plan['range_min']):
            raise RuntimeError('Verification sweep did not cover enough of the measured travel')
        if min(values) < plan['range_min']-16 or max(values) > plan['range_max']+16:
            raise RuntimeError('Verification travel differs from first sweep; review before teleoperation')
        minimum, maximum = min(plan['range_min'], min(values)), max(plan['range_max'], max(values))
        expected[JOINT].update(range_min=minimum, range_max=maximum)
        torque_off(bus)
        bus.write_calibration({JOINT: MotorCalibration(**expected[JOINT])}, cache=False)
        after = {name: dataclasses.asdict(c) for name, c in bus.read_calibration().items()}
        report.update(after=after, torque_after=torque_off(bus))
        if after != expected:
            raise RuntimeError('Readback differs or another joint changed; do not teleoperate')
        target = Path('/calibration/robots/so101_follower')/('repaired-shoulder-'+stamp)/'cup_follower_repaired.json'
        target.parent.mkdir(parents=True, exist_ok=False)
        with target.open('x') as stream:
            json.dump(after, stream, indent=2)
            stream.write('\n')
        report.update(status='verified', new_calibration_file=str(target), new_range=[minimum, maximum])
        print(f'ID 2 calibration verified; other five joints unchanged. Saved {target}', flush=True)
        print('Torque remains OFF. Active calibration file was not overwritten. Review this report before selecting the new calibration or teleoperating.', flush=True)
    except BaseException as error:
        report.update(status='error_or_interrupted', error=str(error))
        raise
    finally:
        if bus.writes_authorized:
            try:
                bus.write('Lock', JOINT, original_lock, normalize=False)
                report['lock_restored'] = bus.read('Lock', JOINT, normalize=False) == original_lock
                if not report['lock_restored']:
                    report['status'] = 'lock_verification_failed'
            except Exception as error:
                report.update(status='lock_restore_failed', lock_restore_error=str(error))
        bus.port_handler.closePort()
        (directory/'report.json').write_text(json.dumps(report, indent=2)+'\n')
        print(f'ID 2 calibration report: {directory}/report.json', flush=True)
        if report['status'] != 'verified' and bus.writes_authorized:
            print('Calibration incomplete; ID 2 registers may have changed. Do not run teleoperation; original backup is preserved.', flush=True)


if __name__ == '__main__':
    main()
