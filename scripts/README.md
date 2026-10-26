# Scripts

Hardware and recording scripts will be added after selecting and verifying the
LeRobot version. This directory intentionally contains no executable robot
commands at Stage 2.

Future scripts must load ignored local hardware configuration, validate required
values, and avoid implicit calibration or unreviewed motor configuration. Test
recording and final collection must be separate, explicitly approved steps.

Stage 3 adds `install_docker_ubuntu.sh` (review and explicit installation approval
required) and `check_environment.py` (software-only imports and a synthetic
video round trip). Neither script connects to a robot. See `../docs/docker.md`.
