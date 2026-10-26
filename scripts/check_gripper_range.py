"""Read-only follower gripper monitor. User moves the gripper gently by hand."""
import importlib.metadata
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from lerobot.motors import Motor, MotorNormMode
from lerobot.motors.feetech import FeetechMotorsBus


class ReadOnlyBus(FeetechMotorsBus):
    def write(self, *args, **kwargs):
        raise RuntimeError("Motor writes forbidden")

    def _write(self, *args, **kwargs):
        raise RuntimeError("Motor writes forbidden")

    def sync_write(self, *args, **kwargs):
        raise RuntimeError("Motor writes forbidden")


def check_torque(bus):
    states = {name: bus.read("Torque_Enable", name, normalize=False) for name in bus.motors}
    if any(value != 0 for value in states.values()):
        raise RuntimeError(f"STOP: torque is enabled or unknown: {states}. No settings changed.")


if __name__ == "__main__":
    if importlib.metadata.version("lerobot") != "0.6.1":
        raise RuntimeError("Expected LeRobot 0.6.1")
    names = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")
    bus = ReadOnlyBus('/dev/so101-follower', {
        name: Motor(i, 'sts3215', MotorNormMode.RANGE_0_100)
        for i, name in enumerate(names, 1)
    })
    report = {"started_utc": datetime.now(timezone.utc).isoformat(), "stages": {}, "status": "started"}
    try:
        bus.connect(handshake=False)
        for name in names:
            if bus.ping(name, raise_on_error=True) != bus.model_number_table['sts3215']:
                raise RuntimeError(f"Unexpected model: {name}")
        check_torque(bus)
        report['stored_gripper_calibration'] = vars(bus.read_calibration()['gripper'])
        print('All follower motors report torque OFF. Keep the arm supported; move only the gripper.', flush=True)
        print('Keep fingers out of the jaws. Do not force resistance or mechanical stops.', flush=True)
        for stage, instruction in (
            ('closed_before', 'Leave the gripper gently closed; press ENTER to sample.'),
            ('manual_sweep', 'Press ENTER, then gently open and close the gripper by hand for 15 seconds.'),
            ('closed_after', 'Leave it gently closed again; press ENTER to sample.'),
        ):
            input(instruction + ' Ctrl+C cancels. ')
            duration = 15 if stage == 'manual_sweep' else 2
            samples = []
            report['stages'][stage] = samples
            start = time.monotonic()
            while time.monotonic()-start < duration:
                check_torque(bus)
                pos = bus.read('Present_Position', 'gripper', normalize=False)
                samples.append({'seconds': round(time.monotonic()-start, 3), 'position': pos})
                print(f'{stage}: raw position={pos}', flush=True)
                time.sleep(.1)
            print(f'{stage}: min={min(x["position"] for x in samples)}, max={max(x["position"] for x in samples)}', flush=True)
        report['status'] = 'complete'
    except BaseException as error:
        report['status'] = 'interrupted' if isinstance(error, KeyboardInterrupt) else 'error'
        report['error'] = str(error)
        raise
    finally:
        bus.port_handler.closePort()
        directory = Path('/workspace/outputs/motor-inspection')
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / ('gripper-range-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json')
        path.write_text(json.dumps(report, indent=2)+'\n')
        print(f'Report saved: {path}. No motor settings or calibration were written.', flush=True)
