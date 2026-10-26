# Stage 3 Docker proposal

Prepared October 15, 2026. Docker is installed and the image build succeeded;
see `reproducibility.md` for the user-verified image ID. Runtime and hardware
verification remain pending. Docker is the preferred
candidate because the host Python is 3.10 and the selected release needs 3.12.
Native Python remains an alternative if container camera previews or input
handling prove unreliable. Neither option has passed a hardware test yet.

## Selected environment

- LeRobot 0.6.1, the latest release listed by the upstream release page when checked.
  The main branch reports 0.6.2; it is not the selected release.
- Python 3.12 on Debian bookworm, inside the container only.
- CPU PyTorch 2.10.0, torchvision 0.25.0, TorchCodec 0.10.0.
- LeRobot extras: core_scripts and feetech.
- FFmpeg from Debian; a synthetic video encode/decode check runs during build.

Primary references:

- https://github.com/huggingface/lerobot/releases/tag/v0.6.1
- https://github.com/huggingface/lerobot/blob/v0.6.1/pyproject.toml
- https://huggingface.co/docs/lerobot/installation
- https://github.com/meta-pytorch/torchcodec#installing-torchcodec
- https://pytorch.org/get-started/previous-versions/
- https://docs.docker.com/engine/install/ubuntu/

The release source controls package extras and entry points; live documentation
may describe newer main-branch code. Inspect installed CLI help before preparing
hardware commands.

## Approval 1: install Docker on the host

Review `scripts/install_docker_ubuntu.sh`. The exact proposed invocation, from
this project root, is:

```bash
bash scripts/install_docker_ubuntu.sh --approved
```

The script uses sudo because installing host packages, a repository signing key,
and an apt source requires administrative access. It installs Docker Engine,
its CLI, containerd, Buildx, and Compose from Docker's official Ubuntu repository.
Package installation normally starts the Docker/containerd services and Docker
can configure host networking/firewall rules. It stops if conflicting packages
or the usual Docker repository files already exist. It does not remove packages,
add docker-group membership, build images, or start containers. Actual package
versions must be recorded after installation; they are resolved by apt at that
time. Sudo authentication must be entered locally, never shared in chat.

## Approval 2: build and verify software

After Docker installation is verified, request separate approval for:

```bash
sudo docker compose --env-file config/docker.env build collector
```

Before this command, populate ignored `config/docker.env` with HOST_UID/HOST_GID
from `id -u`/`id -g`. Other variables are only needed for hardware overrides.
The build downloads the base image, Debian packages, and Python dependencies.
The Dockerfile executes software-only imports and a temporary synthetic video
round trip; it does not map USB devices. Sudo is used for the system Docker
socket without changing user permissions. Diagnose any failure from its output.
With 27 GiB initially free, recheck free space before the build and recording.
Do not prune unrelated images or data automatically.

After a successful build, save image inspect output (including image ID),
`pip-freeze.txt`, `debian-packages.txt`, and `python-version.txt` from
`/opt/environment/` to ignored `outputs/environment/`. Also record Docker,
Compose, and base-image digest. This initial recipe pins key ML packages but
allows transitive and OS dependencies to resolve. Preserve the built image
(e.g. an approved image export) for exact reuse; do not call this a complete
lockfile or a bit-for-bit reproducible rebuild.

Create `datasets`, `outputs`, `logs`, and `.cache` as the host user before running
Compose. Bind mounts refuse to create missing source directories so Docker
does not silently make them root-owned. After approval, software checks can run
with the base Compose service; its default command accesses no devices.

## Later hardware access

Runtime note: the host numeric UID has no named account in the image. Compose
sets USER/LOGNAME and TORCHINDUCTOR_CACHE_DIR explicitly so Python getpass and
PyTorch cache initialization do not require a passwd lookup. The process still
runs as the configured host UID/GID. This Compose-only correction needs no
image rebuild; rerun the software check to verify it as the runtime user.

The base service maps no hardware, requests no GPU, publishes no ports, mounts
no Docker socket, and does not use privileged mode. It runs with the host numeric
UID/GID, drops capabilities, and persists datasets, outputs, logs, and the HF
cache in host directories. HF Hub offline mode is enabled by default.

Only after Stage 4 identification and hardware access approval, use the local
persistent device paths and numeric device group IDs with:

```bash
sudo docker compose --env-file config/docker.env -f compose.yaml -f compose.hardware.yaml config --quiet
```

This validates configuration without starting a container. The hardware override
maps exactly two controller nodes and one camera capture node. Add
`-f compose.wrist.yaml` for a verified second camera. Container paths are
`/dev/so101-leader`, `/dev/so101-follower`, `/dev/workspace-camera`, and optionally
`/dev/wrist-camera`; future LeRobot commands must use those paths. Recreate
containers after reconnecting devices; mappings refer to the nodes resolved at
creation time. Group IDs must be checked on the host rather than assumed.

No camera preview, keyboard-control, calibration mount, or teleoperation command
is ready yet. Validate preview and stop controls before torque. Existing host
calibration must first be located and reviewed in Stage 5; the host home directory
is not mounted. Do not let an empty container calibration cache trigger automatic
calibration. Inspect and approve calibration reuse/mounting before any robot
connection. Graphical preview transport will be chosen after camera tests; no
X server permissions or host display mounts are changed by this proposal.

## Build diagnosis: evdev input headers

The initial build failed compiling evdev because linux/input.h and
linux/input-event-codes.h were absent. The image now includes linux-libc-dev
(userspace Linux API headers) and build-essential (compiler tools). These are
container dependencies; no host kernel header installation is required.
Python development headers are supplied by the Python base image. Rebuild
verification passed in the successful image build recorded in `reproducibility.md`.
