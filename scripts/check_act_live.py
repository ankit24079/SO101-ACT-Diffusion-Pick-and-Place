"""Read-only live ACT prediction: no torque, configuration or goal writes."""
import dataclasses
import json
import time
from pathlib import Path

import torch
from PIL import Image
from lerobot.policies.act.configuration_act import ACTConfig
from lerobot.policies.act.modeling_act import ACTPolicy
from lerobot.policies.factory import make_pre_post_processors
from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig
from teleop_cameras import CameraMonitor

NAMES = ('shoulder_pan', 'shoulder_lift', 'elbow_flex', 'wrist_flex', 'wrist_roll', 'gripper')
CALIBRATION = Path('/calibration/robots/so101_follower/repaired-shoulder-1792448625156379989/cup_follower_repaired.json')


def main():
    torch.set_num_threads(4)
    out = Path('/workspace/outputs/inference')/str(time.time_ns())
    out.mkdir(parents=True)
    model = '/models/checkpoints/050000/pretrained_model'
    cfg = ACTConfig.from_pretrained(model)
    cfg.device = 'cpu'
    cfg.pretrained_backbone_weights = None
    policy = ACTPolicy.from_pretrained(model, config=cfg).eval()
    pre, post = make_pre_post_processors(policy_cfg=cfg, pretrained_path=model,
        preprocessor_overrides={'device_processor': {'device': 'cpu'}})
    robot = SO101Follower(SO101FollowerConfig(port='/dev/so101-follower',
        id=CALIBRATION.stem, calibration_dir=CALIBRATION.parent))
    cams = CameraMonitor()
    try:
        robot.bus.connect(handshake=False)
        actual = {n: dataclasses.asdict(c) for n, c in robot.bus.read_calibration().items()}
        if actual != json.loads(CALIBRATION.read_text()):
            raise RuntimeError('Stored follower calibration differs from the recording calibration')
        for n in NAMES:
            if robot.bus.read('Torque_Enable', n, normalize=False, num_retry=2):
                raise RuntimeError(f'{n}: torque is already enabled; read-only check stopped')
        cams.start()
        images, times = cams.snapshot()
        positions = robot.bus.sync_read('Present_Position', num_retry=2)
        batch = {'observation.state': torch.tensor([[positions[n] for n in NAMES]], dtype=torch.float32),
                 'observation.elapsed_time': torch.zeros(1, 1),
                 'observation.camera_time': torch.zeros(1, 2)}
        for n, image in images.items():
            Image.fromarray(image).save(out/f'{n}.jpg')
            batch[f'observation.images.{n}'] = torch.from_numpy(image.copy()).permute(2, 0, 1).unsqueeze(0).float()/255
        durations = []
        with torch.inference_mode():
            for _ in range(4):
                t = time.perf_counter()
                chunk = post(policy.predict_action_chunk(pre(batch))).cpu()
                durations.append(1000*(time.perf_counter()-t))
        assert chunk.shape == (1, 100, 6) and torch.isfinite(chunk).all()
        report = {'checkpoint': model, 'motor_writes': False, 'torque_enabled': False,
                  'current_state': positions, 'chunk_shape': list(chunk.shape),
                  'first_action': dict(zip(NAMES, chunk[0, 0].tolist())),
                  'first_action_delta': {n: float(chunk[0, 0, i])-positions[n] for i,n in enumerate(NAMES)},
                  'prediction_times_ms': durations, 'preview_dir': str(out)}
        (out/'read-only-prediction.json').write_text(json.dumps(report, indent=2)+'\n')
        torch.save(chunk, out/'predicted_chunk.pt')
        print(json.dumps(report, indent=2), flush=True)
    finally:
        cams.close()
        if robot.bus.port_handler.is_open:
            robot.bus.port_handler.closePort()


if __name__ == '__main__':
    main()
