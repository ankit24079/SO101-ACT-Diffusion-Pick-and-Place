"""Launcher regression checks with fake devices; no hardware accessed."""
import contextlib
import copy
import dataclasses
import io
import json
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import official_teleop


@dataclasses.dataclass
class Config:
    port: str
    id: str
    calibration_dir: Path
    cameras: dict = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class Calibration:
    id: int
    drive_mode: int
    homing_offset: int
    range_min: int
    range_max: int


class LauncherTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name)
        self.data = {'gripper': {'id': 6, 'drive_mode': 0, 'homing_offset': 0,
                                 'range_min': 100, 'range_max': 3000}}
        self.path = self.out/'arm.json'
        self.path.write_text(json.dumps(self.data))
        regs = {name: {'supported': True, 'communication_ok': True,
                      'motor_error_byte': 0, 'value_raw': value}
                for name, value in [('Torque_Enable', 0), ('Min_Voltage_Limit', 40),
                                    ('Max_Voltage_Limit', 120), ('Present_Voltage', 49),
                                    ('Present_Position', 2000), ('Min_Position_Limit', 100),
                                    ('Max_Position_Limit', 3000)]}
        motor = {'status': 'read_complete', 'model': dict(regs['Present_Voltage']), 'registers': regs}
        self.report = {'arms': {role: {'motors': {'gripper': copy.deepcopy(motor)}}
                                for role in ('leader', 'follower')}}
        self.devices = []
        self.connect_failure = False
        outer = self
        class Device:
            def __init__(self, config):
                self.config = config
                self.cameras = {}
                self.bus = Mock()
                self.bus.motors = {'gripper': None}
                self.bus.port_handler.is_open = False
                self.bus.read_calibration.return_value = {'gripper': Calibration(**outer.data['gripper'])}
                self.bus.read.return_value = 0
                self.bus.connect.side_effect = lambda **kwargs: setattr(self.bus.port_handler, 'is_open', True)
                self.bus.port_handler.closePort.side_effect = lambda: setattr(self.bus.port_handler, 'is_open', False)
                self.connect_calls = []
                outer.devices.append(self)
            def connect(self, calibrate):
                self.connect_calls.append(calibrate)
                self.bus.port_handler.is_open = True
                if outer.connect_failure and 'follower' in self.config.port:
                    raise RuntimeError('partial connect failure')
        self.loop = Mock(side_effect=KeyboardInterrupt)
        self.processors = (object(), object(), object())
        modules = {}
        for name, values in {
            'lerobot.cameras.opencv': {'OpenCVCameraConfig': lambda **kw: kw},
            'lerobot.processor': {'make_default_processors': lambda: self.processors},
            'lerobot.robots.so_follower': {'SO101Follower': Device, 'SO101FollowerConfig': Config},
            'lerobot.teleoperators.so_leader': {'SO101Leader': Device, 'SO101LeaderConfig': Config},
            'lerobot.scripts.lerobot_teleoperate': {'teleop_loop': self.loop},
        }.items():
            module = types.ModuleType(name)
            module.__dict__.update(values)
            modules[name] = module
        for context in [patch.dict(sys.modules, modules),
                        patch.dict('os.environ', {'LEADER_CALIBRATION_RELATIVE': 'selected.json'}),
                        patch.object(official_teleop.importlib.metadata, 'version', return_value='0.6.1'),
                        patch.object(official_teleop, 'audit', return_value=(self.out, self.report)),
                        patch.object(official_teleop, 'calibration_path', return_value=self.path),
                        patch.object(official_teleop.threading, 'Thread'),
                        patch('builtins.input', return_value='CLEAR TO MOVE'),
                        contextlib.redirect_stdout(io.StringIO())]:
            context.__enter__()
            self.addCleanup(context.__exit__, None, None, None)

    def test_read_only_never_configures_or_moves(self):
        official_teleop.main(False)
        self.assertTrue(all(not d.connect_calls for d in self.devices))
        self.loop.assert_not_called()
        for d in self.devices:
            d.bus.disable_torque.assert_not_called()

    def test_motor_error_blocks_before_native_connect(self):
        self.report['arms']['leader']['motors']['gripper']['registers']['Present_Voltage']['motor_error_byte'] = 1
        with self.assertRaisesRegex(RuntimeError, 'faulted preflight'):
            official_teleop.main(True)
        self.assertEqual(self.devices, [])
        self.loop.assert_not_called()

    def test_follower_outside_calibration_blocks_before_native_connect(self):
        regs = self.report['arms']['follower']['motors']['gripper']['registers']
        regs['Present_Position']['value_raw'] = 3891
        with self.assertRaisesRegex(RuntimeError, 'outside stored calibrated range'):
            official_teleop.main(True)
        self.assertEqual(self.devices, [])
        self.loop.assert_not_called()

    def test_actual_loop_delegation_and_torque_cleanup(self):
        official_teleop.main(True)
        self.loop.assert_called_once()
        args = self.loop.call_args.kwargs
        self.assertEqual(args['fps'], 60)
        self.assertIsNone(args['duration'])
        self.assertIs(args['teleop_action_processor'], self.processors[0])
        self.assertTrue(all(d.connect_calls == [False] for d in self.devices))
        for d in self.devices:
            d.bus.disable_torque.assert_called_with('gripper', num_retry=2)
        manifest = json.loads((self.out/'official-session.json').read_text())
        self.assertTrue(manifest['follower_torque_off_verified'])

    def test_partial_connect_failure_still_disables_torque(self):
        self.connect_failure = True
        with self.assertRaisesRegex(RuntimeError, 'partial connect'):
            official_teleop.main(True)
        self.loop.assert_not_called()
        for d in self.devices:
            d.bus.disable_torque.assert_called_with('gripper', num_retry=2)

    def test_stop_request_waits_for_next_read_boundary(self):
        requested = threading.Event()
        robot = Mock()
        def read():
            requested.set()  # Enter arrives while synchronous I/O is running.
            return {'state': 1}
        robot.get_observation.side_effect = read
        proxy = official_teleop.StopAtLoopBoundary(robot, requested)
        self.assertEqual(proxy.get_observation(), {'state': 1})
        with self.assertRaises(official_teleop.OperatorStop):
            proxy.get_observation()
        robot.get_observation.assert_called_once()

    def test_interrupted_sdk_busy_latch_recovered_before_cleanup(self):
        def fail(**kwargs):
            self.devices[1].bus.port_handler.is_using = True
            raise KeyboardInterrupt
        self.loop.side_effect = fail
        official_teleop.main(True)
        self.assertFalse(self.devices[1].bus.port_handler.is_using)
        manifest = json.loads((self.out/'official-session.json').read_text())
        self.assertEqual(manifest['sdk_busy_latch_recovered'], ['follower'])
        self.assertTrue(manifest['follower_torque_off_verified'])


if __name__ == '__main__':
    unittest.main()
