"""Camera-only LeRobot check. No robot imports or serial device access."""
import concurrent.futures
import json
import time
from pathlib import Path

import cv2
from PIL import Image
from lerobot.cameras.opencv import OpenCVCamera, OpenCVCameraConfig


def check(item):
    name, path = item
    camera = OpenCVCamera(OpenCVCameraConfig(
        index_or_path=path, width=640, height=480, fps=30, fourcc="MJPG", warmup_s=2,
    ))
    try:
        camera.connect()
        times = []
        for index in range(150):
            frame = camera.read()
            times.append(time.perf_counter())
            if tuple(frame.shape) != (480, 640, 3):
                raise RuntimeError(f"Unexpected {name} shape: {frame.shape}")
            if index == 30:
                Image.fromarray(frame).save(output / f"{name}.jpg")
        intervals = [b - a for a, b in zip(times, times[1:])]
        fourcc = int(camera.videocapture.get(cv2.CAP_PROP_FOURCC))
        return {
            "camera": name, "shape": [480, 640, 3], "frames": len(times),
            "requested_fps": 30,
            "reported_fps": camera.videocapture.get(cv2.CAP_PROP_FPS),
            "fourcc": "".join(chr((fourcc >> (8 * i)) & 255) for i in range(4)),
            "delivered_fps": round((len(times)-1)/(times[-1]-times[0]), 2),
            "max_delivery_interval_ms": round(max(intervals)*1000, 2),
            "delivery_intervals_over_50ms": sum(t > .05 for t in intervals),
            "note": "Delivery timing only; does not establish sensor synchronization or dropped-frame counts.",
        }
    finally:
        if camera.is_connected:
            camera.disconnect()


if __name__ == "__main__":
    output = Path("/workspace/outputs/camera-check-docker")
    output.mkdir(parents=True, exist_ok=True)
    print("LeRobot camera discovery:", OpenCVCamera.find_cameras(), flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(check, [("workspace", "/dev/video0"), ("wrist", "/dev/video1")]))
    (output / "report.json").write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=2), flush=True)
    print("Camera capture complete; no serial devices mapped or opened.")
