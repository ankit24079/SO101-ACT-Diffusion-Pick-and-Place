from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from gripper_contact_hold import InitialGripperContactHold


class InitialHoldTest(unittest.TestCase):
    def test_original_hold_and_release_threshold_are_restored(self):
        h=InitialGripperContactHold()
        for i in range(10):
            self.assertAlmostEqual(h.update(0,16,i/30),15.5 if i>=5 else 0)
        for i in range(10):
            self.assertEqual(h.update(18,16,1+i/30,opening_request=18),15.5)
        self.assertEqual(h.update(18.5,16,2,opening_request=18.5),18.5)
        self.assertIsNone(h.hold)
        self.assertIsNone(h.release_target)
        self.assertEqual(h.release_count,1)
        # The opening-completion experiment is deliberately not active.
        self.assertEqual(h.update(0,16,2.1),0)

    def test_original_opening_intent_works_with_rate_limited_target(self):
        h=InitialGripperContactHold()
        for i in range(10):h.update(0,16,i/30)
        self.assertEqual(h.update(16,16,1,opening_request=25),16)
        self.assertIsNone(h.hold)


if __name__=='__main__':unittest.main()
