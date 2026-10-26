# syntax=docker/dockerfile:1
# Initial build records resolved OS/Python/Python-package versions in /opt/environment.
FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1     HOME=/tmp/lerobot-home HF_HOME=/workspace/.cache/huggingface     HF_HUB_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1
# evdev (pulled in by pynput) compiles against Linux userspace input headers.
RUN apt-get update && apt-get install -y --no-install-recommends     build-essential linux-libc-dev ffmpeg libglib2.0-0 libgl1 libegl1 libxkbcommon0 libxi6 libxtst6 v4l-utils     && rm -rf /var/lib/apt/lists/*
COPY config/constraints.txt /opt/constraints.txt
RUN python -m pip install --index-url https://download.pytorch.org/whl/cpu     torch==2.10.0+cpu torchvision==0.25.0+cpu torchcodec==0.10.0
RUN python -m pip install --constraint /opt/constraints.txt 'lerobot[core_scripts,feetech]==0.6.1'     && python -m pip check
COPY scripts/check_environment.py /opt/check_environment.py
RUN mkdir -p /opt/environment && python /opt/check_environment.py     && python -m pip freeze --all > /opt/environment/pip-freeze.txt     && dpkg-query -W > /opt/environment/debian-packages.txt     && python --version > /opt/environment/python-version.txt
WORKDIR /workspace
USER 1000:1000
CMD ["python", "/opt/check_environment.py"]
