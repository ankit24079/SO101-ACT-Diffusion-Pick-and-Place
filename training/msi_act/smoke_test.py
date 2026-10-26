"""One tiny CPU ACT update and checkpoint/validation test; not a trained policy."""
import argparse
import json
from pathlib import Path

from common import check_package, check_version


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--full-architecture', action='store_true', help='Test the full four-decoder-layer architecture instead of the tiny model')
    args = parser.parse_args()
    check_version()
    root = check_package(args.data_root)
    if args.output_dir.exists():
        raise RuntimeError('Choose a new smoke-test output directory')
    import torch
    from torch.utils.data import DataLoader
    from lerobot.datasets.dataset_metadata import LeRobotDatasetMetadata
    from lerobot.datasets.factory import resolve_delta_timestamps
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    from lerobot.policies.act.configuration_act import ACTConfig
    from lerobot.policies.factory import make_policy, make_pre_post_processors
    from validate_act import evaluate

    torch.set_num_threads(4)
    torch.manual_seed(42)
    if args.full_architecture:
        cfg = ACTConfig(device='cpu', n_decoder_layers=4,
                        pretrained_backbone_weights=None, push_to_hub=False)
    else:
        cfg = ACTConfig(device='cpu', chunk_size=2, n_action_steps=2, dim_model=64,
                        dim_feedforward=256, n_heads=4, n_encoder_layers=1,
                        n_decoder_layers=1, n_vae_encoder_layers=1,
                        pretrained_backbone_weights=None, push_to_hub=False)
    meta = LeRobotDatasetMetadata('local/so101-cube-cup-train', root=root/'datasets/train')
    policy = make_policy(cfg, ds_meta=meta)
    pre, post = make_pre_post_processors(policy_cfg=cfg, dataset_stats=meta.stats)
    dataset = LeRobotDataset('local/so101-cube-cup-train', root=root/'datasets/train',
                             delta_timestamps=resolve_delta_timestamps(cfg, meta), video_backend='pyav')
    batch = next(iter(DataLoader(dataset, batch_size=1, num_workers=0)))
    processed = pre(batch)
    policy.train()
    optimizer = torch.optim.AdamW(policy.parameters(), lr=1e-5)
    loss, details = policy.forward(processed)
    assert torch.isfinite(loss)
    loss.backward()
    decoder_blocks_with_gradients = sum(
        any(p.grad is not None and torch.isfinite(p.grad).all() and p.grad.abs().sum() > 0
            for p in layer.parameters()) for layer in policy.model.decoder.layers)
    assert decoder_blocks_with_gradients == cfg.n_decoder_layers
    optimizer.step()
    checkpoint = args.output_dir/'pretrained_model'
    checkpoint.mkdir(parents=True)
    policy.save_pretrained(checkpoint)
    pre.save_pretrained(checkpoint)
    post.save_pretrained(checkpoint)
    report = evaluate(checkpoint, root, device='cpu', batch_size=1, workers=0,
                      max_samples=2, output=args.output_dir/'validation.json')
    result = {'test_only_not_a_trained_policy': True, 'one_step_loss': float(loss.detach()),
              'full_architecture': args.full_architecture,
              'decoder_layers': cfg.n_decoder_layers,
              'trainable_parameters': sum(p.numel() for p in policy.parameters() if p.requires_grad),
              'decoder_blocks_with_gradients': decoder_blocks_with_gradients,
              'loss_details': details, 'checkpoint_reloaded': True, 'validation': report}
    (args.output_dir/'smoke-test.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
