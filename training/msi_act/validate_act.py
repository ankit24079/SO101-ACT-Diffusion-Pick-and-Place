"""Evaluate saved ACT checkpoints on the 12 external held-out episodes.

Uses checkpoint preprocessing/statistics, action chunk padding masks and native
LeRobot video decoding. Does not connect to, replay on, or move any robot.
"""
import argparse
import json
from pathlib import Path

from common import CAMERAS, JOINTS, check_package, check_version


def masked_sums(prediction, target, is_pad):
    """Sum absolute chunk errors per joint, excluding episode-end padding."""
    import torch
    if prediction.shape != target.shape or is_pad.shape != prediction.shape[:2]:
        raise ValueError('Prediction, target and padding mask shapes differ')
    if not torch.isfinite(prediction).all() or not torch.isfinite(target).all():
        raise RuntimeError('Non-finite prediction or target')
    valid = ~is_pad.bool()
    error = (prediction-target).abs()
    return (error*valid.unsqueeze(-1)).sum(dim=(0, 1)), int(valid.sum())


def evaluate(checkpoint, data_root, device='cuda', batch_size=8, workers=4,
             max_samples=0, output=None):
    check_version()
    root = check_package(data_root)
    import numpy as np
    import torch
    from torch.utils.data import DataLoader, Subset
    from lerobot.datasets.dataset_metadata import LeRobotDatasetMetadata
    from lerobot.datasets.factory import resolve_delta_timestamps
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    from lerobot.policies.act.configuration_act import ACTConfig
    from lerobot.policies.act.modeling_act import ACTPolicy
    from lerobot.policies.factory import make_pre_post_processors

    checkpoint = Path(checkpoint).resolve()
    if device.startswith('cuda') and not torch.cuda.is_available():
        raise RuntimeError('CUDA unavailable; run on an allocated GPU node')
    torch.manual_seed(42)
    cfg = ACTConfig.from_pretrained(str(checkpoint))
    cfg.device = device
    policy = ACTPolicy.from_pretrained(str(checkpoint), config=cfg).to(device).eval()
    if set(cfg.image_features) != set(CAMERAS):
        raise RuntimeError('Checkpoint must consume both recorded camera views')
    # Never supply held-out dataset stats to either processor.
    pre, post = make_pre_post_processors(
        policy_cfg=cfg, pretrained_path=str(checkpoint),
        preprocessor_overrides={'device_processor': {'device': device}},
    )
    meta = LeRobotDatasetMetadata('local/so101-cube-cup-validation', root=root/'datasets/validation')
    dataset = LeRobotDataset('local/so101-cube-cup-validation', root=root/'datasets/validation',
                             delta_timestamps=resolve_delta_timestamps(cfg, meta), video_backend='pyav')
    selected = list(range(len(dataset)))
    if max_samples and max_samples < len(dataset):
        selected = np.linspace(0, len(dataset)-1, max_samples, dtype=int).tolist()
    loader_args = {'batch_size': batch_size, 'shuffle': False, 'num_workers': workers}
    if workers:
        loader_args['multiprocessing_context'] = 'spawn'
    loader = DataLoader(Subset(dataset, selected), **loader_args)
    normalized_sum = torch.zeros(6, dtype=torch.float64)
    physical_sum = torch.zeros(6, dtype=torch.float64)
    first_sum = torch.zeros(6, dtype=torch.float64)
    valid_count = observations = 0
    with torch.inference_mode():
        for batch in loader:
            target_physical = batch['action'].clone().cpu()
            is_pad = batch['action_is_pad'].clone()
            processed = pre(batch)
            prediction = policy.predict_action_chunk(processed)
            sums, count = masked_sums(prediction, processed['action'], is_pad.to(device))
            normalized_sum += sums.cpu().double()
            physical = post(prediction).cpu()
            sums, _ = masked_sums(physical, target_physical, is_pad.cpu())
            physical_sum += sums.double()
            first_sum += (physical[:, 0]-target_physical[:, 0]).abs().sum(dim=0).double()
            valid_count += count
            observations += len(target_physical)
    if not valid_count:
        raise RuntimeError('No non-padded validation actions')
    result = {
        'checkpoint': str(checkpoint), 'validation_episodes_available': 12,
        'observations_evaluated': observations, 'total_available_observations': len(dataset),
        'full_validation': observations == len(dataset), 'valid_action_vectors': valid_count,
        'normalized_chunk_l1': float(normalized_sum.sum()/(valid_count*6)),
        'physical_chunk_mae_by_joint': dict(zip(JOINTS, (physical_sum/valid_count).tolist())),
        'first_action_mae_by_joint': dict(zip(JOINTS, (first_sum/observations).tolist())),
        'units': 'first five joints degrees; gripper percentage points',
        'normalization': 'saved checkpoint processors; no validation statistics fitted',
        'metric_scope': 'Open-loop action imitation error with zero-latent inference and padding excluded; not robot task success rate.',
    }
    if output:
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2)+'\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkpoint', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--device', default='cuda')
    parser.add_argument('--batch-size', type=int, default=8)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--max-samples', type=int, default=0)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.max_samples < 0 or args.batch_size < 1 or args.workers < 0:
        parser.error('Invalid sample, batch or worker count')
    print(json.dumps(evaluate(args.checkpoint, args.data_root, args.device, args.batch_size,
                              args.workers, args.max_samples, args.output), indent=2))


if __name__ == '__main__':
    main()
