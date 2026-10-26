"""Exercise write scope with the actual upstream half-turn helper, no hardware."""
import ast
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'scripts/calibrate_follower_shoulder.py'


class FakeBus:
    model_ctrl_table = {'sts3215': {'Lock': (55, 1), 'Homing_Offset': (31, 2),
                                  'Min_Position_Limit': (9, 2), 'Max_Position_Limit': (11, 2)}}
    model_resolution_table = {'sts3215': 4096}

    def __init__(self):
        self.calls = []
        self.calibration = {'unrelated': 'preserved in external backup'}

    def write(self, register, motor, value, *args, **kwargs):
        address, length = self.model_ctrl_table['sts3215'][register]
        return self._write(address, length, 2 if motor == 'shoulder_lift' else motor, value)

    def _write(self, address, length, motor_id, value, *args, **kwargs):
        self.calls.append((address, motor_id, value))

    def _get_motors_list(self, motors):
        return motors

    def _get_motor_model(self, motor):
        return 'sts3215'

    def sync_read(self, register, motors, normalize):
        return {motor: 2300 for motor in motors}

    def _get_half_turn_homings(self, positions):
        return {motor: pos-2047 for motor, pos in positions.items()}


class CalibrationPlanTest(unittest.TestCase):
    def setUp(self):
        tree = ast.parse(SOURCE.read_text())
        functions = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                     and n.name in ('unwrap_delta', 'calibration_plan')]
        self.ns = {}
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(SOURCE), 'exec'), self.ns)

    def test_boundary_crossing_becomes_continuous_travel(self):
        raw = [p % 4096 for p in range(2047, 4248, 100)]
        plan = self.ns['calibration_plan'](700, raw)
        predicted = [(p+700-plan['homing_offset']) % 4096 for p in raw]
        self.assertEqual(predicted, list(range(plan['range_min'], plan['range_max']+1, 100)))
        self.assertGreater(plan['range_min'], 0)
        self.assertLess(plan['range_max'], 4095)

    def test_offset_stays_in_signed_magnitude_range(self):
        for old_offset in (-2047, -1983, 0, 700, 2047):
            plan = self.ns['calibration_plan'](old_offset, list(range(1000, 3001, 100)))
            self.assertLessEqual(abs(plan['homing_offset']), 2047)

    def test_rejects_undersampling_and_ambiguous_jumps(self):
        for raw in ([2047]*20, [1000, 2000]*10, [1000]*3):
            with self.assertRaises(RuntimeError):
                self.ns['calibration_plan'](0, raw)


class ScopeTest(unittest.TestCase):
    def setUp(self):
        tree = ast.parse(SOURCE.read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
        ns = {'FeetechMotorsBus': FakeBus, 'JOINT': 'shoulder_lift',
              'ALLOWED': {'Lock', 'Homing_Offset', 'Min_Position_Limit', 'Max_Position_Limit'}}
        exec(compile(ast.Module(body=[cls], type_ignores=[]), str(SOURCE), 'exec'), ns)
        self.bus = ns['ShoulderCalibrationBus']()

    def test_no_writes_before_confirmation(self):
        with self.assertRaises(RuntimeError):
            self.bus.write('Lock', 'shoulder_lift', 0)
        self.assertEqual(self.bus.calls, [])

    def test_other_joints_and_motion_registers_blocked(self):
        self.bus.writes_authorized = True
        for register, motor in [('Homing_Offset', 'elbow_flex'), ('Torque_Enable', 'shoulder_lift'),
                                ('Goal_Position', 'shoulder_lift'), ('P_Coefficient', 'shoulder_lift')]:
            with self.assertRaises(RuntimeError):
                self.bus.write(register, motor, 1)
        with self.assertRaises(RuntimeError):
            self.bus._write(31, 2, 3, 10)
        with self.assertRaises(RuntimeError):
            self.bus._write(42, 2, 2, 10)
        with self.assertRaises(RuntimeError):
            self.bus.sync_write('Goal_Position', {})
        self.assertEqual(self.bus.calls, [])

    def test_actual_official_helper_only_writes_id_two(self):
        path = ROOT/'outputs/official-source-review-20261019/reference/lerobot-v0.6.1/motors/motors_bus.py'
        if not path.exists():
            self.skipTest('Version-matched upstream reference is not present')
        source = path.read_text()
        # Host Python is 3.10; isolate the methods from the 3.12 module's
        # unrelated PEP-695 type declarations before parsing.
        methods = source[source.index('    def reset_calibration('):source.index('    def record_ranges_of_motion(')]
        tree = ast.parse(textwrap.dedent(methods))
        for name in ('reset_calibration', 'set_half_turn_homings'):
            fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
            fn.returns = None
            fn.decorator_list = []
            for arg in fn.args.args:
                arg.annotation = None
            ns = {}
            exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), str(path), 'exec'), ns)
            setattr(FakeBus, name, ns[name])
        self.bus.writes_authorized = True
        offsets = self.bus.set_half_turn_homings(['shoulder_lift'])
        self.assertEqual(offsets, {'shoulder_lift': 253})
        self.assertEqual(self.bus.calls, [(31, 2, 0), (9, 2, 0), (11, 2, 4095), (31, 2, 253)])


if __name__ == '__main__':
    unittest.main()
