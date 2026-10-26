"""Offline validation must never mix episodes or use future predictions."""
import importlib.util
from pathlib import Path
import unittest

import numpy as np

spec = importlib.util.spec_from_file_location('temporal_validation',
    Path(__file__).resolve().parents[1]/'training/compare_temporal_policies.py')
comparison = importlib.util.module_from_spec(spec)
spec.loader.exec_module(comparison)


class TemporalValidationTest(unittest.TestCase):
    def test_aligns_action_offsets_and_resets_between_episodes(self):
        chunks = np.zeros((4, 3, 6))
        chunks[0, 1] = 4
        chunks[1, 0] = 8
        chunks[2, 0] = 100
        chunks[2, 1] = 110
        chunks[3, 0] = 120
        result = comparison.replay(chunks, [0, 0, 1, 1], [0, 1, 0, 1], 0)
        np.testing.assert_allclose(result[:, 0], [0, 6, 100, 115])

    def test_future_prediction_cannot_change_current_action(self):
        chunks = np.zeros((3, 3, 6))
        first = comparison.replay(chunks, [0, 0, 0], [0, 1, 2], -.5)
        chunks[2] = 10000
        changed = comparison.replay(chunks, [0, 0, 0], [0, 1, 2], -.5)
        np.testing.assert_array_equal(first[:2], changed[:2])

    def test_sparse_cadence_ignores_unavailable_predictions(self):
        chunks = np.ones((4, 4, 6))
        chunks[1] = 10000
        chunks[2] = 3
        result = comparison.replay(chunks, [0]*4, range(4), 0, stride=2)
        np.testing.assert_allclose(result[:, 0], [1, 1, 2, 2])

    def test_native_queue_advances_and_resets_at_episode_boundary(self):
        chunks = np.tile(np.arange(3)[None, :, None], (4, 1, 6)).astype(float)
        chunks[2:] += 10
        result = comparison.queued(chunks, [0, 0, 1, 1], [0, 1, 0, 1], 2)
        np.testing.assert_allclose(result[:, 0], [0, 1, 10, 11])


if __name__ == '__main__':
    unittest.main()
