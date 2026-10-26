"""Train using the stock LeRobot ACT trainer, then score held-out checkpoints."""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from common import check_package, check_version


def training_command(args, root):
    if getattr(args, 'resume', False):
        configs = sorted(p for p in args.output_dir.glob('checkpoints/*/pretrained_model/train_config.json')
                         if p.parent.parent.name.isdigit())
        if not configs:
            raise RuntimeError('No resumable checkpoint train_config.json found')
        return [sys.executable, '-m', 'lerobot.scripts.lerobot_train',
                f'--config_path={configs[-1].resolve()}', '--resume=true',
                f'--dataset.root={root}/datasets/train', f'--policy.device={args.device}',
                f'--output_dir={args.output_dir.resolve()}', '--policy.push_to_hub=false',
                '--wandb.enable=false']
    command = [sys.executable, '-m', 'lerobot.scripts.lerobot_train',
               '--dataset.repo_id=local/so101-cube-cup-train',
               f'--dataset.root={root}/datasets/train', '--dataset.video_backend=pyav',
               '--policy.type=act', f'--policy.device={args.device}',
               '--policy.n_decoder_layers=4',
               '--policy.push_to_hub=false', '--wandb.enable=false',
               '--policy.chunk_size=100', '--policy.n_action_steps=100',
               f'--steps={args.steps}', f'--batch_size={args.batch_size}',
               f'--num_workers={args.workers}', '--seed=42',
               f'--save_freq={args.save_freq}', '--log_freq=100',
               f'--output_dir={args.output_dir.resolve()}']
    if args.no_pretrained_backbone:
        command.append('--policy.pretrained_backbone_weights=null')
    if args.smoke_test:
        # Exercise real data, forward/backward, checkpointing and validation on CPU.
        command = [c for c in command if not c.startswith(('--policy.chunk_size=', '--policy.n_action_steps=', '--policy.n_decoder_layers='))]
        command += ['--policy.chunk_size=2', '--policy.n_action_steps=2',
                    '--policy.n_decoder_layers=1',
                    '--policy.dim_model=64', '--policy.n_heads=4',
                    '--policy.dim_feedforward=256', '--policy.n_encoder_layers=1',
                    '--policy.n_vae_encoder_layers=1', '--policy.pretrained_backbone_weights=null']
    return command


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--device', default='cuda')
    parser.add_argument('--steps', type=int, default=100000)
    parser.add_argument('--batch-size', type=int, default=8)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--save-freq', type=int, default=10000)
    parser.add_argument('--no-pretrained-backbone', action='store_true')
    parser.add_argument('--smoke-test', action='store_true')
    parser.add_argument('--validate-latest-only', action='store_true')
    parser.add_argument('--validation-max-samples', type=int, default=0)
    parser.add_argument('--resume', action='store_true', help='Resume the latest numeric checkpoint in output-dir')
    args = parser.parse_args()
    if args.smoke_test:
        args.steps, args.batch_size, args.workers, args.save_freq = 1, 1, 0, 1
        args.validation_max_samples = 2
    if min(args.steps, args.batch_size, args.save_freq) < 1 or min(args.workers, args.validation_max_samples) < 0:
        parser.error('Invalid steps, batch size, checkpoint frequency, workers or sample count')
    check_version()
    import importlib.util
    if importlib.util.find_spec('accelerate') is None:
        raise RuntimeError("Missing training dependencies. Provision LeRobot 0.6.1 with its training extra in your MSI GPU environment; see README.md.")
    root = check_package(args.data_root)
    import torch
    if args.device.startswith('cuda') and not torch.cuda.is_available():
        raise RuntimeError('CUDA unavailable. Use an MSI GPU allocation with CUDA PyTorch.')
    if args.output_dir.exists() and not args.resume:
        raise RuntimeError('Output directory already exists. Use a fresh path, or use native LeRobot resume instructions.')
    if args.resume and (not args.output_dir.is_dir() or args.smoke_test):
        raise RuntimeError('Resume needs an existing training run and cannot be combined with --smoke-test')
    command = training_command(args, root)
    print('Starting stock LeRobot ACT training on 64 episodes. Validation episodes are not training inputs.', flush=True)
    print(json.dumps(command, indent=2), flush=True)
    environment = dict(os.environ)
    # Avoid oversubscribing CPU libraries inside Slurm allocations.
    environment.setdefault('OMP_NUM_THREADS', os.environ.get('SLURM_CPUS_PER_TASK', '4'))
    subprocess.run(command, check=True, env=environment)
    from validate_act import evaluate
    checkpoints = sorted(p for p in args.output_dir.glob('checkpoints/*/pretrained_model')
                         if p.parent.name.isdigit() and (p/'config.json').exists())
    if not checkpoints:
        raise RuntimeError('No numeric checkpoint directories found after training')
    if args.validate_latest_only:
        checkpoints = checkpoints[-1:]
    metrics = []
    for checkpoint in checkpoints:
        print(f'Validating {checkpoint.parent.name} on external held-out data', flush=True)
        result = evaluate(checkpoint, root, args.device, args.batch_size, args.workers,
                          args.validation_max_samples,
                          args.output_dir/'validation'/f'{checkpoint.parent.name}.json')
        metrics.append(result)
    best = min(metrics, key=lambda x: x['normalized_chunk_l1'])
    summary = {'best_checkpoint': best['checkpoint'], 'selection_metric': 'normalized_chunk_l1',
               'best_score': best['normalized_chunk_l1'], 'evaluated_checkpoints': len(metrics),
               'full_validation': all(m['full_validation'] for m in metrics),
               'training_episodes': 64, 'validation_episodes': 12,
               'note': 'Validation selects a candidate checkpoint. Physical success rate is not measured.'}
    (args.output_dir/'validation-summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == '__main__':
    main()
