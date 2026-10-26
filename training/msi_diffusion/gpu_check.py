"""Exercise the full diffusion training batch inside an allocated GPU job."""
import argparse
import json
from pathlib import Path
import time

from common import check_package, check_version


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data-root',type=Path,required=True)
    p.add_argument('--batch-size',type=int,default=8)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    check_version();root=check_package(args.data_root)
    import torch
    from torch.utils.data import DataLoader
    from lerobot.datasets.dataset_metadata import LeRobotDatasetMetadata
    from lerobot.datasets.factory import resolve_delta_timestamps
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    from lerobot.policies.diffusion.configuration_diffusion import DiffusionConfig
    from lerobot.policies.factory import make_policy,make_pre_post_processors
    if not torch.cuda.is_available():raise RuntimeError('GPU setup check needs a Slurm GPU allocation')
    torch.manual_seed(42)
    cfg=DiffusionConfig(device='cuda',n_obs_steps=2,horizon=16,n_action_steps=8,
        down_dims=(256,512,1024),resize_shape=(240,320),crop_ratio=1.,
        noise_scheduler_type='DDIM',num_train_timesteps=100,num_inference_steps=20,
        do_mask_loss_for_padding=True,push_to_hub=False)
    meta=LeRobotDatasetMetadata('local/so101-cube-cup-train',root=root/'datasets/train')
    policy=make_policy(cfg,ds_meta=meta)
    pre,post=make_pre_post_processors(policy_cfg=cfg,dataset_stats=meta.stats)
    dataset=LeRobotDataset('local/so101-cube-cup-train',root=root/'datasets/train',
        delta_timestamps=resolve_delta_timestamps(cfg,meta),video_backend='pyav')
    batch=pre(next(iter(DataLoader(dataset,batch_size=args.batch_size,num_workers=0))))
    torch.cuda.reset_peak_memory_stats()
    optimizer=torch.optim.Adam(policy.parameters(),lr=cfg.optimizer_lr,
        betas=cfg.optimizer_betas,eps=cfg.optimizer_eps,weight_decay=cfg.optimizer_weight_decay)
    policy.train();loss,_=policy(batch)
    if not torch.isfinite(loss):raise RuntimeError('Nonfinite training loss')
    loss.backward()
    grad_norm=torch.nn.utils.clip_grad_norm_(policy.parameters(),10.,error_if_nonfinite=True)
    optimizer.step();optimizer.zero_grad(set_to_none=True)
    policy.eval();policy.reset()
    observation={k:batch[k][:1] for k in cfg.input_features}
    torch.cuda.synchronize();start=time.perf_counter()
    prediction=post(policy.predict_action_chunk(observation))
    torch.cuda.synchronize();elapsed=time.perf_counter()-start
    if prediction.shape!=(1,8,6) or not torch.isfinite(prediction).all():
        raise RuntimeError('Invalid full-size diffusion prediction')
    report=dict(status='passed',hardware_accessed=False,robot_hardware_accessed=False,
        gpu=torch.cuda.get_device_name(0),batch_size=args.batch_size,
        trainable_parameters=sum(p.numel() for p in policy.parameters() if p.requires_grad),
        peak_allocated_gb=torch.cuda.max_memory_allocated()/1024**3,
        one_step_loss=float(loss.detach()),gradient_norm=float(grad_norm),
        first_batch_one_prediction_ms=elapsed*1000,
        note='Setup and GPU memory check only; not a trained model or steady-state inference benchmark.')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':main()
