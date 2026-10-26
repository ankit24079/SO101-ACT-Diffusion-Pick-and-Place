"""Compare FP32 CPU execution options on saved data; no device access."""
import json
import copy
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
    torch.set_num_threads(4)
    checkpoint = '/models/checkpoints/050000/pretrained_model'
    cfg = ACTConfig.from_pretrained(checkpoint)
    cfg.device = 'cpu'
    cfg.pretrained_backbone_weights = None
    policy = ACTPolicy.from_pretrained(checkpoint, config=cfg).eval()
    pre, post = make_pre_post_processors(policy_cfg=cfg, pretrained_path=checkpoint,
        preprocessor_overrides={'device_processor': {'device': 'cpu'}})
    dataset = LeRobotDataset('local/so101-cube-cup-validation',
        root=Path('/project/exports/so101-cube-cup-msi-76-val12/datasets/validation'),
        video_backend='pyav')
    batches = [next(iter(DataLoader(torch.utils.data.Subset(dataset, [i]),
        batch_size=1, num_workers=0))) for i in (0, 100, 300)]
    results = []
    with torch.inference_mode():
        references = [post(policy.predict_action_chunk(pre(b))).clone() for b in batches]
        original_backbone = copy.deepcopy(policy.model.backbone)
        for layout in ('contiguous', 'channels_last', 'frozen_contiguous', 'frozen_channels_last'):
            memory_format = torch.channels_last if layout.endswith('channels_last') else torch.contiguous_format
            policy.model.backbone = copy.deepcopy(original_backbone).to(memory_format=memory_format)
            if layout.startswith('frozen_'):
                sample = torch.zeros(1, 3, 480, 640).contiguous(memory_format=memory_format)
                policy.model.backbone = torch.jit.freeze(torch.jit.trace(
                    policy.model.backbone, sample, strict=False).eval())
            # Conv weights in channels-last select the optimized convolution path;
            # inputs, normalization, model weights and action semantics stay FP32.
            for threads in ((4,) if layout.startswith('frozen_') else (3, 4)):
                torch.set_num_threads(threads)
                errors = []
                for b, ref in zip(batches, references):
                    output = post(policy.predict_action_chunk(pre(b)))
                    assert output.shape == (1, 100, 6) and torch.isfinite(output).all()
                    errors.append(float((output-ref).abs().max()))
                for _ in range(2):
                    post(policy.predict_action_chunk(pre(batches[0])))
                samples = []
                for i in range(9):
                    start = time.perf_counter()
                    post(policy.predict_action_chunk(pre(batches[i % len(batches)])))
                    samples.append((time.perf_counter()-start)*1000)
                result = dict(layout=layout, threads=threads,
                    median_ms=statistics.median(samples), max_ms=max(samples),
                    max_action_difference=max(errors), equivalent=max(errors) <= .01,
                    samples_ms=samples)
                results.append(result)
                print(json.dumps(result), flush=True)
    report = dict(hardware_accessed=False, checkpoint=checkpoint, precision='float32',
        saved_validation_frame_indices=[0, 100, 300],
        timing_includes='preprocessing, full two-camera model, postprocessing',
        results=results)
    Path('/results/cpu-options.json').write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__':
    main()
