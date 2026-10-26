# SO101 ACT & Diffusion Policy — Pick and Place

An end-to-end vision-based robotic manipulation project using a LeRobot SO-101
leader/follower pair with workspace and wrist cameras. The project combines
teleoperated demonstration collection, ACT and Diffusion Policy training,
held-out evaluation, and physical cube-to-cup placement with ACT.

## Project overview

- Target dataset: 100 cube-to-cup demonstration episodes, split into 85 training
  and 15 validation episodes. Source data is nominally 30 FPS with six joint values
  and two 640x480 RGB camera streams.
- Completed a 100,000-step ACT training run with four decoder layers and
  held-out checkpoint evaluation.
- Demonstrated autonomous cube-to-cup placement with ACT during attended trials,
  using asynchronous temporal averaging and gripper hold/release/close control.
- Trained Diffusion Policy and completed held-out checkpoint evaluation and a
  causal temporal-ensembling comparison with ACT on the same validation recordings.

## Validation results

Average current-action errors against recorded demonstrations:

| Policy | Temporal ensembling | Mean arm error | Gripper error |
| --- | --- | ---: | ---: |
| ACT | Disabled | 1.96 degrees | 1.37 percentage points |
| ACT | Coefficient -0.5 | 2.08 degrees | 1.47 percentage points |
| Diffusion Policy | Disabled | 1.31 degrees | 0.84 percentage points |
| Diffusion Policy | Coefficient -0.5 | 1.44 degrees | 0.97 percentage points |

With temporal ensembling applied to both policies, Diffusion Policy reduced
mean arm error by **31%** and gripper error by **34%** compared with ACT.
These are offline imitation errors, not measured pick-and-place success rates.
The temporal replay assumes predictions at 30 Hz with zero inference latency,
resets at episode boundaries, and excludes deployment-specific gripper overrides.
Diffusion temporal averaging is an experimental option; its native execution
uses an eight-action queue. Physical deployment was demonstrated with ACT;
Diffusion Policy was evaluated offline.

Datasets, trained weights, run logs, generated export archives, actual device
configuration, and hardware-specific calibration are stored separately and are
excluded from this code repository.

## Code map

| Location | Purpose |
| --- | --- |
| `Dockerfile`, `compose*.yaml` | CPU recording/diagnostic container and hardware overlays |
| `config/*.example` | Templates for local device and dataset settings |
| `scripts/official_teleop.py`, `scripts/official_episode.py` | Official LeRobot teleoperation and episode capture wrapper |
| `scripts/export_msi_dataset.py`, `scripts/package_msi_export.py` | Export the selected train/validation split |
| [ACT training](training/msi_act/README.md) | Stock LeRobot ACT training and held-out evaluation |
| [Diffusion training](training/msi_diffusion/README.md) | Diffusion Policy training, validation, CPU smoke test and Slurm launcher |
| `training/compare_temporal_policies.py` | Causal offline comparison of ACT and Diffusion Policy with and without temporal ensembling |
| `scripts/act_robot_inference.py` | Attended ACT deployment and diagnostic logging |
| `scripts/gripper_contact_hold.py` | Optional custom gripper policies and post-release closure |
| `tests/` | Control, gripper and temporal-averaging checks |

The old experiment launchers and diagnostic utilities are included for
reproducibility. Some reference this project's original local calibration and
checkpoint paths. Review and adapt those paths to your own setup before use.

## Setup

The recording image uses Python 3.12 and LeRobot 0.6.1 with CPU PyTorch.
See [Docker setup](docs/docker.md) and the [configuration template](config/docker.env.example).
Create the ignored `config/docker.env` using verified device identities and host
permissions, and provide the matching local calibration files. Hardware roles must
be identified by persistent USB paths, not assumed `/dev/ttyACM*` enumeration.

For GPU training, use a separate CUDA environment. Follow the relevant
training README; do not apply the recording container's CPU constraints to the
GPU environment. Training expects a separately exported
dataset package with `splits.json` and native LeRobot
`datasets/train` and `datasets/validation` directories.

## Inference

- [Native LeRobot ACT and wrapper behavior](docs/native-act-inference.md)
- [More responsive temporal averaging and post-release closure](docs/responsive-act-inference.md)
- [Gripper opening boost](docs/gripper-opening-boost.md)

The custom gripper logic is a position-based heuristic. It does not measure
grip force or visually confirm that an object landed in the cup. Custom actions
are deployment adjustments, not changes to the learned ACT architecture.
The CPU laptop can produce stale predictions; keep the prediction-age and motor
fault checks active. Keep the power disconnect accessible during physical trials.

## Checks

Run pure control tests on the laptop:

```bash
python3 -m unittest discover -s tests -p 'test*gripper*py'
python3 -m unittest discover -s tests -p 'test_inference_timing.py'
```

The temporal-ensemble tests require NumPy. Training workflow tests and real-data
smoke tests require the policy-specific environment and the separately supplied
dataset package; see each training README for commands. These checks do not
require connecting the robot.

## Contributors

See [CONTRIBUTORS.md](CONTRIBUTORS.md).
