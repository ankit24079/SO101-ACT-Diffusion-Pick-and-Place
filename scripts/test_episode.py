"""One local LeRobot test episode; called by guarded teleop after torque is off."""
import json
import shutil
import time
from pathlib import Path

import av
import numpy as np
from PIL import Image
from lerobot.configs import RGBEncoderConfig
from lerobot.datasets.lerobot_dataset import LeRobotDataset

NAMES = ['shoulder_pan', 'shoulder_lift', 'elbow_flex', 'wrist_flex', 'wrist_roll', 'gripper']
TASK = 'Pick up the cube and place it in the cup.'
FPS = 10


def features():
    return {
        'observation.state': {'dtype': 'float32', 'shape': (6,), 'names': NAMES},
        'action': {'dtype': 'float32', 'shape': (6,), 'names': NAMES},
        'observation.elapsed_time': {'dtype': 'float64', 'shape': (1,), 'names': ['measured_seconds']},
        'observation.camera_time': {'dtype': 'float64', 'shape': (2,), 'names': ['workspace', 'wrist']},
        **{f'observation.images.{name}': {'dtype': 'video', 'shape': (480, 640, 3), 'names': ['height', 'width', 'channels']} for name in ('workspace', 'wrist')},
    }


def write_episode(root, frames, fps=FPS):
    if root.exists():
        raise RuntimeError(f'Refusing to overwrite dataset: {root}')
    dataset = LeRobotDataset.create(
        repo_id='local/' + root.name, root=root, fps=fps, features=features(),
        robot_type='so101_follower', use_videos=True,
        rgb_encoder=RGBEncoderConfig(vcodec='h264', crf=23, preset='fast'),
        image_writer_threads=2,
    )
    try:
        for frame in frames:
            data = dict(frame)
            paths = data.pop('_image_paths', {})
            for name, path in paths.items():
                with Image.open(path) as image:
                    data[f'observation.images.{name}'] = np.asarray(image.convert('RGB')).copy()
            dataset.add_frame(data)
        dataset.save_episode(parallel_encoding=False)
    finally:
        dataset.finalize()


def validate(root, fps=FPS):
    import pyarrow.parquet as pq
    info = json.loads((root/'meta/info.json').read_text())
    paths = sorted((root/'data').rglob('*.parquet'))
    tables = [pq.read_table(path).to_pydict() for path in paths]
    count = sum(len(t['timestamp']) for t in tables)
    assert info['total_episodes'] == 1 and info['total_frames'] == count and count > 1
    assert info['fps'] == fps
    state = np.array([x for t in tables for x in t['observation.state']])
    action = np.array([x for t in tables for x in t['action']])
    timestamps = np.array([x for t in tables for x in t['timestamp']])
    # LeRobot serializes shape-(1,) numeric features as Parquet scalars.
    # Reshape also accepts list-valued singleton columns from older layouts.
    actual = np.asarray(
        [x for t in tables for x in t['observation.elapsed_time']], dtype=np.float64,
    ).reshape(count)
    capture = np.array([x for t in tables for x in t['observation.camera_time']])
    task_tables = list((root/'meta').glob('tasks.parquet'))
    assert task_tables and TASK in str(pq.read_table(task_tables[0]).to_pydict()), 'Task description missing'
    assert state.shape == action.shape == (count, 6)
    assert np.isfinite(state).all() and np.isfinite(action).all()
    assert np.allclose(timestamps, np.arange(count)/fps, atol=1e-5)
    assert (np.diff(actual)>0).all()
    ages = actual[:, None]-capture
    videos = {}
    for name in ('workspace', 'wrist'):
        files = list((root/'videos'/f'observation.images.{name}').rglob('*.mp4'))
        assert len(files) == 1, files
        previews = {}
        decoded = 0
        with av.open(str(files[0])) as container:
            for index, frame in enumerate(container.decode(video=0)):
                assert (frame.width, frame.height) == (640, 480)
                if index in {0, count//2, count-1}:
                    path = root.parent / (root.name + '-review') / f'{name}-{index:05d}.jpg'
                    path.parent.mkdir(parents=True, exist_ok=True)
                    frame.to_image().save(path)
                    previews[str(index)] = str(path)
                decoded += 1
        assert decoded == count, (name, decoded, count)
        videos[name] = {'decoded_frames': decoded, 'previews': previews}
    # Verify the official reader can reopen the local dataset and decode images.
    reader = LeRobotDataset(repo_id='local/'+root.name, root=root, video_backend='pyav')
    assert len(reader) == count
    for index in (0, count//2, count-1):
        frame = reader[index]
        for name in ('workspace', 'wrist'):
            assert tuple(frame[f'observation.images.{name}'].shape) == (3, 480, 640)
    dt = np.diff(actual)
    report = {
        'root': str(root), 'task': TASK, 'episodes': 1, 'frames': count,
        'nominal_fps': fps, 'nominal_duration_seconds': count/fps,
        'measured_duration_seconds': float(actual[-1]-actual[0]),
        'measured_sample_fps': float((count-1)/(actual[-1]-actual[0])),
        'max_sample_gap_ms': float(max(dt)*1000),
        'sample_intervals_over_150ms': int(sum(dt>.15)),
        'max_camera_age_ms': dict(zip(('workspace', 'wrist'), map(float, ages.max(axis=0)*1000))),
        'reused_camera_frames': {name: int(sum(np.diff(capture[:,i])==0)) for i,name in enumerate(('workspace','wrist'))},
        'state_shape': list(state.shape), 'action_shape': list(action.shape),
        'videos': videos, 'official_reader_reopened': True,
        'note': 'Nominal timestamps are frame_index/fps; actual elapsed/camera delivery times are extra features. No hardware synchronization or exact dropped-frame counter.',
    }
    review = root.parent/(root.name+'-review')
    review.mkdir(parents=True, exist_ok=True)
    (review/'validation.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2),flush=True)
    return report


def smoke_test(fps=FPS):
    root = Path('/workspace/outputs/recording-smoke') / ('synthetic-'+str(time.time_ns()))
    frames = []
    for i in range(3):
        frames.append({
            'observation.state': np.zeros(6,dtype=np.float32), 'action': np.zeros(6,dtype=np.float32),
            'observation.elapsed_time': np.array([i/fps],dtype=np.float64),
            'observation.camera_time': np.array([i/fps,i/fps],dtype=np.float64),
            **{f'observation.images.{name}': np.full((480,640,3),i*60,dtype=np.uint8) for name in ('workspace','wrist')},
            'task': TASK,
        })
    write_episode(root, frames, fps=fps)
    validate(root, fps=fps)
    print('Synthetic dataset write/read/video check passed. No hardware accessed.',flush=True)


class TestEpisode:
    def __init__(self):
        if shutil.disk_usage('/workspace/datasets').free < 5*1024**3:
            raise RuntimeError('Less than 5 GiB free; stop before recording')
        self.root = Path('/workspace/datasets') / ('cube-cup-test-'+str(time.time_ns()))
        self.frames = []
        self.start = None
        self.control_mapping = {'mode': 'not_started'}
        self.voltage_log_path = None
        self.spool = Path('/workspace/outputs/test-recordings') / (self.root.name+'-frames')
        self.spool.mkdir(parents=True, exist_ok=False)

    def add(self, state, action, camera):
        images, times = camera.snapshot()
        now = time.monotonic()
        if self.start is None:
            self.start = now
        stale = {name: round((now-t)*1000, 1)
                 for name, t in zip(('workspace', 'wrist'), times) if now-t > .2}
        if stale:
            raise RuntimeError(f'Camera frame over 200 ms old: {stale} (ages in ms); stop recording')
        if shutil.disk_usage(self.spool).free < 2*1024**3:
            raise RuntimeError('Less than 2 GiB free; stop to preserve data and allow encoding')
        paths = {}
        for name, image in images.items():
            path = self.spool / f'{name}-{len(self.frames):08d}.jpg'
            Image.fromarray(image).save(path, quality=95)
            paths[name] = str(path)
        frame = {
            'observation.state': np.array([state[n] for n in NAMES],dtype=np.float32),
            'action': np.array([action[n] for n in NAMES],dtype=np.float32),
            'observation.elapsed_time': np.array([now-self.start],dtype=np.float64),
            'observation.camera_time': np.array([t-self.start for t in times],dtype=np.float64),
            '_image_paths': paths,
            'task': TASK,
        }
        self.frames.append(frame)
        # Preserve a replayable journal alongside disk-spooled images.
        row = {key: value.tolist() if isinstance(value, np.ndarray) else value for key, value in frame.items()}
        with (self.spool/'frames.jsonl').open('a') as stream:
            stream.write(json.dumps(row)+'\n')

    def finish(self, outcome, torque_off, torque_attempted=True):
        # Save test metadata even when no episode is available or saving is blocked.
        sidecar = Path('/workspace/outputs/test-recordings') / (self.root.name+'.json')
        sidecar.parent.mkdir(parents=True,exist_ok=True)
        metadata = {'root':str(self.root),'task':TASK,'frames':len(self.frames),'stop_reason':outcome,'torque_enable_attempted':torque_attempted,'torque_off_verified':torque_off,'task_success':'pending user/visual review','training_approved':False,'control_mapping':self.control_mapping,'voltage_log_path':self.voltage_log_path}
        sidecar.write_text(json.dumps(metadata,indent=2)+'\n')
        if not torque_attempted:
            print('No episode saved: stopped before torque enable and recording.',flush=True)
            return
        if not torque_off:
            print('POWER OFF FOLLOWER: torque-off was not verified; dataset encoding skipped.',flush=True)
            return
        if len(self.frames)<2:
            print('No test episode saved: fewer than two frames.',flush=True)
            return
        print(f'Torque is OFF. Saving one local test episode: {self.root}',flush=True)
        write_episode(self.root,self.frames)
        (self.root/'recording_context.json').write_text(json.dumps(metadata,indent=2)+'\n')
        self.frames.clear()
        validate(self.root)
        print('Test dataset saved and structurally checked. Visual/timing review still required. No upload.',flush=True)


if __name__=='__main__':
    smoke_test()
