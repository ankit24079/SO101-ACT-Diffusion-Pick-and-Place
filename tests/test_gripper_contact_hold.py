import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from gripper_contact_hold import GripperContactHold, startup_raw_goals, native_gripper_goal


class ContactHoldTest(unittest.TestCase):
    def held_gripper(self):
        h=GripperContactHold()
        for i in range(10):
            h.update(0,16,i/30)
        self.assertIsNotNone(h.hold)
        return h

    def test_small_sustained_opening_releases_below_old_threshold(self):
        h=self.held_gripper()
        self.assertEqual(h.update(16.7,16,.4,opening_request=16.7),15.5)
        self.assertEqual(h.update(16.7,16,.5,opening_request=16.7),15.5)
        self.assertEqual(h.update(16.7,16,.56,opening_request=16.7),16.7)
        self.assertIsNone(h.hold)
        self.assertEqual(h.release_count,1)
        self.assertEqual(h.last_event,'release_on_opening_request')

    def test_single_small_opening_spike_does_not_drop(self):
        h=self.held_gripper()
        self.assertEqual(h.update(16.7,16,.4),15.5)
        self.assertEqual(h.update(0,16,.45),15.5)
        self.assertIsNone(h.opening_since)
        self.assertIsNotNone(h.hold)
        self.assertEqual(h.release_count,0)

    def test_subthreshold_jitter_and_persistent_closure_keep_holding(self):
        h=self.held_gripper()
        for i in range(100):
            self.assertEqual(h.update(16.2 if i%2 else 0,16,1+i/30),15.5)
        self.assertEqual(h.release_count,0)

    def test_release_does_not_send_a_still_closing_rate_limited_target(self):
        h=self.held_gripper()
        self.assertEqual(h.update(14,16,.4,opening_request=25),16)
        self.assertIsNone(h.hold)

    def test_small_opening_works_at_slow_native_inference_rate(self):
        h=self.held_gripper()
        h.update(16.7,16,.4)
        self.assertEqual(h.update(16.7,16,.8),16.7)
        self.assertEqual(h.release_count,1)

    def test_opening_completes_before_reclosing_prediction_is_accepted(self):
        h=self.held_gripper()
        h.update(18,16,1,opening_request=22)
        self.assertEqual(h.release_target,22)
        self.assertEqual(h.update(0,17,1.05),22)
        self.assertEqual(h.update(0,20,1.15),22)
        self.assertEqual(h.update(0,22,1.2),22)
        self.assertEqual(h.update(0,22,1.35),22)
        self.assertIsNone(h.release_target)
        self.assertEqual(h.last_event,'opening_completed')
        self.assertEqual(h.update(0,22,1.4),0)

    def test_contact_release_does_not_complete_before_jaws_reach_target(self):
        h=self.held_gripper()
        h.update(18,16,1,opening_request=22)
        self.assertEqual(h.update(0,17,3),22)
        self.assertEqual(h.release_target,22)

    def test_further_opening_extends_target_but_closing_does_not_shrink_it(self):
        h=self.held_gripper()
        h.update(18,16,1,opening_request=22)
        self.assertEqual(h.update(0,17,1.1,opening_request=25),25)
        self.assertEqual(h.update(0,18,1.2,opening_request=0),25)

    def test_native_endpoint_clamping_preserves_contact_hold(self):
        self.assertEqual(native_gripper_goal(-.05),0)
        self.assertEqual(native_gripper_goal(100.05),100)
        self.assertEqual(native_gripper_goal(15.2),15.2)
        h=GripperContactHold()
        for i in range(6):
            goal=h.update(native_gripper_goal(-.05),16,i*.4,opening_request=-.05)
        self.assertEqual(goal,15.5)
        self.assertEqual(h.contact_count,1)
        with self.assertRaises(ValueError):native_gripper_goal(math.nan)

    def test_small_gripper_endpoint_error_seeds_valid_goal(self):
        cal={'gripper':{'range_min':1031,'range_max':2496}}
        self.assertEqual(startup_raw_goals({'gripper':1028},cal),{'gripper':1031})
        self.assertEqual(cal['gripper']['range_min'],1031)
        for value in (1026,2497):
            with self.assertRaises(RuntimeError):
                startup_raw_goals({'gripper':value},cal)
        with self.assertRaises(RuntimeError):
            startup_raw_goals({'shoulder_pan':1028},{'shoulder_pan':cal['gripper']})

    def test_stalled_closure_holds_near_contact_and_opens_on_request(self):
        h = GripperContactHold()
        for i in range(10):
            command = h.update(0, 15.36, i/30)
        self.assertAlmostEqual(command, 14.86)
        self.assertEqual(h.contact_count, 1)
        self.assertAlmostEqual(h.update(0, 15.36, .4), 14.86)
        self.assertEqual(h.update(25, 15.36, .5), 25)
        self.assertIsNone(h.hold)

    def test_moving_closure_is_not_mistaken_for_contact(self):
        h = GripperContactHold()
        for i in range(40):
            observed = 70-i
            self.assertEqual(h.update(observed-5, observed, i/30), observed-5)
        self.assertIsNone(h.hold)

    def test_opening_and_small_tracking_gap_do_not_latch(self):
        h = GripperContactHold()
        for i in range(30):
            self.assertEqual(h.update(20, 15, i/30), 20)
            self.assertEqual(h.update(14, 15, i/30+.001), 14)
        self.assertIsNone(h.hold)

    def test_nonfinite_inputs_are_rejected(self):
        for args in [(math.nan, 15, 0), (0, math.inf, 0), (0, 15, math.nan)]:
            with self.assertRaises(ValueError):
                GripperContactHold().update(*args)

    def test_opening_intent_releases_even_when_command_is_rate_limited(self):
        h = GripperContactHold()
        for i in range(10):
            h.update(0,15,i/30)
        self.assertIsNotNone(h.hold)
        self.assertEqual(h.update(16.5,15,.4,opening_request=25),16.5)
        self.assertIsNone(h.hold)


if __name__ == '__main__':
    unittest.main()
