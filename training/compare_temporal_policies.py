"""Causal, episode-separated offline temporal-ensemble comparison.

Uses recorded observations, not a closed-loop simulator. Every-frame prediction
assumes zero inference latency and is not a replay of CPU deployment timing.
"""
import argparse
import json
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'msi_diffusion'))
sys.path.insert(0, str(HERE.parent / 'scripts'))
from common import JOINTS, check_package, check_version
from act_temporal_ensemble import TimeAlignedTemporalEnsembler


def score(actions, target):
    error = np.abs(actions - target)
    return dict(mae_by_joint=dict(zip(JOINTS, error.mean(axis=0).tolist())),
                mean_arm_mae_degrees=float(error[:, :5].mean()),
                gripper_mae_percentage_points=float(error[:, 5].mean()))


def replay(chunks, episodes, frames, coefficient, stride=1):
    """Only earlier/current chunks from this episode can contribute."""
    output = np.empty((len(chunks), 6))
    last_episode = None
    for i, (episode, frame) in enumerate(zip(episodes, frames)):
        if episode != last_episode:
            ensemble = TimeAlignedTemporalEnsembler(coefficient, 30)
            last_episode = episode
            first_frame = frame
        now = float(frame) / 30
        if (frame - first_frame) % stride == 0:
            ensemble.add(now, chunks[i])
        output[i], _ = ensemble.action(now)
    return output


def queued(chunks, episodes, frames, stride):
    output = np.empty((len(chunks), 6))
    last_episode = None
    for i, (episode, frame) in enumerate(zip(episodes, frames)):
        if episode != last_episode:
            last_episode = episode
            first_frame = frame
        if (frame - first_frame) % stride == 0:
            anchor, active = frame, chunks[i]
        output[i] = active[frame - anchor]
    return output


def predictions(kind, checkpoint, root, out, batch_size, workers):
    import torch
    from torch.utils.data import DataLoader
    from lerobot.datasets.dataset_metadata import LeRobotDatasetMetadata
    from lerobot.datasets.factory import resolve_delta_timestamps
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    from lerobot.policies.factory import make_pre_post_processors
    if kind == 'act':
        from lerobot.policies.act.configuration_act import ACTConfig as Config
        from lerobot.policies.act.modeling_act import ACTPolicy as Policy
    else:
        from lerobot.policies.diffusion.configuration_diffusion import DiffusionConfig as Config
        from lerobot.policies.diffusion.modeling_diffusion import DiffusionPolicy as Policy
    torch.manual_seed(42)
    cfg = Config.from_pretrained(str(checkpoint))
    cfg.device = 'cuda'
    cfg.pretrained_backbone_weights = None
    policy = Policy.from_pretrained(str(checkpoint), config=cfg).cuda().eval()
    pre, post = make_pre_post_processors(policy_cfg=cfg, pretrained_path=str(checkpoint),
        preprocessor_overrides={'device_processor': {'device': 'cuda'}})
    meta = LeRobotDatasetMetadata('local/so101-cube-cup-validation', root=root/'datasets/validation')
    ds = LeRobotDataset('local/so101-cube-cup-validation', root=root/'datasets/validation',
        delta_timestamps=resolve_delta_timestamps(cfg, meta), video_backend='pyav')
    kwargs = dict(batch_size=batch_size, shuffle=False, num_workers=workers,
        generator=torch.Generator().manual_seed(42))
    if workers:
        kwargs['multiprocessing_context'] = 'spawn'
    loader = DataLoader(ds, **kwargs)
    noise_generator = torch.Generator(device='cuda').manual_seed(42)
    chunks, targets, episodes, frames = [], [], [], []
    seen = 0
    with torch.inference_mode():
        for batch in loader:
            start = cfg.n_obs_steps - 1 if kind == 'diffusion' else 0
            targets.append(batch['action'][:, start].clone().numpy())
            episodes.append(batch['episode_index'].clone().numpy().reshape(-1))
            frames.append(batch['frame_index'].clone().numpy().reshape(-1))
            processed = pre(batch)
            if kind == 'diffusion':
                noise = torch.randn((len(targets[-1]), cfg.horizon, 6),
                    device='cuda', generator=noise_generator)
                pred = policy.predict_action_chunk(processed, noise=noise)
            else:
                pred = policy.predict_action_chunk(processed)
            chunks.append(post(pred).cpu().numpy())
            seen += len(targets[-1])
            if seen % 800 == 0 or seen == len(ds):
                print(f'{kind}: {seen}/{len(ds)} predictions cached', flush=True)
    arrays = dict(chunks=np.concatenate(chunks), target=np.concatenate(targets),
        episodes=np.concatenate(episodes), frames=np.concatenate(frames))
    if not all(np.isfinite(a).all() for a in arrays.values()):
        raise RuntimeError('Nonfinite cached predictions')
    np.savez_compressed(out/f'{kind}-predictions.npz', **arrays)
    return arrays


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data-root', type=Path, required=True)
    p.add_argument('--act-checkpoint', type=Path, required=True)
    p.add_argument('--diffusion-checkpoint', type=Path, required=True)
    p.add_argument('--output-dir', type=Path, required=True)
    p.add_argument('--batch-size', type=int, default=8)
    p.add_argument('--workers', type=int, default=4)
    args = p.parse_args()
    check_version()
    root = check_package(args.data_root)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    results = {}
    reference = None
    for kind, checkpoint in [('act', args.act_checkpoint), ('diffusion', args.diffusion_checkpoint)]:
        data = predictions(kind, checkpoint.resolve(), root, args.output_dir, args.batch_size, args.workers)
        if reference is not None:
            for key in ('target', 'episodes', 'frames'):
                np.testing.assert_allclose(data[key], reference[key], atol=1e-5, rtol=0)
        else:
            reference = {k: data[k] for k in ('target', 'episodes', 'frames')}
        c, y, e, f = (data[k] for k in ('chunks', 'target', 'episodes', 'frames'))
        metrics = {'no_ensemble_next_action': score(c[:, 0], y)}
        for coefficient in (.01, -.5):
            metrics[f'temporal_coefficient_{coefficient}'] = score(replay(c, e, f, coefficient), y)
        # Zero-latency 2.5 Hz ACT prediction / 30 Hz control sensitivity check.
        # Cadence approximates the CPU trials, not their measured variable timing.
        if kind == 'act':
            for coefficient in (.01, -.5):
                metrics[f'approx_2_5hz_temporal_coefficient_{coefficient}'] = score(
                    replay(c, e, f, coefficient, stride=12), y)
        stride = 8 if kind == 'diffusion' else 100
        metrics[f'queued_{stride}_actions'] = score(queued(c, e, f, stride), y)
        results[kind] = dict(checkpoint=str(checkpoint), observations=len(y),
            episodes=len(np.unique(e)), metrics=metrics)
        print(json.dumps({kind: results[kind]}, indent=2), flush=True)
        (args.output_dir/'comparison-partial.json').write_text(json.dumps(results, indent=2)+'\n')
    report = dict(results=results,
        scope='Offline causal action imitation on all 12 held-out episodes, not task success.',
        units='Arm MAE in degrees; gripper MAE in percentage points.',
        prediction_cadence='Main temporal scores predict each nominal 30 Hz frame, zero latency.',
        reset='Ensemble and action queues reset at every episode boundary; no future chunks used.',
        deployment_limit='CPU latency, changing robot states, rate limits and contact/release overrides are not simulated.',
        diffusion_temporal_note='Optional overlap averaging is experimental; native diffusion normally executes an 8-action queue.',
        coefficients='0.01 earlier trial and -0.5 later trial; pre-existing values, not fitted to validation.')
    (args.output_dir/'comparison.json').write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__':
    main()
