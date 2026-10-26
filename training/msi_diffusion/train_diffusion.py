"""Stock LeRobot diffusion training on the fixed 64/12 cube-to-cup split."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

from common import check_package, check_version


def training_command(args, root):
    if args.resume:
        configs = sorted(args.output_dir.glob('checkpoints/*/pretrained_model/train_config.json'))
        configs = [p for p in configs if p.parent.parent.name.isdigit()]
        if not configs:
            raise RuntimeError('No numeric resumable diffusion checkpoint found')
        config = json.loads(configs[-1].read_text())
        if config['policy']['type'] != 'diffusion':
            raise RuntimeError('Refusing to resume a non-diffusion run')
        return [sys.executable, '-m', 'lerobot.scripts.lerobot_train',
            f'--config_path={configs[-1].resolve()}', '--resume=true',
            f'--dataset.root={root}/datasets/train', f'--policy.device={args.device}',
            f'--output_dir={args.output_dir.resolve()}',
            '--policy.push_to_hub=false', '--wandb.enable=false']
    command = [sys.executable, '-m', 'lerobot.scripts.lerobot_train',
        '--dataset.repo_id=local/so101-cube-cup-train',
        f'--dataset.root={root}/datasets/train', '--dataset.video_backend=pyav',
        '--policy.type=diffusion', f'--policy.device={args.device}',
        '--policy.push_to_hub=false', '--wandb.enable=false',
        '--policy.n_obs_steps=2', '--policy.horizon=16', '--policy.n_action_steps=8',
        '--policy.drop_n_last_frames=7', '--policy.down_dims=[256,512,1024]',
        '--policy.resize_shape=[240,320]', '--policy.crop_ratio=1.0',
        '--policy.noise_scheduler_type=DDIM', '--policy.num_train_timesteps=100',
        '--policy.num_inference_steps=20', '--policy.do_mask_loss_for_padding=true',
        f'--steps={args.steps}', f'--batch_size={args.batch_size}',
        f'--num_workers={args.workers}', f'--save_freq={args.save_freq}',
        '--log_freq=100', '--seed=42', f'--output_dir={args.output_dir.resolve()}']
    if args.no_pretrained_backbone:
        command.append('--policy.pretrained_backbone_weights=null')
    return command


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data-root', type=Path, required=True)
    p.add_argument('--output-dir', type=Path, required=True)
    p.add_argument('--device', default='cuda')
    p.add_argument('--steps', type=int, default=100000)
    p.add_argument('--batch-size', type=int, default=8)
    p.add_argument('--workers', type=int, default=4)
    p.add_argument('--save-freq', type=int, default=10000)
    p.add_argument('--validation-max-samples', type=int, default=256,
        help='Checkpoint selection subset; the selected checkpoint is then scored on all validation frames')
    p.add_argument('--resume', action='store_true')
    p.add_argument('--no-pretrained-backbone', action='store_true')
    p.add_argument('--print-command', action='store_true', help='Validate package and print command; do not train')
    args = p.parse_args()
    if min(args.steps,args.batch_size,args.save_freq)<1 or min(args.workers,args.validation_max_samples)<0:
        p.error('Invalid training or validation counts')
    root = check_package(args.data_root)
    command = training_command(args,root)
    print(json.dumps(command,indent=2),flush=True)
    if args.print_command:
        return
    check_version()
    if any(importlib.util.find_spec(name) is None for name in ('accelerate','diffusers')):
        raise RuntimeError('Install lerobot[training,diffusion]==0.6.1 in the GPU environment')
    import torch
    if args.device.startswith('cuda') and not torch.cuda.is_available():
        raise RuntimeError('Run inside an allocated MSI GPU job')
    if args.output_dir.exists() and not args.resume:
        raise RuntimeError('Choose a fresh output directory or explicitly resume')
    env = dict(os.environ)
    env.setdefault('OMP_NUM_THREADS',os.environ.get('SLURM_CPUS_PER_TASK','8'))
    subprocess.run(command,env=env,check=True)
    from validate_diffusion import evaluate
    checkpoints = sorted(p for p in args.output_dir.glob('checkpoints/*/pretrained_model')
        if p.parent.name.isdigit() and (p/'model.safetensors').exists())
    if not checkpoints:
        raise RuntimeError('No saved checkpoints found')
    scores = []
    for checkpoint in checkpoints:
        print(f'Validating checkpoint {checkpoint.parent.name}',flush=True)
        scores.append(evaluate(checkpoint,root,args.device,args.batch_size,args.workers,
            args.validation_max_samples,args.output_dir/'validation'/f'{checkpoint.parent.name}.json'))
    best = min(scores,key=lambda r:r['normalized_execution_l1'])
    full = best if best['full_validation'] else evaluate(Path(best['checkpoint']),root,
        args.device,args.batch_size,args.workers,0,args.output_dir/'validation/best-full.json')
    summary = dict(best_checkpoint=best['checkpoint'],
        selection_metric='normalized_execution_l1', selection_score=best['normalized_execution_l1'],
        selection_observations=best['observations_evaluated'], evaluated_checkpoints=len(scores),
        best_full_validation=full,training_episodes=64,validation_episodes=12,
        note='Checkpoint selection is open-loop imitation scoring, not robot task success.')
    (args.output_dir/'validation-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2),flush=True)


if __name__ == '__main__':
    main()
