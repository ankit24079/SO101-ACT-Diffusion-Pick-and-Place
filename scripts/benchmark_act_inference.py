"""CPU inference timing with a saved observation; no hardware devices needed."""
import json
import statistics
import time
from pathlib import Path

import torch
from torch.utils.data import DataLoader
from lerobot.datasets.lerobot_dataset import LeRobotDataset
from lerobot.policies.act.configuration_act import ACTConfig
from lerobot.policies.act.modeling_act import ACTPolicy
from lerobot.policies.factory import make_pre_post_processors


def main():
    checkpoint = '/models/checkpoints/050000/pretrained_model'
    cfg = ACTConfig.from_pretrained(checkpoint)
    cfg.device = 'cpu'
    # The complete trained backbone is already in model.safetensors.
    cfg.pretrained_backbone_weights = None
    torch.set_num_threads(4)
    policy = ACTPolicy.from_pretrained(checkpoint, config=cfg).eval()
    pre, post = make_pre_post_processors(
        policy_cfg=cfg, pretrained_path=checkpoint,
        preprocessor_overrides={'device_processor': {'device': 'cpu'}},
    )
    dataset = LeRobotDataset('local/so101-cube-cup-validation',
        root=Path('/project/exports/so101-cube-cup-msi-76-val12/datasets/validation'),
        video_backend='pyav')
    batch = next(iter(DataLoader(dataset, batch_size=1, num_workers=0)))
    results = []
    with torch.inference_mode():
        for threads in (1, 2, 4):
            torch.set_num_threads(threads)
            for _ in range(2):
                post(policy.predict_action_chunk(pre(batch)))
            samples = []
            for _ in range(6):
                start = time.perf_counter()
                output = post(policy.predict_action_chunk(pre(batch)))
                samples.append(time.perf_counter()-start)
                assert output.shape == (1, 100, 6) and torch.isfinite(output).all()
            results.append({'threads': threads, 'median_ms': 1000*statistics.median(samples),
                            'max_ms': 1000*max(samples)})
            print(json.dumps(results[-1]), flush=True)
    result = {'checkpoint': checkpoint, 'hardware_accessed': False,
              'input': 'saved two-camera validation observation, batch size 1',
              'timings_include': 'preprocessing, full model prediction, postprocessing',
              'camera_capture_and_motor_io_included': False, 'results': results}
    out = Path('/project/outputs/inference')
    out.mkdir(exist_ok=True, parents=True)
    (out/'cpu-benchmark.json').write_text(json.dumps(result, indent=2)+'\n')


if __name__ == '__main__':
    main()
