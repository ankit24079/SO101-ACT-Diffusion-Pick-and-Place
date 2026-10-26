"""Encode an existing official episode journal offline. No hardware imports/I/O."""
import argparse
import json
import re
import shutil
from pathlib import Path

import numpy as np

from test_episode import validate, write_episode


def main(episode):
    if not re.fullmatch(r'cube-cup-official-\d+', episode):
        raise ValueError('Expected an exact cube-cup-official-<number> episode name')
    output = Path('/workspace/outputs/test-recordings')
    metadata = json.loads((output/(episode+'.json')).read_text())
    spool = output/(episode+'-frames')
    root = Path('/workspace/datasets')/episode
    if root.exists():
        raise RuntimeError(f'Refusing to overwrite existing dataset: {root}')
    if shutil.disk_usage(root.parent).free < 5*1024**3:
        raise RuntimeError('Less than 5 GiB free; keep the raw journal and frames')
    frames = []
    for line in (spool/'frames.jsonl').read_text().splitlines():
        frame = json.loads(line)
        for key in ('observation.state', 'action'):
            frame[key] = np.asarray(frame[key], dtype=np.float32)
            if frame[key].shape != (6,) or not np.isfinite(frame[key]).all():
                raise RuntimeError(f'Invalid {key} in frame {len(frames)}')
        for key in ('observation.elapsed_time', 'observation.camera_time'):
            frame[key] = np.asarray(frame[key], dtype=np.float64)
        for name in ('workspace', 'wrist'):
            path = Path(frame['_image_paths'][name]).resolve()
            if not path.is_relative_to(spool.resolve()) or not path.is_file():
                raise RuntimeError(f'Missing or invalid saved image: {path}')
        frames.append(frame)
    if len(frames) != metadata['frames'] or len(frames) < 2:
        raise RuntimeError('Journal count does not match the saved recording context')
    fps = metadata['fps_requested']
    context = dict(metadata, recovered_offline=True, training_approved=False,
                   recovery_note='Encoded from preserved journal and JPEGs. Original shutdown torque verification remains unchanged. No hardware accessed during recovery.')
    print(f'Recovering {len(frames)} frames with both cameras; no hardware access.', flush=True)
    write_episode(root, frames, fps=fps)
    (root/'recording_context.json').write_text(json.dumps(context, indent=2)+'\n')
    validate(root, fps=fps)
    print(f'Recovered and structurally validated: {root}. Original raw files preserved.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--episode', required=True)
    main(parser.parse_args().episode)
