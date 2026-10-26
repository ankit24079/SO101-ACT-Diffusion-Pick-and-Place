"""Verify native ACT selection/ensembling on saved data; no robot access."""
import json
import time
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader
from lerobot.datasets.lerobot_dataset import LeRobotDataset
from lerobot.policies.act.configuration_act import ACTConfig
from lerobot.policies.act.modeling_act import ACTPolicy, ACTTemporalEnsembler
from lerobot.policies.factory import make_pre_post_processors
from act_robot_inference import configure_native_act, native_action
from check_act_live import NAMES


def main():
    torch.set_num_threads(4)
    model='/models/checkpoints/050000/pretrained_model'
    cfg=ACTConfig.from_pretrained(model)
    cfg.device='cpu'
    cfg.pretrained_backbone_weights=None
    configure_native_act(cfg,True,.01)
    assert cfg.n_action_steps==1 and cfg.temporal_ensemble_coeff==.01
    policy=ACTPolicy.from_pretrained(model,config=cfg).eval()
    pre,post=make_pre_post_processors(policy_cfg=cfg,pretrained_path=model,
        preprocessor_overrides={'device_processor':{'device':'cpu'}})
    data=LeRobotDataset('local/so101-cube-cup-validation',
        root=Path('/project/exports/so101-cube-cup-msi-76-val12/datasets/validation'),video_backend='pyav')
    batch=next(iter(DataLoader(data,batch_size=1,num_workers=0)))
    observation=({n:float(batch['observation.state'][0,i]) for i,n in enumerate(NAMES)},
                 {name:batch[f'observation.images.{name}'][0].permute(1,2,0).mul(255).round().byte().numpy()
                  for name in ('workspace','wrist')})
    # Capture the exact predictions used by select_action, then compare its
    # outputs with a fresh official ensembler receiving those same predictions.
    original_predict=policy.predict_action_chunk
    captured=[]
    def capture(batch):
        chunk=original_predict(batch)
        captured.append(chunk.clone())
        return chunk
    policy.predict_action_chunk=capture
    reference=ACTTemporalEnsembler(.01,100)
    times=[]
    for _ in range(4):
        t=time.perf_counter()
        actual=native_action(policy,pre,post,observation)
        times.append(1000*(time.perf_counter()-t))
        expected=post(reference.update(captured[-1])).cpu().numpy()[0]
        np.testing.assert_allclose(actual,expected,rtol=1e-5,atol=1e-5)
    assert len(captured)==4
    configure_native_act(cfg,False,.01)
    policy.reset()
    captured.clear()
    for i in range(5):
        actual=native_action(policy,pre,post,observation)
        expected=post(captured[0][:,i]).cpu().numpy()[0]
        np.testing.assert_allclose(actual,expected,rtol=1e-5,atol=1e-5)
    assert len(captured)==1
    result={'motor_access':False,'checkpoint':model,
            'native_temporal_ensemble_reference_matched':True,
            'coefficient':.01,'temporal_n_action_steps':1,
            'native_chunk_queue_matched':True,'queue_n_action_steps':100,
            'native_temporal_action_ms':times,
            'median_temporal_control_hz_without_io':1000/float(np.median(times[1:])),
            'gripper_contact_hold_default':False,'custom_rate_limits_in_native_mode':False,
            'note':'Saved dataset observation. Native synchronous temporal ensemble control cannot be assumed to reach 30 Hz on this CPU.'}
    out=Path('/project/outputs/inference/native-lerobot-check.json')
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2),flush=True)


if __name__=='__main__':main()
