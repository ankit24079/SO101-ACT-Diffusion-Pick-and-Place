"""Passive recording around native LeRobot observation/action calls.

No motor calls are added. JPEG writes run on a bounded worker queue; official
dataset encoding and validation run only after follower torque-off verification.
"""
import json
import queue
import shutil
import threading
import time
from pathlib import Path

import numpy as np
from PIL import Image

from test_episode import NAMES, TASK, validate, write_episode


class OfficialEpisode:
    def __init__(self, session_path, fps=30):
        if shutil.disk_usage('/workspace/datasets').free < 5*1024**3:
            raise RuntimeError('Less than 5 GiB free; no recording started')
        self.fps = fps
        self.root = Path('/workspace/datasets')/f'cube-cup-official-{time.time_ns()}'
        self.spool = Path('/workspace/outputs/test-recordings')/(self.root.name+'-frames')
        self.spool.mkdir(parents=True, exist_ok=False)
        self.session_path = str(session_path)
        self.jobs = queue.Queue(maxsize=30)
        self.frames = []
        self.error = None
        self.started = None
        self.last_sample = None
        self.accepted = 0
        self.timestamp_pair_misses = 0
        self.control_samples = 0
        self.control_first = self.control_last = None
        self.max_control_gap = 0
        self.worker = threading.Thread(target=self._write, daemon=True)
        self.worker.start()

    def check(self):
        if self.error:
            raise RuntimeError(f'Recording worker failed: {self.error}')

    def offer(self, observation, action, observed_at, captures):
        self.check()
        self.control_samples += 1
        if self.control_first is None:
            self.control_first = observed_at
        if self.control_last is not None:
            self.max_control_gap = max(self.max_control_gap, observed_at-self.control_last)
        self.control_last = observed_at
        if self.last_sample is not None and observed_at-self.last_sample < 1/self.fps:
            return
        if captures is None:
            self.timestamp_pair_misses += 1
            return
        if self.started is None:
            self.started = observed_at
        ages = {name: (observed_at-captures[name])*1000 for name in ('workspace', 'wrist')}
        if any(age < 0 or age > 500 for age in ages.values()):
            raise RuntimeError(f'Camera timestamp invalid or older than native 500 ms limit: {ages}')
        frame = {
            'observation.state': np.array([observation[f'{n}.pos'] for n in NAMES], dtype=np.float32),
            'action': np.array([action[f'{n}.pos'] for n in NAMES], dtype=np.float32),
            'observation.elapsed_time': np.array([observed_at-self.started], dtype=np.float64),
            'observation.camera_time': np.array([captures[n]-self.started for n in ('workspace', 'wrist')], dtype=np.float64),
            'task': TASK,
        }
        images = {name: observation[name].copy() for name in ('workspace', 'wrist')}
        try:
            self.jobs.put_nowait((self.accepted, frame, images))
        except queue.Full:
            raise RuntimeError('Recording disk worker fell behind; bounded queue full') from None
        self.accepted += 1
        self.last_sample = observed_at

    def _write(self):
        while True:
            job = self.jobs.get()
            try:
                if job is None:
                    return
                if self.error:
                    continue
                index, frame, images = job
                if shutil.disk_usage(self.spool).free < 2*1024**3:
                    raise RuntimeError('Less than 2 GiB free; stop recording')
                paths = {}
                for name, image in images.items():
                    path = self.spool/f'{name}-{index:08d}.jpg'
                    Image.fromarray(image).save(path, quality=95)
                    paths[name] = str(path)
                frame['_image_paths'] = paths
                with (self.spool/'frames.jsonl').open('a') as stream:
                    stream.write(json.dumps({k: v.tolist() if isinstance(v, np.ndarray) else v
                                             for k, v in frame.items()})+'\n')
                self.frames.append(frame)
            except Exception as error:
                self.error = str(error)
            finally:
                self.jobs.task_done()

    def finish(self, outcome, torque_off):
        # Called only after motor cleanup: draining/encoding must not delay stop.
        self.jobs.put(None)
        self.worker.join()
        context = {
            'root': str(self.root), 'task': TASK, 'frames': len(self.frames),
            'accepted_frames': self.accepted, 'stop_reason': outcome,
            'torque_off_verified': torque_off, 'worker_error': self.error,
            'official_session': self.session_path, 'fps_requested': self.fps,
            'control': 'unaltered LeRobot 0.6.1 teleop_loop; passive recording proxy',
            'action_source': 'return value of official follower.send_action',
            'arm_position_units': 'degrees', 'gripper_units': 'percent openness 0..100',
            'camera_timestamp_source': 'native latest_timestamp matched by image identity',
            'timestamp_pair_misses': self.timestamp_pair_misses,
            'control_samples': self.control_samples,
            'measured_control_hz': ((self.control_samples-1)/(self.control_last-self.control_first)
                                    if self.control_samples > 1 and self.control_last > self.control_first else None),
            'max_control_gap_ms': self.max_control_gap*1000,
            'voltage_telemetry': 'preflight register audit only; no extra motor reads in control loop',
            'task_success': 'pending visual and user review', 'training_approved': False,
        }
        sidecar = self.spool.parent/(self.root.name+'.json')
        sidecar.write_text(json.dumps(context, indent=2)+'\n')
        if not torque_off or len(self.frames) < 2:
            print(f'Dataset encoding skipped; spooled data and context preserved: {sidecar}', flush=True)
            return
        print(f'Torque OFF. Encoding recorded episode: {self.root}', flush=True)
        write_episode(self.root, self.frames, fps=self.fps)
        (self.root/'recording_context.json').write_text(json.dumps(context, indent=2)+'\n')
        validate(self.root, fps=self.fps)
        self.frames.clear()
        print('Official-control episode saved and structurally validated. Visual/task review still required.', flush=True)


class RecordedFollower:
    """Delegate all control to the real robot; observe existing calls only."""
    def __init__(self, robot, recorder):
        self.robot = robot
        self.recorder = recorder

    def __getattr__(self, name):
        return getattr(self.robot, name)

    def get_observation(self):
        self.recorder.check()
        observation = self.robot.get_observation()
        captures = {}
        for name, camera in self.robot.cameras.items():
            with camera.frame_lock:
                if camera.latest_frame is not observation[name] or camera.latest_timestamp is None:
                    captures = None
                    break
                # Native camera timestamps use perf_counter; dataset times use
                # monotonic. Convert using elapsed age rather than clock epoch.
                captures[name] = time.monotonic()-(time.perf_counter()-camera.latest_timestamp)
        self.observation = observation
        self.observed_at = time.monotonic()
        self.captures = captures
        return observation

    def send_action(self, action):
        sent = self.robot.send_action(action)
        self.recorder.offer(self.observation, sent, self.observed_at, self.captures)
        return sent
