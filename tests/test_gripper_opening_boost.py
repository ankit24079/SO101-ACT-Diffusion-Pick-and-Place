from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from gripper_contact_hold import OpeningBoostGripperContactHold


class OpeningBoostTest(unittest.TestCase):
    def held(self, observed=16.4):
        h = OpeningBoostGripperContactHold()
        for i in range(10):
            h.update(0, observed, i/30)
        self.assertIsNotNone(h.hold)
        return h

    def test_accepted_release_boosts_and_completes_before_reclosing(self):
        h = self.held()
        for t in (1., 1.04):
            self.assertAlmostEqual(h.update(16.6,16.4,t),15.9)
        h.update(16.6,16.4,1.09,opening_request=17)
        self.assertEqual(h.release_target,30)
        self.assertEqual(h.update(0,18,1.15),30)
        h.update(0,30,1.4)
        h.update(0,30,1.51)
        self.assertIsNone(h.release_target)

    def test_closing_and_subthreshold_jitter_do_not_weaken_grip(self):
        h = self.held()
        for i in range(30):
            self.assertAlmostEqual(h.update(0,16.4,1+i/30),15.9)
        h.update(16.6,16.4,3.)
        h.update(0,16.4,3.04)
        self.assertIsNotNone(h.hold)
        self.assertIsNone(h.release_target)

    def test_strong_opening_and_endpoint_clamp(self):
        h = self.held()
        h.update(25,16.4,1)
        self.assertEqual(h.release_target,30)
        h = self.held(97)
        h.update(100,97,1)
        self.assertEqual(h.release_target,100)

    def test_recorded_17_percent_opening_is_boosted_before_detection(self):
        h = self.held(16.38225255972696)
        h.update(16,16.38225255972696,9.45,opening_request=17.1)
        self.assertEqual(h.release_target,30)
        self.assertIsNone(h.hold)

    def test_17_percent_is_not_boosted_when_it_means_closing(self):
        h = self.held(18)
        self.assertEqual(h.update(17,18,1,opening_request=17),17.5)
        self.assertIsNone(h.release_target)

    def test_minimum_release_opening_is_30_percent(self):
        h = self.held(14)
        h.update(14.6,14,1,opening_request=14.6)
        self.assertEqual(h.release_target,30)

    def test_16_percent_does_not_trigger_a_fixed_threshold(self):
        h = self.held(16.45)
        self.assertAlmostEqual(h.update(16,16.45,1,opening_request=16),15.95)
        self.assertIsNone(h.release_target)

    def test_first_attempt_gets_clearance_without_later_wider_model_request(self):
        h = self.held(16.109215017064844)
        h.update(16,16.109215017064844,10.91,opening_request=16.74)
        self.assertEqual(h.release_target,30)
        # Recorded first-attempt plateau: 20.55% must not be treated as done.
        for t in (11.3,12.,14.):
            self.assertEqual(h.update(0,20.54607508532423,t,opening_request=0),30)
            self.assertIsNotNone(h.release_target)
        h.update(0,30,14.2)
        h.update(0,30,14.31)
        self.assertIsNone(h.release_target)

    def test_recorded_29_49_percent_plateau_completes_30_percent_opening(self):
        h = self.held(16.18)
        h.update(16,16.18,1,opening_request=17)
        self.assertEqual(h.release_target,30)
        # Still require substantial jaw travel; partial 21% opening is insufficient.
        h.update(0,21,1.3)
        self.assertIsNotNone(h.release_target)
        h.update(0,29.488054607508534,1.4)
        h.update(0,29.488054607508534,1.51)
        self.assertIsNone(h.release_target)
        self.assertEqual(h.last_event,'opening_completed')


if __name__ == '__main__':
    unittest.main()
