import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from inference_timing import control_gap_status,bounded_step_time


class TimingTest(unittest.TestCase):
    def test_observed_brief_delays_warn_and_sustained_stall_stops(self):
        for dt in (.274,.333,.343):
            self.assertEqual(control_gap_status(dt),'late')
        self.assertEqual(control_gap_status(1/30),'normal')
        self.assertEqual(control_gap_status(.25),'normal')
        self.assertEqual(control_gap_status(1.),'stop')
        self.assertEqual(control_gap_status(1.5),'stop')

    def test_pause_does_not_expand_target_step(self):
        for dt in (.274,.333,.343,.9):
            self.assertEqual(bounded_step_time(dt),.05)
            self.assertAlmostEqual(30*bounded_step_time(dt),1.5)
        self.assertAlmostEqual(bounded_step_time(1/30),1/30)

    def test_invalid_clock_values_fail(self):
        for dt in (math.nan,math.inf,-1):
            with self.assertRaises(ValueError):control_gap_status(dt)
            with self.assertRaises(ValueError):bounded_step_time(dt)


if __name__=='__main__':unittest.main()
