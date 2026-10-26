from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from gripper_contact_hold import CloseAfterReleaseGripperHold


class CloseAfterReleaseTest(unittest.TestCase):
    def closing(self):
        h = CloseAfterReleaseGripperHold()
        for i in range(10):h.update(0,16,i/30)
        h.update(16,16,1,opening_request=17)
        self.assertEqual(h.release_target,30)
        h.update(0,29.49,1.4,opening_request=0)
        h.update(0,29.49,1.51,opening_request=0)
        self.assertEqual(h.post_release_phase,'closing')
        return h

    def closed(self):
        h = self.closing()
        for i,observed in enumerate((25,20,15,10,5,.5,.5,.5,.5)):
            h.update(30,observed,1.6+i*.04,opening_request=30)
        self.assertEqual(h.post_release_phase,'closed')
        return h

    def test_closes_despite_model_remaining_open_after_release(self):
        h = self.closing()
        self.assertEqual(h.update(30,25,1.6,opening_request=30),0)
        h = self.closed()
        self.assertEqual(h.update(30,.5,3,opening_request=30),0)
        self.assertEqual(h.post_release_phase,'closed')

    def test_does_not_close_before_opening_is_completed(self):
        h = CloseAfterReleaseGripperHold()
        for i in range(10):h.update(0,16,i/30)
        h.update(16,16,1,opening_request=17)
        self.assertEqual(h.update(0,21,2,opening_request=0),30)
        self.assertIsNone(h.post_release_phase)

    def test_obstruction_is_detected_without_forcing_full_closure(self):
        h = self.closing()
        for i in range(10):
            result=h.update(0,16,1.6+i/30,opening_request=0)
            if h.last_event=='post_release_close_obstructed':break
        self.assertEqual(h.last_event,'post_release_close_obstructed')
        self.assertEqual(result,15.5)
        self.assertIsNotNone(h.hold)
        self.assertIsNone(h.post_release_phase)

    def test_fresh_close_then_open_request_can_begin_next_pickup(self):
        h = self.closed()
        self.assertEqual(h.update(25,.5,3,opening_request=25),0)
        self.assertEqual(h.update(0,.5,3.1,opening_request=0),0)
        self.assertEqual(h.update(25,.5,3.2,opening_request=25),25)
        self.assertIsNone(h.post_release_phase)
        self.assertEqual(h.last_event,'next_pickup_opening')

    def test_startup_opening_is_not_overridden(self):
        h = CloseAfterReleaseGripperHold()
        self.assertEqual(h.update(20,0,0,opening_request=20),20)
        self.assertIsNone(h.post_release_phase)


if __name__=='__main__':unittest.main()
