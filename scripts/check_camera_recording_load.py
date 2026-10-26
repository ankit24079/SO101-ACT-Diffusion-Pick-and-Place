"""Camera-only 60-second JPEG recording-load test. No serial or motor access."""
import json
import time
from pathlib import Path

from PIL import Image
from teleop_cameras import CameraMonitor


def main():
    camera = CameraMonitor()
    rows = []
    outcome = 'interrupted'
    spool = camera.output / 'recording-load'
    spool.mkdir()
    try:
        camera.start()
        start = time.monotonic()
        print('Camera-only recording-load check: 60 seconds; no arms accessed.', flush=True)
        while time.monotonic()-start < 60:
            tick = time.monotonic()
            images, times = camera.snapshot()
            now = time.monotonic()
            ages = {name: (now-t)*1000 for name, t in zip(('workspace', 'wrist'), times)}
            row = {'seconds': now-start, 'camera_age_ms': ages}
            rows.append(row)
            if any(age > 200 for age in ages.values()):
                raise RuntimeError(f'Stale camera frame: {ages} ms')
            for name, frame in images.items():
                Image.fromarray(frame).save(spool/f'{name}-{len(rows):06d}.jpg', quality=95)
            row['jpeg_write_ms'] = (time.monotonic()-now)*1000
            with (spool/'samples.jsonl').open('a') as stream:
                stream.write(json.dumps(row)+'\n')
            time.sleep(max(0, .1-(time.monotonic()-tick)))
        outcome = 'passed'
    except BaseException as error:
        outcome = f'{type(error).__name__}: {error}'
        raise
    finally:
        camera.close()
        report = {'outcome': outcome, 'samples': len(rows), 'motor_access': False,
                  'training_dataset': False,
                  'max_camera_age_ms': {name: max((r['camera_age_ms'][name] for r in rows), default=None)
                                        for name in ('workspace', 'wrist')},
                  'max_jpeg_write_ms': max((r.get('jpeg_write_ms', 0) for r in rows), default=None)}
        (camera.output/'recording-load-report.json').write_text(json.dumps(report, indent=2)+'\n')
        print(json.dumps(report, indent=2), flush=True)
        print(f'Recording-load report: {camera.output}/recording-load-report.json', flush=True)


if __name__ == '__main__':
    main()
