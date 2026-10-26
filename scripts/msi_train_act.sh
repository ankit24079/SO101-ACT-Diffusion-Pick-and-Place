#!/usr/bin/env bash
# Run from an allocated GPU compute node with the GPU environment activated.
set -euo pipefail
package_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
python - <<'PY'
import importlib.metadata
import torch
assert importlib.metadata.version('lerobot') == '0.6.1', 'Use the exported dataset version: LeRobot 0.6.1'
assert torch.cuda.is_available(), 'Activate your CUDA PyTorch environment on an allocated GPU node'
print('Training GPU:', torch.cuda.get_device_name(0))
PY
python -m lerobot.scripts.lerobot_train \
  --dataset.repo_id=local/so101-cube-cup-train \
  --dataset.root="$package_dir/datasets/train" \
  --dataset.video_backend=pyav \
  --policy.type=act \
  --policy.n_decoder_layers=4 \
  --policy.device=cuda \
  --policy.push_to_hub=false \
  --wandb.enable=false \
  --batch_size=8 \
  --num_workers=4 \
  --steps=100000 \
  --seed=42 \
  --output_dir="${SO101_TRAIN_OUTPUT:-$package_dir/training-output/act-$(date +%Y%m%d-%H%M%S)}" \
  "$@"
