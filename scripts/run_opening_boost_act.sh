#!/bin/bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
exec sudo docker compose --env-file config/docker.env \
  -f compose.yaml -f compose.inference.yaml run --rm collector \
  python /opt/scripts/act_robot_inference.py \
  --until-enter --legacy-async --temporal-ensemble --ensemble-coefficient 0.01 \
  --contact-hold --gripper-source ensemble --gripper-hold-profile opening-boost
