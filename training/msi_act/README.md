# ACT training for the 64/12 SO-101 dataset on MSI

This code trains on 64 episodes and evaluates saved checkpoints on the 12 separate held-out episodes. It uses LeRobot 0.6.1's stock ACT trainer, both camera streams, and the six recorded joint/action values. It never accesses robot hardware or uploads models to Hugging Face.

The full architecture explicitly uses **4 Transformer action decoder layers**, as requested, rather than inheriting LeRobot's one-layer default. The CVAE posterior encoder and policy observation encoder each retain 4 layers; width 512, 8 heads, feed-forward width 3200, latent dimension 32 and chunk size 100 remain unchanged. This gives 67,751,686 trainable parameters for this six-action, two-camera model. Each decoder layer includes self-attention, cross-attention and a feed-forward network.

Use `train_act.py` from this updated code package. The earlier starter `train_act.sh` inside the previously exported dataset archive predates this architecture change. The dataset itself does not need to be uploaded again.

## Files

- `train_act.py`: dataset checks, native training invocation, checkpoint validation and model selection.
- `validate_act.py`: standalone held-out action prediction evaluation.
- `train.sbatch`: MSI Slurm entry point, including resume support.
- `smoke_test.py`: one CPU model update, saved-checkpoint reload and two-sample validation (tiny model by default; use --full-architecture for the full model). This is a software test, not useful policy training.
- `common.py` and `tests/`: split/feature checks and metric/command tests.

## Data and environment

Extract `so101-cube-cup-msi-76-val12.tar.gz` and verify its checksums first. Pass its top-level extracted directory as `--data-root`; do not pass `datasets/train` directly. This code rejects the earlier 68/8 package.

Use Python 3.12 and LeRobot 0.6.1 in a dedicated environment. Install a CUDA-enabled PyTorch and matching torchvision build supported by your MSI GPU/driver and site modules. Then install the training extra, which includes Accelerate:

```bash
python -m pip install 'lerobot[training]==0.6.1' 'av==15.1.0'
python -m pip check
python -c 'import torch, accelerate, importlib.metadata; print(importlib.metadata.version("lerobot")); print(torch.__version__, torch.cuda.is_available())'
```

Provision the environment using your group's MSI instructions. The collector image has CPU-only Torch and is missing Accelerate; do not copy it as the MSI GPU training environment. This project does not install or modify site modules automatically.

ACT uses pretrained ResNet-18 weights by default. Cache them before an offline batch job using a network-enabled environment allowed by MSI:

```bash
python -c 'from torchvision.models import resnet18, ResNet18_Weights; resnet18(weights=ResNet18_Weights.IMAGENET1K_V1)'
```

For a deliberately unpretrained backbone use `--no-pretrained-backbone`; it changes the experiment and may require more data/training. Both cameras remain 640x480; no video extraction is needed.

## Run in a GPU allocation

After activating the GPU environment, run on an allocated compute node, not a login node:

```bash
python ~/so101/so101-act-training-code/train_act.py \
  --data-root ~/so101/so101-cube-cup-msi-76-val12 \
  --output-dir ~/so101/runs/act-cube-cup-001
```

Defaults: 100000 optimizer steps, batch size 8, seed 42, four data workers, action chunks of 100 saved timesteps, and a checkpoint every 10000 steps. This uses the dataset's nominal 30 FPS, not the 60 Hz collection control loop. Training images, measured follower state and sent action labels come from the existing dataset.

Override fresh-training parameters as needed:

```bash
python train_act.py --data-root /path/to/so101-cube-cup-msi-76-val12 \
  --output-dir /path/to/new-run --steps 100000 --batch-size 4 --workers 4
```

If GPU memory is insufficient, lower batch size. A fresh run refuses an existing output directory. Training duration and robot success are not guaranteed by these defaults.

## Slurm submission

Create a shell script that loads the site modules you need and activates your environment, for example `~/activate-lerobot-gpu.sh`. Its exact contents depend on your existing MSI environment. The script must be readable by the job and not start training itself.

Set these paths on the MSI login node:

```bash
export SO101_CODE_DIR="$HOME/so101/so101-act-training-code"
export SO101_DATA_DIR="$HOME/so101/so101-cube-cup-msi-76-val12"
export SO101_OUTPUT_DIR="$HOME/so101/runs/act-cube-cup-001"
export SO101_ACTIVATE_SCRIPT="$HOME/activate-lerobot-gpu.sh"
sbatch --account=YOUR_ACCOUNT --partition=msigpu --gres=gpu:1 "$SO101_CODE_DIR/train.sbatch"
```

Replace `YOUR_ACCOUNT` with your authorized MSI allocation. Verify that your account can use the requested partition/GPU and adjust the 12-hour walltime request to the site's limits. MSI documents `msigpu` with a generic one-GPU request; your group may use another partition. This job template has not been submitted or tested on MSI.

Monitor with `squeue --me` and the generated `so101-act-<jobid>.out/.err` files. No training starts on your robot when you submit this job.

## Resume after a stopped job

Use the same output directory and `--resume`:

```bash
python train_act.py --data-root /path/to/so101-cube-cup-msi-76-val12 \
  --output-dir /path/to/existing-run --resume
```

Or, with the same Slurm environment variables:

```bash
sbatch --account=YOUR_ACCOUNT --partition=msigpu --gres=gpu:1 "$SO101_CODE_DIR/train.sbatch" --resume
```

Resume loads the latest numeric checkpoint's native `train_config.json` and training state, including the original target step count. Fresh-run step, batch-size, worker and backbone CLI overrides are not applied on resume. If no complete resumable checkpoint exists, the wrapper fails explicitly.

Start a fresh output directory for the four-decoder-layer experiment. Resuming a one-layer run retains its saved architecture; resume does not add layers to an existing checkpoint.

## Validation and outputs

After native training finishes, the wrapper evaluates all saved numeric checkpoints on the held-out dataset. This happens after training, not inside the optimizer loop. Only checkpoint processors/training normalization statistics are used; validation data never enters gradient updates or normalization fitting.

- `checkpoints/<step>/pretrained_model/`: policy weights, config and saved preprocessing/postprocessing. Native checkpoint training state is retained separately for resume.
- `validation/<step>.json`: normalized chunk L1 and per-joint errors in degrees / gripper percentage points.
- `validation-summary.json`: checkpoint with the lowest held-out normalized chunk L1.

Validation calls ACT's zero-latent inference path, uses future action chunks from the native dataset reader, and excludes `action_is_pad` at episode boundaries. It measures supervised imitation error, not physical pick-and-place success. Comparing checkpoints on validation is model selection; there is no independent test set here.

For faster checks evaluate just the latest checkpoint (`--validate-latest-only`) or sample validation (`--validation-max-samples 120`). The report explicitly marks sampled evaluation as partial. Defaults use all 6676 held-out observations. Do not interpret sampled results as full validation.

Standalone evaluation:

```bash
python validate_act.py \
  --checkpoint /path/to/run/checkpoints/100000/pretrained_model \
  --data-root /path/to/so101-cube-cup-msi-76-val12 \
  --output /path/to/run/validation/manual.json
```

For later deployment, transfer the complete selected `pretrained_model` directory, including both processor JSON files and their safetensors. Deployment and physical testing are separate tasks; this code does not move any arm. Keep the training camera/base arrangement and verify compatibility with calibration on the deployment machine.

## Local checks performed

The collector CPU environment tested both the reduced-size configuration and the full four-decoder-layer configuration on real two-camera data. The full-model check verifies nonzero finite gradients in all four decoder blocks, one optimizer update, checkpoint/processor save and reload, and two held-out inference samples including an episode-end padded chunk. Pretrained backbone initialization is disabled only for these offline software tests. Padding, nonfinite values, split overlap, training-only command construction and native resume-path tests are included.

The full stock trainer could parse the generated configuration but could not start in the collector image because its optional `accelerate` dependency is absent. No packages were installed into that environment. Full GPU training, full checkpoint validation and MSI job submission have not been executed. The smoke model is not a trained policy and is not part of this code package.

To repeat tests in an environment containing LeRobot and CPU Torch:

```bash
python -m unittest discover -s tests -v
python smoke_test.py --data-root /path/to/so101-cube-cup-msi-76-val12 --output-dir /path/to/new-smoke-output
```

## References

- Version-matched ACT implementation: https://github.com/huggingface/lerobot/blob/v0.6.1/src/lerobot/policies/act/modeling_act.py
- Native training entry point: https://github.com/huggingface/lerobot/blob/v0.6.1/src/lerobot/scripts/lerobot_train.py
- MSI shared GPU partitions: https://userdocs.msi.umn.edu/compute/shared_partitions.html
- MSI Slurm guide: https://userdocs.msi.umn.edu/compute/slurm_job_submission.html
