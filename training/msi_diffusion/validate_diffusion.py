"""Score native diffusion execution chunks using saved training processors."""
import argparse
import json
from pathlib import Path
import time

from common import CAMERAS, JOINTS, check_package, check_version


def execution_targets(actions, is_pad, n_obs_steps, n_action_steps):
    start = n_obs_steps-1
    end = start+n_action_steps
    if n_obs_steps<1 or n_action_steps<1 or end>actions.shape[1] or is_pad.shape!=actions.shape[:2]:
        raise ValueError('Invalid diffusion action alignment')
    return actions[:,start:end],is_pad[:,start:end]


def masked_sums(prediction,target,is_pad):
    import torch
    if prediction.shape!=target.shape or is_pad.shape!=prediction.shape[:2]:
        raise ValueError('Prediction and target shapes differ')
    if not torch.isfinite(prediction).all() or not torch.isfinite(target).all():
        raise RuntimeError('Nonfinite predictions or targets')
    valid = ~is_pad.bool()
    return ((prediction-target).abs()*valid.unsqueeze(-1)).sum(dim=(0,1)),int(valid.sum())


def select_indices(episode_indices,max_samples):
    """Distribute a subset over episodes rather than only scoring the beginning."""
    import numpy as np
    episodes = np.asarray(episode_indices)
    if not max_samples or max_samples>=len(episodes):
        return list(range(len(episodes)))
    groups = [np.flatnonzero(episodes==i) for i in np.unique(episodes)]
    selected=[]
    for index,group in enumerate(groups):
        count=min(len(group),max_samples//len(groups)+(index<max_samples%len(groups)))
        if count:
            selected.extend(group[np.linspace(0,len(group)-1,count,dtype=int)].tolist())
    return sorted(selected)


def evaluate(checkpoint,data_root,device='cuda',batch_size=8,workers=4,max_samples=0,output=None):
    check_version()
    root=check_package(data_root)
    import torch
    from torch.utils.data import DataLoader,Subset
    from lerobot.datasets.dataset_metadata import LeRobotDatasetMetadata
    from lerobot.datasets.factory import resolve_delta_timestamps
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    from lerobot.policies.diffusion.configuration_diffusion import DiffusionConfig
    from lerobot.policies.diffusion.modeling_diffusion import DiffusionPolicy
    from lerobot.policies.factory import make_pre_post_processors

    checkpoint=Path(checkpoint).resolve()
    cfg=DiffusionConfig.from_pretrained(str(checkpoint))
    cfg.device=device
    # Checkpoint contains the entire visual backbone; never fetch ImageNet again.
    cfg.pretrained_backbone_weights=None
    if set(cfg.image_features)!=set(CAMERAS):
        raise RuntimeError('Diffusion must consume both recorded cameras')
    policy=DiffusionPolicy.from_pretrained(str(checkpoint),config=cfg).to(device).eval()
    policy.reset()
    pre,post=make_pre_post_processors(policy_cfg=cfg,pretrained_path=str(checkpoint),
        preprocessor_overrides={'device_processor':{'device':device}})
    meta=LeRobotDatasetMetadata('local/so101-cube-cup-validation',root=root/'datasets/validation')
    dataset=LeRobotDataset('local/so101-cube-cup-validation',root=root/'datasets/validation',
        delta_timestamps=resolve_delta_timestamps(cfg,meta),video_backend='pyav')
    selected=select_indices(dataset.hf_dataset['episode_index'],max_samples)
    loader_kwargs=dict(batch_size=batch_size,shuffle=False,num_workers=workers,
        generator=torch.Generator().manual_seed(42))
    if workers:loader_kwargs['multiprocessing_context']='spawn'
    loader=DataLoader(Subset(dataset,selected),**loader_kwargs)
    normalized_sum=torch.zeros(6,dtype=torch.float64)
    physical_sum=torch.zeros(6,dtype=torch.float64)
    first_sum=torch.zeros(6,dtype=torch.float64)
    noise_generator=torch.Generator(device=device).manual_seed(42)
    valid_count=first_count=observations=0
    inference_seconds=0
    with torch.inference_mode():
        for batch in loader:
            target,padding=execution_targets(batch['action'].clone(),batch['action_is_pad'].clone(),
                cfg.n_obs_steps,cfg.n_action_steps)
            processed=pre(batch)
            noise=torch.randn((len(target),cfg.horizon,6),device=device,generator=noise_generator)
            if device.startswith('cuda'):torch.cuda.synchronize()
            start=time.perf_counter()
            prediction=policy.predict_action_chunk(processed,noise=noise)
            if device.startswith('cuda'):torch.cuda.synchronize()
            inference_seconds+=time.perf_counter()-start
            normalized_target,_=execution_targets(processed['action'],processed['action_is_pad'],
                cfg.n_obs_steps,cfg.n_action_steps)
            sums,count=masked_sums(prediction,normalized_target,padding.to(device))
            normalized_sum+=sums.cpu().double()
            physical=post(prediction).cpu()
            sums,_=masked_sums(physical,target,padding)
            physical_sum+=sums.double()
            first_valid=~padding[:,0].bool()
            first_sum+=(physical[first_valid,0]-target[first_valid,0]).abs().sum(dim=0).double()
            first_count+=int(first_valid.sum())
            valid_count+=count
            observations+=len(target)
    if not valid_count or not first_count:raise RuntimeError('No valid validation targets')
    result=dict(checkpoint=str(checkpoint),policy='diffusion',validation_episodes_available=12,
        observations_evaluated=observations,total_available_observations=len(dataset),
        full_validation=observations==len(dataset),valid_action_vectors=valid_count,
        n_obs_steps=cfg.n_obs_steps,horizon=cfg.horizon,n_action_steps=cfg.n_action_steps,
        noise_scheduler_type=cfg.noise_scheduler_type,num_inference_steps=cfg.num_inference_steps,
        normalized_execution_l1=float(normalized_sum.sum()/(valid_count*6)),
        physical_execution_mae_by_joint=dict(zip(JOINTS,(physical_sum/valid_count).tolist())),
        first_action_mae_by_joint=dict(zip(JOINTS,(first_sum/first_count).tolist())),
        mean_inference_ms_per_observation=1000*inference_seconds/observations,
        units='first five joints degrees; gripper percentage points',
        normalization='saved training checkpoint processors; no validation statistics fitted',
        metric_scope='Open-loop execution-chunk imitation error; past action excluded and padding masked. Not robot success.',
        comparison_note='Diffusion min/max normalization differs from ACT mean/std; compare physical per-joint MAE, not normalized scores.')
    if output:
        output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--checkpoint',type=Path,required=True)
    p.add_argument('--data-root',type=Path,required=True)
    p.add_argument('--device',default='cuda')
    p.add_argument('--batch-size',type=int,default=8)
    p.add_argument('--workers',type=int,default=4)
    p.add_argument('--max-samples',type=int,default=256,help='0 scores every held-out observation')
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if args.batch_size<1 or min(args.workers,args.max_samples)<0:p.error('Invalid batch, worker or sample count')
    print(json.dumps(evaluate(args.checkpoint,args.data_root,args.device,args.batch_size,
        args.workers,args.max_samples,args.output),indent=2))
