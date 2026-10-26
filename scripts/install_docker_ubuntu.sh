#!/usr/bin/env bash
# Review this file and obtain user approval before invoking it.
set -euo pipefail
if [[ "${1:-}" != "--approved" ]]; then
  echo 'Requires explicit user approval. Usage: bash scripts/install_docker_ubuntu.sh --approved' >&2
  exit 2
fi
. /etc/os-release
if [[ "$ID" != ubuntu || "$VERSION_ID" != 22.04 || "$(dpkg --print-architecture)" != amd64 ]]; then
  echo 'Host differs from inspected Ubuntu 22.04 amd64; stop and review.' >&2
  exit 1
fi
for package in docker.io docker-compose docker-compose-v2 docker-doc podman-docker containerd runc docker-ce docker-ce-cli containerd.io; do
  if dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q 'install ok installed'; then
    echo "Existing package $package found; stop and review instead of replacing it." >&2
    exit 1
  fi
done
if [[ -e /etc/apt/sources.list.d/docker.sources || -e /etc/apt/sources.list.d/docker.list || -e /etc/apt/keyrings/docker.asc ]]; then
  echo 'Docker repository configuration already exists; stop and review.' >&2
  exit 1
fi
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<'SOURCES'
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: jammy
Components: stable
Architectures: amd64
Signed-By: /etc/apt/keyrings/docker.asc
SOURCES
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
docker --version
docker compose version
sudo systemctl is-active docker
# Do not add the user to the docker group or launch any containers.
