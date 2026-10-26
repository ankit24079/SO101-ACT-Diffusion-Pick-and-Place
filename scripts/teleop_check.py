"""LeRobot 0.6.1 bus-level preflight and explicitly approved 20 s teleop test.

Default is read-only preflight. Does not call robot.connect/configure/calibrate.
Run mode writes only follower Goal_Position and Torque_Enable registers.
"""
import argparse
import dataclasses
import importlib.metadata
import json
import os
import signal
import select
import sys
import time
from pathlib import Path

from gripper_contact import GripperContactHold

from lerobot.motors import Motor, MotorCalibration, MotorNormMode
from lerobot.motors.feetech import FeetechMotorsBus

NAMES = ('shoulder_pan', 'shoulder_lift', 'elbow_flex', 'wrist_flex', 'wrist_roll', 'gripper')


def read(bus, register):
    values = {}
    for name in NAMES:
        try:
            values[name] = bus.read(register, name, normalize=False)
        except Exception as error:
            raise RuntimeError(f'{bus.port}: {name}, register {register}: {error}') from error
    return values


def positions(bus):
    raw = read(bus, 'Present_Position')
    for name, value in raw.items():
        c = bus.calibration[name]
        # Small encoder jitter near an endpoint is allowed; never extends commands.
        if not c.range_min - 8 <= value <= c.range_max + 8:
            raise RuntimeError(f'{bus.port}/{name}: raw position {value} outside calibrated range {c.range_min}..{c.range_max} (8-count jitter allowance); stop')
    # Normalize the same snapshot rather than reading every joint twice.
    # The raw-read wrapper above preserves arm/joint context on SDK faults.
    normalized = bus._normalize({bus.motors[name].id: value for name, value in raw.items()})
    return raw, {name: normalized[bus.motors[name].id] for name in NAMES}


def interrupted(signum, frame):
    raise KeyboardInterrupt


def check_voltage(bus):
    limits = {}
    for name in NAMES:
        low = bus.read('Min_Voltage_Limit', name, normalize=False)
        high = bus.read('Max_Voltage_Limit', name, normalize=False)
        value = bus.read('Present_Voltage', name, normalize=False)
        if not low < high or not low <= value <= high:
            raise RuntimeError(f'{bus.port}/{name}: voltage register {value} outside {low}..{high}')
        limits[name] = (low, high)
    return limits


def relative_targets(leader, offset):
    targets = {}
    for name in NAMES:
        low = 0 if name == 'gripper' else -100
        targets[name] = min(100, max(low, leader[name] + offset[name]))
    return targets


def startup_offsets(leader, follower, relative_start):
    # Arm joints can start in different poses. Gripper openness must keep its
    # calibrated meaning (0=closed, 100=open), independent of initial openings.
    return {
        name: follower[name]-leader[name] if relative_start and name != 'gripper' else 0.0
        for name in NAMES
    }


def ensure_torque_off(bus, role, allow_release=False):
    states = read(bus, 'Torque_Enable')
    enabled = {name: value for name, value in states.items() if value != 0}
    if not enabled:
        return
    print(f'{role}: existing Torque_Enable values: {json.dumps(states)}', flush=True)
    if role != 'follower' or not allow_release:
        raise RuntimeError(f'{role}: torque must already be off; affected joints: {json.dumps(enabled)}')
    if any(value != 1 for value in enabled.values()):
        raise RuntimeError(f'{role}: unexpected torque register value; inspect before changing settings')
    print('The follower is already energized. Stop other robot programs. Secure/support it so it can settle safely; keep hands clear of pinch points.', flush=True)
    print('The next step writes Torque_Enable=0 only to the enabled follower joints. It does not command a position or change calibration.', flush=True)
    if input('Type RELEASE TORQUE only when the arm can settle safely: ') != 'RELEASE TORQUE':
        raise RuntimeError('Torque release not confirmed; no release writes issued')
    path = Path('/workspace/outputs/motor-inspection') / f'torque-release-{time.time_ns()}.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    report = {'before': states, 'status': 'started'}
    # Persist the existing state before attempting any register write.
    path.write_text(json.dumps(report, indent=2)+'\n')
    try:
        errors = {}
        for name in enabled:
            try:
                bus.write('Torque_Enable', name, 0, normalize=False)
            except Exception as error:
                errors[name] = str(error)
        after = read(bus, 'Torque_Enable')
        report.update(after=after, write_errors=errors)
        if errors or any(after.values()):
            raise RuntimeError('Torque release incomplete. Cut follower motor power and inspect the report.')
        report['status'] = 'torque_off_verified'
        print('Existing follower torque released; all six joints now report OFF.', flush=True)
    except BaseException as error:
        report.update(status='error', error=str(error))
        raise
    finally:
        path.write_text(json.dumps(report, indent=2)+'\n')
        print(f'Torque release report: {path}', flush=True)


class VoltageLog:
    """Persist every successful voltage read and any fault, including partial samples."""
    def __init__(self, buses, limits):
        self.buses = buses
        self.limits = limits
        self.root = Path('/workspace/outputs/task-voltage') / str(time.time_ns())
        self.root.mkdir(parents=True, exist_ok=False)
        self.stream = (self.root/'samples.jsonl').open('x')
        self.control_stream = (self.root/'control.jsonl').open('x')
        self.started = time.monotonic()
        self.last_print = -1
        self.extrema = {role: {} for role in buses}
        self.fault = None
        self.last_control_print = -1

    def sample(self):
        row = {'seconds': time.monotonic()-self.started, 'voltage_raw': {}}
        role = name = None
        try:
            for role, bus in self.buses.items():
                row['voltage_raw'][role] = {}
                for name in NAMES:
                    value = bus.read('Present_Voltage', name, normalize=False)
                    row['voltage_raw'][role][name] = value
                    old = self.extrema[role].get(name, [value, value])
                    self.extrema[role][name] = [min(old[0], value), max(old[1], value)]
                    low, high = self.limits[role][name]
                    if not low <= value <= high:
                        raise RuntimeError(f'Voltage register {value} outside {low}..{high}')
        except Exception as error:
            self.fault = f'{role}/{name}/Present_Voltage: {error}'
            row['error'] = self.fault
            raise RuntimeError(self.fault) from error
        finally:
            self.stream.write(json.dumps(row)+'\n')
            self.stream.flush()
        if row['seconds']-self.last_print >= 1:
            print('All-motor voltage registers:', json.dumps(row['voltage_raw']), flush=True)
            self.last_print = row['seconds']

    def control(self, desired, observed, commanded, grip_state=None):
        row = {'seconds': time.monotonic()-self.started,
               'mapped_leader_target': dict(desired), 'observed_follower': dict(observed),
               'sent_follower_target': dict(commanded)}
        if grip_state is not None:
            row['gripper_contact'] = dict(grip_state)
        self.control_stream.write(json.dumps(row)+'\n')
        self.control_stream.flush()
        if row['seconds']-self.last_control_print >= 1:
            print(f'Gripper opening %: requested={desired["gripper"]:.1f}, sent={commanded["gripper"]:.1f}, observed={observed["gripper"]:.1f}', flush=True)
            self.last_control_print = row['seconds']

    def close(self, outcome):
        self.stream.close()
        self.control_stream.close()
        (self.root/'summary.json').write_text(json.dumps({
            'outcome': outcome, 'voltage_fault': self.fault, 'limits_raw': self.limits,
            'min_max_raw': self.extrema,
            'note': 'Sequential motor telemetry samples, not a high-speed electrical transient measurement.',
        }, indent=2)+'\n')
        print(f'All-motor voltage logs: {self.root}', flush=True)


def main(run, monitor=False, with_cameras=False, record_test=False, relative_start=False, until_enter=False, shoulder_lift_max=None):
    if importlib.metadata.version('lerobot') != '0.6.1':
        raise RuntimeError('Expected LeRobot 0.6.1')
    buses = {}
    torque_attempted = False
    cameras = None
    recording = None
    outcome = 'error_or_interrupted'
    torque_off_verified = False
    voltage_log = None
    all_voltage_limits = {}
    grip = GripperContactHold()
    preflight = {'status': 'started', 'arms': {}, 'powered_requested': run,
                 'shoulder_lift_max': shoulder_lift_max}
    preflight_dir = Path('/workspace/outputs/preflight')
    preflight_dir.mkdir(parents=True, exist_ok=True)
    preflight_path = preflight_dir / f'{time.time_ns()}.json'
    if record_test:
        from test_episode import TestEpisode, smoke_test
        smoke_test()
        recording = TestEpisode()
    try:
        for role, relative in (
            ('leader', os.environ.get('LEADER_CALIBRATION_RELATIVE', 'teleoperators/so101_leader/cup_leader.json')),
            ('follower', 'robots/so101_follower/cup_follower.json'),
        ):
            print(f'Checking {role} arm (read-only preflight)...', flush=True)
            arm_report = preflight['arms'][role] = {'calibration_file': relative, 'status': 'checking'}
            data = json.loads((Path('/calibration')/relative).read_text())
            bus = FeetechMotorsBus(f'/dev/so101-{role}', {
                name: Motor(i, 'sts3215', MotorNormMode.RANGE_0_100 if name == 'gripper' else MotorNormMode.RANGE_M100_100)
                for i, name in enumerate(NAMES, 1)
            }, calibration={name: MotorCalibration(**value) for name, value in data.items()})
            buses[role] = bus
            bus.connect(handshake=False)
            for name in NAMES:
                if bus.ping(name, raise_on_error=True) != bus.model_number_table['sts3215']:
                    raise RuntimeError(f'Unexpected {role} motor model')
            ensure_torque_off(bus, role, allow_release=run)
            arm_report['torque_off_checked'] = True
            all_voltage_limits[role] = check_voltage(bus)
            actual = {name: dataclasses.asdict(c) for name, c in bus.read_calibration().items()}
            arm_report['motor_calibration'] = actual
            if actual != data:
                differences = {n: {'motor': actual.get(n), 'local_file': data.get(n)} for n in set(actual) | set(data) if actual.get(n) != data.get(n)}
                raise RuntimeError(f'{role}: stored calibration mismatch: {json.dumps(differences)}; no automatic calibration or torque enable')
            if any(value != 0 for value in read(bus, 'Operating_Mode').values()):
                raise RuntimeError(f'{role}: expected position mode; no automatic mode change')
            if any(value & 0x10 for value in read(bus, 'Phase').values()):
                raise RuntimeError(f'{role}: feedback mode needs review; no automatic change')
            arm_report['status'] = 'register_checks_passed'
        leader, follower = buses['leader'], buses['follower']
        _, leader_pos = positions(leader)
        raw, follower_pos = positions(follower)
        deltas = {name: round(leader_pos[name]-follower_pos[name], 2) for name in NAMES}
        print('Leader minus follower, normalized units:', json.dumps(deltas), flush=True)
        print('Calibration matches; torque OFF; register modes checked.', flush=True)
        preflight.update(status='passed', leader_position=leader_pos, follower_position=follower_pos, deltas=deltas)
        if not run:
            if monitor:
                input('Torque is OFF. Support both arms, keep fingers clear of pinch points. Press ENTER, then gently move ONLY the leader through small motions for 15 seconds: ')
                samples = []
                start = time.monotonic()
                try:
                    while time.monotonic() - start < 15:
                        if any(read(leader, 'Torque_Enable').values()) or any(read(follower, 'Torque_Enable').values()):
                            raise RuntimeError('Torque state changed; stop manual handling')
                        _, desired = positions(leader)
                        _, actual = positions(follower)
                        sample = {'seconds': round(time.monotonic()-start, 3), 'leader_target': desired, 'follower_observed': actual}
                        samples.append(sample)
                        print(json.dumps(sample), flush=True)
                        time.sleep(.2)
                finally:
                    directory = Path('/workspace/outputs/teleop-dry-run')
                    directory.mkdir(parents=True, exist_ok=True)
                    path = directory / f'report-{time.time_ns()}.json'
                    path.write_text(json.dumps({'powered': False, 'samples': samples}, indent=2)+'\n')
                    print(f'Dry-run report saved: {path}', flush=True)
            print('Read-only preflight complete. No motor writes issued.', flush=True)
            outcome = 'read_only_preflight_completed'
            return
        if not relative_start and any(abs(value) > 10 for value in deltas.values()):
            raise RuntimeError('Initial poses differ by over 10 normalized units; stop for alignment review')
        if relative_start:
            print('Relative arm start: arm joints follow leader changes. Gripper uses calibrated absolute openness (no startup offset).', flush=True)
        voltage_log = VoltageLog(buses, all_voltage_limits)
        voltage_log.sample()
        if recording is not None:
            recording.voltage_log_path = str(voltage_log.root)
        if shoulder_lift_max is not None:
            print(f'Shoulder lift follows the leader with a maximum target of {shoulder_lift_max:.2f} normalized units. Existing slew and 5-unit tracking limits remain active.', flush=True)
        if input('Confirm accessible follower power disconnect, clear workspace, and supported arms. Type CLEAR TO MOVE: ') != 'CLEAR TO MOVE':
            raise RuntimeError('Movement not confirmed')
        if with_cameras:
            from teleop_cameras import CameraMonitor
            cameras = CameraMonitor()
            cameras.start()
        # Recheck after the human prompt; the arms may have been touched.
        if any(read(leader, 'Torque_Enable').values()) or any(read(follower, 'Torque_Enable').values()):
            raise RuntimeError('Torque state changed during prompt')
        check_voltage(leader)
        check_voltage(follower)
        voltage_log.sample()
        raw, follower_pos = positions(follower)
        _, leader_pos = positions(leader)
        refreshed_deltas = {n: round(leader_pos[n]-follower_pos[n], 2) for n in NAMES}
        print('Alignment after camera startup:', json.dumps(refreshed_deltas), flush=True)
        outside = {n: leader_pos[n]-follower_pos[n] for n in NAMES if abs(leader_pos[n]-follower_pos[n]) > 10}
        if outside and not relative_start:
            detail = ', '.join(f'{n}={value:.2f}' for n, value in outside.items())
            raise RuntimeError(f'Initial poses changed; outside 10-unit alignment limit: {detail}. No torque enabled.')
        offsets = startup_offsets(leader_pos, follower_pos, relative_start)
        if relative_start:
            print('Startup offsets (follower minus leader):', json.dumps(offsets), flush=True)
        if recording is not None:
            recording.control_mapping = {
                'mode': 'relative_start' if relative_start else 'absolute',
                'gripper_mapping': 'absolute_calibrated_openness',
                'leader_calibration_relative': os.environ.get('LEADER_CALIBRATION_RELATIVE', 'teleoperators/so101_leader/cup_leader.json'),
                'shoulder_lift_max': shoulder_lift_max,
                'gripper_contact_policy': {
                    'type': 'position_contact_hold',
                    'lag_threshold_pp': grip.lag_threshold,
                    'stationary_speed_pp_s': grip.stationary_speed,
                    'confirmation_seconds': grip.confirmation_seconds,
                    'hold_error_pp': grip.hold_error,
                    'release_margin_pp': grip.release_margin,
                    'torque_or_current_control': False,
                },
                'offsets': offsets,
                'leader_start': dict(leader_pos),
                'follower_start': dict(follower_pos),
            }
        if cameras is not None:
            cameras.check()
        # Seed current physical positions BEFORE enabling torque; no stale goals.
        for name, value in raw.items():
            c = follower.calibration[name]
            follower.write('Goal_Position', name, min(c.range_max, max(c.range_min, value)), normalize=False)
        torque_attempted = True
        for name in NAMES:
            follower.write('Torque_Enable', name, 1, normalize=False)
        duration = None if record_test or until_enter else 20
        description = 'Operator-ended recording (no time limit)' if record_test else ('Operator-ended test (no time limit); press ENTER when done' if until_enter else '20-second test')
        print(f'{description}. Move leader gently. Ctrl+C stops; cut follower power immediately for unexpected motion.', flush=True)
        if record_test:
            from test_episode import TASK
            print(f'Recording ONE test episode at 10 FPS: {TASK} Press ENTER when done.', flush=True)
        last = dict(follower_pos)
        start = previous = time.monotonic()
        while duration is None or time.monotonic()-start < duration:
            if (record_test or until_enter) and select.select([sys.stdin], [], [], 0)[0]:
                sys.stdin.readline()
                outcome = 'operator_finished'
                break
            tick = time.monotonic()
            dt = min(tick-previous, .1)
            previous = tick
            if cameras is not None:
                cameras.check()
            voltage_log.sample()
            _, desired = positions(leader)
            desired = relative_targets(desired, offsets)
            if shoulder_lift_max is not None:
                desired['shoulder_lift'] = min(desired['shoulder_lift'], shoulder_lift_max)
            _, current = positions(follower)
            grip_desired, grip_state = grip.update(
                desired['gripper'], last['gripper'], current['gripper'], time.monotonic(),
            )
            if grip_state['event'] == 'contact_latched':
                print(f'Gripper contact suspected: holding target {grip_desired:.2f}%. Further close requests ignored. Open leader above {grip_state["release_above"]:.2f}% to release.', flush=True)
            elif grip_state['event'] == 'release_requested':
                print('Leader opening requested: gripper hold released.', flush=True)
            for name in NAMES:
                # 5 normalized units/s for arm joints; 5 percentage points/s for gripper.
                step = 5 * dt
                requested = grip_desired if name == 'gripper' else desired[name]
                target = last[name] + max(-step, min(step, requested-last[name]))
                if abs(last[name]-current[name]) > 5:
                    raise RuntimeError(
                        f'{name}: excessive tracking error; previous target={last[name]:.2f}, '
                        f'observed={current[name]:.2f}, difference={abs(last[name]-current[name]):.2f} '
                        f'normalized units (limit 5); stop'
                    )
                follower.write('Goal_Position', name, target)
                last[name] = target
            voltage_log.control(desired, current, last, grip_state)
            if recording is not None:
                recording.add(current, last, cameras)
            time.sleep(max(0, .1-(time.monotonic()-tick)))
        else:
            outcome = 'time_limit_completed'
        print(f'Teleoperation loop finished: {outcome}.', flush=True)
    except BaseException as error:
        outcome = 'operator_interrupted' if isinstance(error, KeyboardInterrupt) else f'error: {error}'
        if preflight['status'] != 'passed':
            preflight.update(status='failed', error=str(error))
        raise
    finally:
        follower = buses.get('follower')
        if torque_attempted and follower is not None:
            for name in NAMES:
                try:
                    follower.write('Torque_Enable', name, 0, normalize=False)
                except Exception as error:
                    print(f'POWER OFF FOLLOWER: torque disable failed for {name}: {error}', flush=True)
            try:
                if any(read(follower, 'Torque_Enable').values()):
                    print('POWER OFF FOLLOWER: torque-off readback failed.', flush=True)
                else:
                    torque_off_verified = True
                    print('Follower torque OFF verified.', flush=True)
            except Exception as error:
                print(f'POWER OFF FOLLOWER: cannot verify torque state: {error}', flush=True)
        for bus in buses.values():
            bus.port_handler.closePort()
        preflight['run_outcome'] = outcome
        preflight['torque_enable_attempted'] = torque_attempted
        preflight['follower_torque_off_verified'] = torque_off_verified
        preflight_path.write_text(json.dumps(preflight, indent=2)+'\n')
        print(f'Preflight report saved: {preflight_path}', flush=True)
        if voltage_log is not None:
            voltage_log.close(outcome)
        if cameras is not None:
            cameras.close()
        if recording is not None:
            if not torque_attempted:
                print('Recording did not start; this run issued no torque-enable commands.', flush=True)
            recording.finish(outcome, torque_off_verified, torque_attempted)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', action='store_true', help='Enable follower torque and move; explicit approval required')
    parser.add_argument('--monitor', action='store_true', help='15-second torque-off leader/target monitor; no motor writes')
    parser.add_argument('--cameras', action='store_true', help='Capture both cameras during the approved powered test')
    parser.add_argument('--record-test', action='store_true', help='One local cube-to-cup episode; implies --run --cameras, Enter to finish, no time limit')
    parser.add_argument('--relative-start', action='store_true', help='Apply leader joint changes from the current follower pose; no powered startup alignment')
    parser.add_argument('--until-enter', action='store_true', help='End a powered non-recording test with Enter instead of a timer')
    parser.add_argument('--shoulder-lift-max', type=float, help='Cap the mapped follower shoulder-lift target at this normalized value (-100 to 100); continue following the leader below the cap')
    args = parser.parse_args()
    if args.record_test:
        args.run = args.cameras = True
    if args.run and args.monitor:
        parser.error('Choose either --run or --monitor')
    if args.cameras and not args.run:
        parser.error('--cameras requires --run')
    if args.until_enter and not args.run:
        parser.error('--until-enter requires --run')
    if args.shoulder_lift_max is not None:
        if not args.run:
            parser.error('--shoulder-lift-max requires --run or --record-test')
        if not -100 <= args.shoulder_lift_max <= 100:
            parser.error('--shoulder-lift-max must be between -100 and 100')
    signal.signal(signal.SIGTERM, interrupted)
    main(args.run, args.monitor, args.cameras, args.record_test, args.relative_start, args.until_enter, args.shoulder_lift_max)
