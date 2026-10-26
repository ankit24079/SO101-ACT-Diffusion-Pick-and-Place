"""Pure control-policy tests; no LeRobot, serial access, or motor commands."""
import importlib.util
import math
from pathlib import Path
import sys
import unittest

path = Path(__file__).resolve().parents[1]/'scripts/gripper_contact.py'
spec = importlib.util.spec_from_file_location('gripper_contact',path)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
GripperContactHold = module.GripperContactHold


class ContactTests(unittest.TestCase):
    def latch(self):
        grip=GripperContactHold()
        state=None
        for i in range(6):
            target,state=grip.update(0,14,16,i*.1)
        self.assertTrue(state['holding'])
        self.assertEqual(target,15)
        return grip

    def test_free_closure_and_opening_do_not_latch(self):
        grip=GripperContactHold()
        for i in range(30):
            measured=40-i*.5
            target,state=grip.update(0,measured-.5,measured,i*.1)
            self.assertFalse(state['holding'])
            self.assertEqual(target,0)
        for i in range(30,60):
            measured=25+(i-30)*.5
            target,state=grip.update(90,measured+.5,measured,i*.1)
            self.assertFalse(state['holding'])
            self.assertEqual(target,90)

    def test_contact_backs_off_and_does_not_accept_more_squeeze(self):
        grip=self.latch()
        for i,requested in enumerate([0,0,5,0,10,0],6):
            target,state=grip.update(requested,15,16,i*.1)
            self.assertEqual(target,15)
            self.assertTrue(state['holding'])
            self.assertEqual(state['release_above'],17)

    def test_opening_releases_and_regrip_can_latch_again(self):
        grip=self.latch()
        target,state=grip.update(18,15,16,.6)
        self.assertEqual(target,18)
        self.assertEqual(state['event'],'release_requested')
        self.assertFalse(state['holding'])
        for i in range(7,13):
            target,state=grip.update(0,14,16,i*.1)
        self.assertTrue(state['holding'])

    def test_short_lag_does_not_latch(self):
        grip=GripperContactHold()
        for i in range(3):
            _,state=grip.update(0,14,16,i*.1)
            self.assertFalse(state['holding'])
        _,state=grip.update(0,15.5,16,.3)
        self.assertFalse(state['holding'])
        self.assertIsNone(grip.candidate_since)

    def test_moving_jaws_do_not_count_as_stationary_contact(self):
        grip=GripperContactHold()
        for i in range(20):
            observed=40-i*.5
            _,state=grip.update(0,observed-2,observed,i*.1)
            self.assertFalse(state['holding'])

    def test_empty_closed_endpoint_not_contact(self):
        grip=GripperContactHold()
        for i in range(20):
            target,state=grip.update(0,0,.4,i*.1)
            self.assertEqual(target,0)
            self.assertFalse(state['holding'])

    def test_invalid_sensor_values_fail_closed(self):
        for value in (math.nan,math.inf):
            with self.assertRaises(ValueError):GripperContactHold().update(0,0,value,0)
        grip=GripperContactHold();grip.update(0,0,0,1)
        with self.assertRaises(ValueError):grip.update(0,0,0,1)

    def test_hold_can_reach_fully_open_to_release(self):
        grip=GripperContactHold(hold_target=99.5)
        target,state=grip.update(100,99.5,99.5,0)
        self.assertEqual(target,100)
        self.assertFalse(state['holding'])


if __name__=='__main__':unittest.main()
