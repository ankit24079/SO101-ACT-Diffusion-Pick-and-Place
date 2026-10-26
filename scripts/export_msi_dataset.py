"""Offline export of the user's fixed 76-episode collection; no hardware access."""
import hashlib
import argparse
import importlib.metadata
import json
import random
import shutil
from pathlib import Path

import av
import numpy as np
import pyarrow.parquet as pq
from lerobot.datasets.aggregate import aggregate_datasets
from lerobot.datasets.lerobot_dataset import LeRobotDataset

PROJECT = Path('/project')
OUTPUT = PROJECT/'exports/so101-cube-cup-msi-76'
REPO_IDS = {'train': 'local/so101-cube-cup-train', 'validation': 'local/so101-cube-cup-validation'}


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2)+'\n')


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for data in iter(lambda: stream.read(1024*1024), b''):
            digest.update(data)
    return digest.hexdigest()


def main():
    global OUTPUT
    parser = argparse.ArgumentParser()
    parser.add_argument('--validation-episodes', type=int, default=8)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    args = parser.parse_args()
    if not 1 <= args.validation_episodes < 76:
        parser.error('--validation-episodes must be between 1 and 75')
    OUTPUT = args.output
    assert importlib.metadata.version('lerobot') == '0.6.1'
    if OUTPUT.exists():
        raise RuntimeError(f'Refusing to overwrite existing export: {OUTPUT}')
    selection = json.loads((PROJECT/'outputs/repaired-setup-20261019/final-collection.json').read_text())
    ids = selection['included_episode_ids']
    assert len(ids) == len(set(ids)) == 76
    assert 'cube-cup-official-1792456313899166218' not in ids
    assert not set(ids).intersection(selection['excluded_later_episode_ids'])
    roots = [PROJECT/'datasets/repaired-setup-20261019'/stem for stem in ids]
    # Temporal strata cover the beginning, middle and end of collection.
    rng = random.Random(42)
    validation_indexes = {rng.choice(list(block)) for block in
                          np.array_split(np.arange(76), args.validation_episodes)}
    splits = {'train': [i for i in range(76) if i not in validation_indexes],
              'validation': sorted(map(int, validation_indexes))}
    OUTPUT.mkdir(parents=True)
    save(OUTPUT/'provenance/final-collection.json', selection)
    records = []
    expected_features = None
    for index, root in enumerate(roots):
        info = json.loads((root/'meta/info.json').read_text())
        review = root.parent/(root.name+'-review')/'validation.json'
        report = json.loads(review.read_text())
        context = json.loads((root/'recording_context.json').read_text())
        assert info['total_episodes'] == 1 and info['fps'] == 30
        assert report['official_reader_reopened'] and context['torque_off_verified']
        assert not context['worker_error']
        if expected_features is None:
            expected_features = info['features']
        assert info['features'] == expected_features, f'Feature mismatch: {root}'
        tables = [pq.read_table(p).to_pydict() for p in sorted(root.glob('data/**/*.parquet'))]
        state = np.asarray([v for t in tables for v in t['observation.state']])
        action = np.asarray([v for t in tables for v in t['action']])
        count = info['total_frames']
        assert state.shape == action.shape == (count, 6)
        assert np.isfinite(state).all() and np.isfinite(action).all()
        assert report['frames'] == count
        for camera in ('workspace', 'wrist'):
            assert report['videos'][camera]['decoded_frames'] == count
        dest = OUTPUT/'provenance/episodes'/f'{index+1:03d}-{root.name}'
        dest.mkdir(parents=True)
        shutil.copy2(review, dest/'validation.json')
        shutil.copy2(root/'recording_context.json', dest/'recording_context.json')
        # Translate historical container paths into this repaired batch's host tree.
        session = PROJECT/'outputs/repaired-setup-20261019'/Path(context['official_session']).relative_to('/workspace/outputs')
        session_data = json.loads(session.read_text())
        assert session_data['follower_torque_off_verified'] and session_data['leader_torque_off_verified']
        for name in ('official-session.json', 'leader-calibration.json', 'follower-calibration.json'):
            shutil.copy2(session.parent/name, dest/name)
        records.append({'source_order_1_based': index+1, 'source_episode_id': root.name,
                        'frames': count, 'measured_duration_seconds': report['measured_duration_seconds'],
                        'max_camera_age_ms': report['max_camera_age_ms'],
                        'sample_intervals_over_150ms': report['sample_intervals_over_150ms'],
                        'reused_camera_frames': report['reused_camera_frames'],
                        'shutdown_warnings': session_data.get('cleanup_errors', []),
                        'full_visual_task_review': False})
    for split, indexes in splits.items():
        destination = OUTPUT/'datasets'/split
        print(f'Aggregating {split}: {len(indexes)} episodes', flush=True)
        aggregate_datasets(repo_ids=['local/'+ids[i] for i in indexes],
                           roots=[roots[i] for i in indexes],
                           aggr_repo_id=REPO_IDS[split], aggr_root=destination,
                           concatenate_videos=False, concatenate_data=False)
        data = LeRobotDataset(repo_id=REPO_IDS[split], root=destination, video_backend='pyav')
        info = json.loads((destination/'meta/info.json').read_text())
        assert info['total_episodes'] == len(indexes)
        assert len(data) == sum(records[i]['frames'] for i in indexes)
        # Videos remain one source file per episode, with byte-identical copies.
        for camera in ('workspace', 'wrist'):
            outputs = sorted((destination/'videos'/f'observation.images.{camera}').rglob('*.mp4'))
            assert len(outputs) == len(indexes)
            for i, output in zip(indexes, outputs, strict=True):
                source = next((roots[i]/'videos'/f'observation.images.{camera}').rglob('*.mp4'))
                assert sha256(source) == sha256(output)
                with av.open(str(output)) as container:
                    decoded = sum(1 for frame in container.decode(video=0)
                                  if (frame.width, frame.height) == (640, 480))
                assert decoded == records[i]['frames']
        offset = 0
        for output_index, i in enumerate(indexes):
            records[i].update(split=split, output_episode_index=output_index)
            table = pq.read_table(sorted(destination.glob('data/**/*.parquet'))[output_index]).to_pydict()
            source = pq.read_table(next(roots[i].glob('data/**/*.parquet'))).to_pydict()
            for key in ('observation.state', 'action', 'observation.elapsed_time',
                        'observation.camera_time', 'timestamp', 'frame_index'):
                assert np.array_equal(np.asarray(table[key]), np.asarray(source[key])), (i, key)
            assert set(table['episode_index']) == {output_index}
            assert table['index'] == list(range(offset, offset+records[i]['frames']))
            for local_index in (0, records[i]['frames']//2, records[i]['frames']-1):
                frame = data[offset+local_index]
                assert int(frame['episode_index']) == output_index
                for camera in ('workspace', 'wrist'):
                    assert tuple(frame[f'observation.images.{camera}'].shape) == (3, 480, 640)
            offset += records[i]['frames']
        print(f'{split}: all data matched, all videos decoded, native reader verified', flush=True)
    save(OUTPUT/'episode-map.json', records)
    save(OUTPUT/'splits.json', {
        'strategy': f'{args.validation_episodes} temporal strata, one held-out episode per stratum; Python random seed 42',
        'train': [ids[i] for i in splits['train']],
        'validation': [ids[i] for i in splits['validation']],
        'no_frames_shared_between_splits': True,
        'validation_dataset_is_not_automatically_evaluated_by_lerobot_train': True})
    save(OUTPUT/'verification.json', {
        'lerobot_version': importlib.metadata.version('lerobot'),
        'total_episodes': 76, 'train_episodes': len(splits['train']),
        'validation_episodes': len(splits['validation']),
        'total_frames_per_camera': sum(r['frames'] for r in records),
        'train_frames': sum(records[i]['frames'] for i in splits['train']),
        'validation_frames': sum(records[i]['frames'] for i in splits['validation']),
        'both_camera_streams_fully_decoded': True,
        'video_bytes_match_originals': True, 'joint_action_and_timing_values_match_originals': True,
        'native_reader_first_middle_last_frame_per_episode_passed': True,
        'training_statistics_computed_from_training_episodes_only': True,
        'human_task_success_review_complete': False,
        'joint_order': ['shoulder_pan','shoulder_lift','elbow_flex','wrist_flex','wrist_roll','gripper'],
        'units': 'First five values degrees; gripper percent opening 0..100',
        'nominal_fps': 30, 'note': 'Actual sampling is approximately 29 Hz. Actual timing features preserved. Hardware synchronization not established.'})
    print(f'Verified export: {OUTPUT}', flush=True)


if __name__ == '__main__':
    main()
