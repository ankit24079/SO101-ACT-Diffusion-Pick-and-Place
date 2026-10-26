"""Checks shared by the offline ACT training and validation tools."""
import importlib.metadata
import json
from pathlib import Path

JOINTS = ['shoulder_pan', 'shoulder_lift', 'elbow_flex', 'wrist_flex', 'wrist_roll', 'gripper']
CAMERAS = ['observation.images.workspace', 'observation.images.wrist']


def check_version():
    version = importlib.metadata.version('lerobot')
    if version != '0.6.1':
        raise RuntimeError(f'This workflow requires LeRobot 0.6.1; found {version}')


def check_package(root):
    root = Path(root).resolve()
    split = json.loads((root/'splits.json').read_text())
    train, val = split['train'], split['validation']
    if len(train) != 64 or len(val) != 12 or len(set(train+val)) != 76:
        raise RuntimeError('Expected 64 distinct training / 12 distinct validation episodes')
    for name, expected in [('train', 64), ('validation', 12)]:
        info = json.loads((root/'datasets'/name/'meta/info.json').read_text())
        if info['total_episodes'] != expected or info['fps'] != 30:
            raise RuntimeError(f'{name}: wrong episode count or nominal FPS')
        features = info['features']
        for key in ('observation.state', 'action'):
            if features[key]['shape'] != [6] or features[key]['names'] != JOINTS:
                raise RuntimeError(f'{name}: unexpected joint order for {key}')
        for key in CAMERAS:
            if features[key]['shape'] != [480, 640, 3] or features[key]['dtype'] != 'video':
                raise RuntimeError(f'{name}: unexpected camera feature {key}')
    return root
