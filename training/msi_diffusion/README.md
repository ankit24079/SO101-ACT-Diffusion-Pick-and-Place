# Diffusion Policy on the same 76 cube-to-cup episodes

Uses LeRobot 0.6.1's stock trainer and native DiffusionPolicy. The original
64-training/12-validation split, six joint meanings, both cameras and 30 FPS
timebase are unchanged. No arm or camera devices are needed for training.
The ACT run and checkpoints are not modified.

## Baseline

- Two observation steps: previous and current state plus both camera frames.
- Temporal conditional U-Net widths 256/512/1024; separate ResNet-18 camera encoders.
- Source frames remain 640x480; model resizes to 320x240 with no crop so the whole
  scene remains visible. This preprocessing differs from the prior ACT model.
- Prediction horizon 16, execute 8 actions (about 0.27 seconds at nominal 30 FPS).
- Epsilon noise prediction; 100 noise timesteps and 20-step DDIM sampling.
- Native training defaults: Adam lr 1e-4, cosine schedule with 500 warmup steps.
- Batch size 8, seed 42, 100,000 optimizer updates, save every 10,000 updates.
- Native MIN_MAX state/action normalization fitted only to training data;
  padded episode-edge actions are excluded from training loss and validation.

These are a starting baseline, not a guarantee of better physical release or
faster laptop inference. Iterative diffusion inference must be benchmarked before
deployment; the old ACT robot-control script cannot load this model unchanged.

## MSI setup and launch

Use a separate diffusion environment with CUDA PyTorch compatible with the
allocation. Install `requirements.txt` there, leaving the working ACT environment
intact. No CPU PyTorch constraints from the recording image should be applied.
Run `bash setup_gpu_env.sh` after uploading the code: it creates a separate
`~/so101/venvs/lerobot-diffusion` environment based on the working ACT CUDA
Python and writes `~/activate-lerobot-diffusion.sh`. It does not replace the ACT
environment. It uses the existing ACT environment's Python directly when present,
so a changed or broken Miniforge module does not prevent activation. Override
`SO101_ACT_BASE_PYTHON` if that environment is stored elsewhere.

After login, inspect available partitions/GPUs and account authorization before
submitting. Account `hongj` was used previously. Supply current partition and GPU
resources to `sbatch`, rather than assuming GPU names match partition names.

```bash
export SO101_CODE_DIR="$HOME/so101/so101-diffusion-training-code"
export SO101_DATA_DIR="$HOME/so101/so101-cube-cup-msi-76-val12"
export SO101_OUTPUT_DIR="$HOME/so101/runs/diffusion-$(date +%Y%m%d-%H%M%S)"
export SO101_ACTIVATE_SCRIPT="$HOME/activate-lerobot-diffusion.sh"
sbatch --account=hongj --partition=YOUR_GPU_PARTITION --gres=gpu:YOUR_GPU:1 \
  "$SO101_CODE_DIR/train.sbatch"
```

Training logs print every 100 steps.
The batch job first performs one full-size forward/backward/update and a
20-step DDIM prediction on the GPU, writing `RUN_DIR-setup.json`. It stops if
that setup/memory check fails and does not save its test weights as training.
Training then starts fresh with seed 42.
Saved checkpoints use the native model and
processor format and support explicit `--resume`. This wrapper validates saved
checkpoints **after training completes**: a deterministic 256-observation subset
spread over all 12 validation episodes selects a candidate, which is then scored
over every held-out observation. Use `validate_diffusion.py --max-samples 0` to
fully score any additional checkpoint. Validation is open-loop imitation error,
not robot success rate.

The native diffusion output is the execution slice, beginning at horizon index
`n_obs_steps - 1` (index 1 here). Validation scores it against matching target and
padding slices; it does not compare the current prediction to a past action.
Fixed initial sampling noise (seed 42) makes checkpoint comparisons repeatable.
Compare physical MAE per joint with ACT. Their normalized losses use different
normalizers and prediction horizons and are not directly comparable.

## Checks

```bash
python -m unittest discover -s tests
python train_diffusion.py --data-root /path/to/so101-cube-cup-msi-76-val12 \
  --output-dir /tmp/unused-diffusion-run --print-command
python smoke_test.py --data-root /path/to/so101-cube-cup-msi-76-val12 \
  --output-dir /tmp/new-diffusion-smoke
```

The smoke test uses real data, a tiny U-Net and 64x64 model inputs to exercise a
single CPU training update, checkpoint saving/reloading and two held-out
predictions. Its output is not a trained policy or a full-size GPU memory test.
`Dockerfile.cpu-check` is a disposable CPU check environment, not an MSI GPU image.
