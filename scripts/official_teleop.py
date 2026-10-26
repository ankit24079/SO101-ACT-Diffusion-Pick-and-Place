"""Reviewed launcher for the installed, unmodified LeRobot 0.6.1 control loop.

Default: read-only audit. --run: official connect/configure + official loop.
Only operator stop handling, backups and cleanup are added around that loop.
"""
import argparse
import dataclasses
import importlib.metadata
import json
import os
import select
import signal
import sys
import threading
from pathlib import Path

from audit_lerobot_official import main as audit


class OperatorStop(Exception):
    pass


class StopAtLoopBoundary:
    """Leave the official loop before its next read, never inside serial I/O."""
    def __init__(self, robot, requested):
        self.robot = robot
        self.requested = requested

    def __getattr__(self, name):
        return getattr(self.robot, name)

    def get_observation(self):
        if self.requested.is_set():
            raise OperatorStop
        return self.robot.get_observation()


def calibration_path(relative):
    root = Path('/calibration').resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise RuntimeError(f'Missing or invalid calibration path: {relative}')
    return path


def main(run=False, record=False):
    if importlib.metadata.version('lerobot') != '0.6.1':
        raise RuntimeError('This launcher was reviewed for LeRobot 0.6.1 only')
    if record:
        run = True
        from official_episode import OfficialEpisode, RecordedFollower
        from test_episode import smoke_test
        smoke_test(fps=30)
    out, report = audit(True)
    # The audit preserves every raw status byte. Do not proceed from a faulted
    # individual response merely because grouped reads could discard its flag.
    for role, arm in report['arms'].items():
        for name, motor in arm['motors'].items():
            for register, row in {'Model_Number': motor['model'], **motor['registers']}.items():
                if row.get('supported') and (not row['communication_ok'] or row['motor_error_byte']):
                    raise RuntimeError(f'{role}/{name}/{register}: faulted preflight response; see {out}')
            if motor['status'] != 'read_complete':
                raise RuntimeError(f'{role}/{name}: incomplete motor audit')
            regs = motor['registers']
            if regs['Torque_Enable']['value_raw'] != 0:
                raise RuntimeError(f'{role}/{name}: support arm and turn torque off before this baseline')
            low, high, value = [regs[k]['value_raw'] for k in
                                ('Min_Voltage_Limit', 'Max_Voltage_Limit', 'Present_Voltage')]
            if not low <= value <= high:
                raise RuntimeError(f'{role}/{name}: voltage {value} outside stored limits {low}..{high}')
            if role == 'follower':
                position, minimum, maximum = [regs[k]['value_raw'] for k in
                                              ('Present_Position', 'Min_Position_Limit', 'Max_Position_Limit')]
                if not minimum <= position <= maximum:
                    raise RuntimeError(
                        f'follower/{name}: raw position {position} outside stored calibrated range '
                        f'{minimum}..{maximum}. Review physical posture/assembly before torque enable; '
                        'no configuration or movement writes issued.'
                    )

    from lerobot.cameras.opencv import OpenCVCameraConfig
    from lerobot.processor import make_default_processors
    from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig
    from lerobot.teleoperators.so_leader import SO101Leader, SO101LeaderConfig
    from lerobot.scripts.lerobot_teleoperate import teleop_loop

    leader_file = calibration_path(os.environ['LEADER_CALIBRATION_RELATIVE'])
    follower_file = calibration_path(os.environ.get(
        'FOLLOWER_CALIBRATION_RELATIVE', 'robots/so101_follower/cup_follower.json'))
    leader = SO101Leader(SO101LeaderConfig(port='/dev/so101-leader', id=leader_file.stem,
                                         calibration_dir=leader_file.parent))
    follower = SO101Follower(SO101FollowerConfig(
        port='/dev/so101-follower', id=follower_file.stem, calibration_dir=follower_file.parent,
        cameras={name: OpenCVCameraConfig(index_or_path=path, width=640, height=480,
                                         fps=30, fourcc='MJPG', warmup_s=2)
                 for name, path in [('workspace', '/dev/video0'), ('wrist', '/dev/video1')]}))
    for role, device, path in [('leader', leader, leader_file), ('follower', follower, follower_file)]:
        local = json.loads(path.read_text())
        (out / f'{role}-calibration.json').write_text(json.dumps(local, indent=2)+'\n')
        bus = device.bus
        try:
            bus.connect(handshake=False)
            actual = {name: dataclasses.asdict(c) for name, c in bus.read_calibration().items()}
            if actual != local:
                raise RuntimeError(f'{role}: calibration mismatch; baseline will not recalibrate or overwrite it')
        finally:
            bus.port_handler.closePort()
    manifest = {'mode': 'official_lerobot_0.6.1', 'fps_requested': 60,
                'leader_config': dataclasses.asdict(leader.config),
                'follower_config': dataclasses.asdict(follower.config),
                'recording': record, 'motor_configuration_started': False,
                'stop': 'Enter or Ctrl+C', 'outcome': 'read_only_audit_completed'}
    def save():
        (out/'official-session.json').write_text(json.dumps(manifest, indent=2, default=str)+'\n')
    save()
    print('Official defaults: degrees for arm joints, gripper 0..100; absolute mapping; 60 Hz requested.', flush=True)
    print('Official configuration writes: delay=0, maximum acceleration=254, acceleration=254; position mode; follower PID=16/0/32; gripper torque/current/overload=500/250/25; official Phase/Lock handling.', flush=True)
    print('Stored voltage limits and calibration are preserved. No IDs, baud-register or firmware changes.', flush=True)
    print('The official loop has no custom 60-unit shoulder cap, 5-unit tracking stop, 5-unit/s slew, relative-start offsets or contact-hold policy.', flush=True)
    if not run:
        print(f'Read-only baseline review saved: {out}. Add --run to start the official baseline.', flush=True)
        return
    print('Official connect enables follower torque. Align the physical poses first; absolute commands can move the follower immediately. Keep the workspace clear and power disconnect accessible.', flush=True)
    if input('Type CLEAR TO MOVE to apply official configuration and start: ') != 'CLEAR TO MOVE':
        raise RuntimeError('Movement not confirmed; no settings written')
    stop = threading.Event()
    requested = threading.Event()
    def request_stop(signum, frame):
        manifest['operator_stop'] = signal.Signals(signum).name
        requested.set()
    previous_handlers = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}
    for s in previous_handlers:
        signal.signal(s, request_stop)
    def enter_stop():
        while not stop.wait(.05):
            if select.select([sys.stdin], [], [], 0)[0]:
                line = sys.stdin.readline()
                manifest['operator_stop'] = 'Enter' if line else 'stdin_closed'
                requested.set()
                return
    manifest['motor_configuration_started'] = True
    save()
    recorder = None
    try:
        if record:
            recorder = OfficialEpisode(out/'official-session.json', fps=30)
            manifest['dataset_root'] = str(recorder.root)
        leader.connect(calibrate=False)
        follower.connect(calibrate=False)
        processors = make_default_processors()
        manifest['outcome'] = 'running'
        save()
        threading.Thread(target=enter_stop, daemon=True).start()
        if record:
            print('RECORDING STARTED: cube into cup; both cameras/states/sent actions at up to 30 FPS. Official control requests 60 Hz. Press Enter when done; no timer.', flush=True)
        else:
            print('Official teleoperation active; Enter or Ctrl+C stops. No dataset recording.', flush=True)
        observed_robot = RecordedFollower(follower, recorder) if record else follower
        teleop_loop(teleop=leader, robot=StopAtLoopBoundary(observed_robot, requested), fps=60,
                    teleop_action_processor=processors[0], robot_action_processor=processors[1],
                    robot_observation_processor=processors[2], duration=None)
        manifest['outcome'] = 'completed'
    except (OperatorStop, KeyboardInterrupt):
        manifest['outcome'] = 'operator_stopped'
    except BaseException as error:
        manifest['outcome'] = f'{type(error).__name__}: {error}'
        raise
    finally:
        stop.set()
        manifest['cleanup_errors'] = []
        # Cover partial connect failures as well as normal official disconnect.
        for role, device in [('follower', follower), ('leader', leader)]:
            bus = device.bus
            if bus.port_handler.is_open:
                try:
                    # Motor calls are synchronous on this main thread, and the
                    # control loop has unwound. No recorder/camera worker touches
                    # this bus. Recover a stale SDK latch left by interrupted I/O.
                    if getattr(bus.port_handler, 'is_using', False) is True:
                        manifest.setdefault('sdk_busy_latch_recovered', []).append(role)
                        bus.port_handler.is_using = False
                    for name in bus.motors:
                        try:
                            bus.disable_torque(name, num_retry=2)
                        except Exception as error:
                            manifest['cleanup_errors'].append(f'{role}/{name}: torque disable: {error}')
                    states = {name: bus.read('Torque_Enable', name, normalize=False, num_retry=2)
                              for name in bus.motors}
                    manifest[f'{role}_torque_off_verified'] = all(v == 0 for v in states.values())
                    if not manifest[f'{role}_torque_off_verified']:
                        raise RuntimeError('Torque-off readback failed')
                except Exception as error:
                    manifest['cleanup_errors'].append(f'{role}: {error}')
                    print(f'POWER OFF {role.upper()}: cannot verify torque off: {error}', flush=True)
                finally:
                    bus.port_handler.closePort()
            for camera in getattr(device, 'cameras', {}).values():
                try:
                    if camera.is_connected:
                        camera.disconnect()
                except Exception as error:
                    manifest['cleanup_errors'].append(f'camera cleanup: {error}')
        save()
        print(f'Official session report: {out}/official-session.json', flush=True)
        if recorder is not None:
            try:
                recorder.finish(manifest['outcome'], manifest.get('follower_torque_off_verified', False))
            except Exception as error:
                manifest['recording_save_error'] = str(error)
                save()
                print(f'RECORDING SAVE FAILED: {error}. Keep the spooled frames for recovery.', flush=True)
        for s, handler in previous_handlers.items():
            signal.signal(s, handler)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', action='store_true', help='Apply official configuration and run official teleoperation')
    parser.add_argument('--record', action='store_true', help='Record one episode using official control; implies --run; Enter to finish')
    def terminate(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, terminate)
    args = parser.parse_args()
    main(args.run, args.record)
