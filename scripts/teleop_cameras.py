"""Background LeRobot camera capture for the initial teleoperation check."""
import json
import threading
import time
from pathlib import Path

from PIL import Image
from lerobot.cameras.opencv import OpenCVCamera, OpenCVCameraConfig


class CameraMonitor:
    def __init__(self):
        self.output = Path('/workspace/outputs/teleop-cameras') / str(time.time_ns())
        self.output.mkdir(parents=True, exist_ok=False)
        self.stop = threading.Event()
        self.cameras = {}
        self.threads = []
        self.errors = {}
        self.samples = {'workspace': [], 'wrist': []}
        self.latest = {}
        self.lock = threading.Lock()
        self.started = time.monotonic()

    def start(self):
        for name, path in [('workspace', '/dev/video0'), ('wrist', '/dev/video1')]:
            camera = OpenCVCamera(OpenCVCameraConfig(
                index_or_path=path, width=640, height=480, fps=30, fourcc='MJPG', warmup_s=2,
            ))
            self.cameras[name] = camera
            camera.connect()
            frame = camera.read()
            if tuple(frame.shape) != (480, 640, 3):
                raise RuntimeError(f'{name}: unexpected image shape {frame.shape}')
            with self.lock:
                self.latest[name] = (frame, time.monotonic())
            Image.fromarray(frame).save(self.output / f'{name}-initial.jpg')
        self.started = time.monotonic()
        for name in self.cameras:
            thread = threading.Thread(target=self.capture, args=(name,), daemon=True)
            self.threads.append(thread)
            thread.start()
        # Sequential camera warmup leaves the first initial frame stale.
        # Require fresh frames published by BOTH capture threads before callers
        # can start recording or enable torque.
        deadline = time.monotonic() + 5
        while True:
            if self.errors:
                raise RuntimeError(f'Camera capture failed during startup: {dict(self.errors)}')
            now = time.monotonic()
            with self.lock:
                ready = all(self.samples[name] and now-self.latest[name][1] < .1
                            for name in self.cameras)
                ages = {name: round((now-self.latest[name][1])*1000, 1)
                        for name in self.cameras}
            if ready:
                break
            if now >= deadline:
                raise RuntimeError(f'Camera startup did not deliver fresh frames from both cameras: {ages} ms')
            time.sleep(.005)
        print(f'Both cameras active at requested 640x480/30 FPS. Preview snapshots: {self.output}', flush=True)

    def capture(self, name):
        try:
            while not self.stop.is_set():
                frame = self.cameras[name].read()
                elapsed = time.monotonic()-self.started
                if tuple(frame.shape) != (480, 640, 3):
                    raise RuntimeError(f'Unexpected shape: {frame.shape}')
                self.samples[name].append(elapsed)
                with self.lock:
                    self.latest[name] = (frame, time.monotonic())
                # Keep capture free of JPEG encoding and disk writes. Initial
                # previews and dataset review frames provide visual inspection.
        except Exception as error:
            self.errors[name] = str(error)

    def check(self):
        if self.errors:
            raise RuntimeError(f'Camera capture failed: {dict(self.errors)}')
        now = time.monotonic()-self.started
        for name, times in self.samples.items():
            if now-(times[-1] if times else 0) > 1:
                raise RuntimeError(f'{name}: no delivered frame for over one second')

    def snapshot(self):
        self.check()
        with self.lock:
            images = {name: self.latest[name][0].copy() for name in ('workspace', 'wrist')}
            times = [self.latest[name][1] for name in ('workspace', 'wrist')]
        return images, times

    def close(self):
        self.stop.set()
        for thread in self.threads:
            thread.join(timeout=2)
        for name, camera in self.cameras.items():
            try:
                if camera.is_connected:
                    camera.disconnect()
            except Exception as error:
                self.errors[name] = str(error)
        results = {}
        for name, times in self.samples.items():
            intervals = [b-a for a,b in zip(times, times[1:])]
            results[name] = {
                'frames': len(times), 'delivery_times_seconds': list(times),
                'delivered_fps': (len(times)-1)/(times[-1]-times[0]) if len(times)>1 else None,
                'max_delivery_interval_ms': max(intervals)*1000 if intervals else None,
                'intervals_over_50ms': sum(x>.05 for x in intervals),
            }
        report = {'requested_width': 640, 'requested_height': 480, 'requested_fps': 30,
                  'errors': dict(self.errors), 'cameras': results,
                  'note': 'Preview snapshots and delivery timing only; not a LeRobot dataset or sensor synchronization proof.'}
        (self.output/'report.json').write_text(json.dumps(report, indent=2)+'\n')
        print(f'Camera report saved: {self.output}/report.json', flush=True)
