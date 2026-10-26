import importlib.util
import json
import queue
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

SCRIPT = Path(__file__).resolve().parents[1]/'scripts/official_episode.py'
NAMES = ['shoulder_pan', 'shoulder_lift', 'elbow_flex', 'wrist_flex', 'wrist_roll', 'gripper']


class RecorderTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        fake = types.ModuleType('test_episode')
        fake.NAMES = NAMES
        fake.TASK = 'Pick up the cube and place it in the cup.'
        fake.write_episode = Mock(side_effect=lambda root, frames, fps: root.mkdir(parents=True))
        fake.validate = Mock()
        with patch.dict(sys.modules, {'test_episode': fake}):
            spec = importlib.util.spec_from_file_location('official_episode_tested', SCRIPT)
            self.mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.mod)
        self.fake = fake
        real_path = Path
        def local_path(value):
            return base/str(value).removeprefix('/workspace/')
        self.writer_threads = []
        def encode(image):
            def save(path, **kwargs):
                self.writer_threads.append(threading.get_ident())
                real_path(path).write_bytes(b'test image')
            return types.SimpleNamespace(save=save)
        for context in [patch.object(self.mod, 'Path', side_effect=local_path),
                        patch.object(self.mod.shutil, 'disk_usage', return_value=types.SimpleNamespace(free=10*1024**3)),
                        patch.object(self.mod.Image, 'fromarray', side_effect=encode)]:
            context.__enter__()
            self.addCleanup(context.__exit__, None, None, None)
        self.rec = self.mod.OfficialEpisode('session.json')
        self.obs = {f'{n}.pos': float(i) for i, n in enumerate(NAMES)}
        self.obs.update({name: np.zeros((4, 4, 3), dtype=np.uint8) for name in ('workspace', 'wrist')})
        self.action = {f'{n}.pos': float(i+1) for i, n in enumerate(NAMES)}
        self.addCleanup(self.stop_worker)

    def stop_worker(self):
        if self.rec.worker.is_alive():
            self.rec.jobs.put(None)
            self.rec.worker.join(timeout=2)

    def test_background_writes_preserve_sent_actions_and_times(self):
        for now in [10., 10.04]:
            self.rec.offer(self.obs, self.action, now, {'workspace': now-.02, 'wrist': now-.03})
        self.rec.finish('operator_stopped', True)
        self.assertEqual(self.rec.accepted, 2)
        self.assertTrue(all(t != threading.get_ident() for t in self.writer_threads))
        self.assertEqual(self.fake.write_episode.call_args.kwargs['fps'], 30)
        context = json.loads((self.rec.root/'recording_context.json').read_text())
        self.assertEqual(context['arm_position_units'], 'degrees')
        self.assertEqual(context['frames'], 2)
        row = json.loads((self.rec.spool/'frames.jsonl').read_text().splitlines()[0])
        self.assertEqual(row['action'], [float(i+1) for i in range(6)])
        self.assertAlmostEqual(row['observation.camera_time'][0], -.02)

    def test_no_encoding_without_verified_torque_off(self):
        self.rec.offer(self.obs, self.action, 10., {'workspace': 9.99, 'wrist': 9.99})
        self.rec.finish('error', False)
        self.fake.write_episode.assert_not_called()

    def test_sampling_and_backpressure(self):
        self.rec.offer(self.obs, self.action, 10., {'workspace': 9.99, 'wrist': 9.99})
        self.rec.offer(self.obs, self.action, 10.01, {'workspace': 10., 'wrist': 10.})
        self.assertEqual(self.rec.accepted, 1)
        with patch.object(self.rec.jobs, 'put_nowait', side_effect=queue.Full):
            with self.assertRaisesRegex(RuntimeError, 'queue full'):
                self.rec.offer(self.obs, self.action, 10.04, {'workspace': 10.03, 'wrist': 10.03})

    def test_passive_proxy_returns_native_action_unchanged(self):
        cam = lambda image: types.SimpleNamespace(frame_lock=threading.Lock(), latest_frame=image,
                                                  latest_timestamp=self.mod.time.perf_counter())
        robot = Mock()
        robot.cameras = {name: cam(self.obs[name]) for name in ('workspace', 'wrist')}
        robot.get_observation.return_value = self.obs
        robot.send_action.return_value = self.action
        recorder = Mock()
        proxy = self.mod.RecordedFollower(robot, recorder)
        self.assertIs(proxy.get_observation(), self.obs)
        self.assertIs(proxy.send_action({'requested': 1}), self.action)
        robot.send_action.assert_called_once_with({'requested': 1})
        self.assertIs(recorder.offer.call_args.args[1], self.action)


if __name__ == '__main__':
    unittest.main()
