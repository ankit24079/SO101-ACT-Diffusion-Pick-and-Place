"""Software-only import and codec round-trip check; never opens hardware."""
import importlib.metadata as metadata
import shutil
import tempfile
from pathlib import Path

import av
import numpy as np
import torch
import torchvision
from torchcodec.decoders import VideoDecoder
from lerobot.datasets.lerobot_dataset import LeRobotDataset
from lerobot.robots.so_follower import SO101FollowerConfig
from lerobot.teleoperators.so_leader import SO101LeaderConfig

for package in ("lerobot", "torch", "torchvision", "torchcodec", "av", "opencv-python-headless", "feetech-servo-sdk"):
    print(f"{package}=={metadata.version(package)}")
assert torch.version.cuda is None, "Expected CPU-only torch"
for command in ("lerobot-find-cameras", "lerobot-find-port", "lerobot-teleoperate", "lerobot-record", "ffmpeg", "v4l2-ctl"):
    assert shutil.which(command), f"Missing command: {command}"
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "codec-test.mp4"
    with av.open(str(path), mode="w") as container:
        stream = container.add_stream("libx264", rate=30)
        stream.width = 64
        stream.height = 48
        stream.pix_fmt = "yuv420p"
        for _ in range(3):
            frame = av.VideoFrame.from_ndarray(np.zeros((48, 64, 3), dtype=np.uint8), format="rgb24")
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    decoder = VideoDecoder(str(path), device="cpu")
    assert len(decoder) == 3
    assert tuple(decoder[0].shape) == (3, 48, 64)
print("Software and CPU video round-trip checks passed. Hardware was not accessed.")
