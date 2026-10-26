from pathlib import Path
import sys
import unittest
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from act_temporal_ensemble import TimeAlignedTemporalEnsembler


class TemporalEnsembleTest(unittest.TestCase):
    def test_overlaps_use_execution_time_not_arrival_count(self):
        e=TimeAlignedTemporalEnsembler(0,30)
        e.add(0,np.repeat(np.arange(100)[:,None],6,axis=1))
        e.add(.4,np.repeat((1000+np.arange(100))[:,None],6,axis=1))
        a,n=e.action(.8)
        self.assertEqual(n,2)
        np.testing.assert_allclose(a,(24+1012)/2)

    def test_matches_native_oldest_first_exponential_formula(self):
        e=TimeAlignedTemporalEnsembler(.01,30)
        e.add(0,np.full((100,6),10))
        e.add(1/30,np.full((100,6),20))
        a,n=e.action(2/30)
        expected=(10+20*np.exp(-.01))/(1+np.exp(-.01))
        np.testing.assert_allclose(a,expected)
        self.assertEqual(n,2)

    def test_expired_chunks_are_discarded_and_future_chunks_not_used(self):
        e=TimeAlignedTemporalEnsembler(0,30)
        e.add(0,np.zeros((10,6)))
        e.add(.3,np.full((10,6),5))
        a,n=e.action(.4)
        np.testing.assert_allclose(a,5)
        self.assertEqual(n,1)
        with self.assertRaises(RuntimeError):e.action(2)

    def test_bad_or_duplicate_predictions_are_rejected(self):
        e=TimeAlignedTemporalEnsembler()
        with self.assertRaises(ValueError):e.add(0,np.full((100,6),np.nan))
        e.add(0,np.zeros((100,6)))
        with self.assertRaises(ValueError):e.add(0,np.zeros((100,6)))

    def test_newer_weighting_advances_coordinated_opening_transition(self):
        original=TimeAlignedTemporalEnsembler(.01,30)
        responsive=TimeAlignedTemporalEnsembler(-.5,30)
        closing=np.array([0,10,20,30,40,5.])
        releasing=np.array([10,20,30,40,50,25.])
        for e in (original,responsive):
            for i,action in enumerate((closing,closing,releasing,releasing)):
                e.add(i*.4,np.tile(action,(100,1)))
        old,_=original.action(1.3)
        new,_=responsive.action(1.3)
        # Contradictory older closure must not dominate two newer release plans.
        self.assertLess(old[5],16.5)
        self.assertGreater(new[5],16.5)
        # The same mixing advances every arm joint, not only the gripper.
        arm_fraction=(new[:5]-closing[:5])/(releasing[:5]-closing[:5])
        grip_fraction=(new[5]-closing[5])/(releasing[5]-closing[5])
        np.testing.assert_allclose(arm_fraction,grip_fraction)
        self.assertTrue(np.all(new>=np.minimum(closing,releasing)))
        self.assertTrue(np.all(new<=np.maximum(closing,releasing)))


if __name__=='__main__':unittest.main()
