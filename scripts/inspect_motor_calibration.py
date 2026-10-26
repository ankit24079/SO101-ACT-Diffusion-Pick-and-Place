"""Read-only motor-register inspection for LeRobot 0.6.1; no robot.connect()."""
import dataclasses
import importlib.metadata
import json
from datetime import datetime, timezone
from pathlib import Path

from lerobot.motors import Motor, MotorNormMode
from lerobot.motors.feetech import FeetechMotorsBus


class ReadOnlyBus(FeetechMotorsBus):
    def write(self, *args, **kwargs):
        raise RuntimeError("Motor register writes forbidden during inspection")

    def _write(self, *args, **kwargs):
        raise RuntimeError("Motor register writes forbidden during inspection")

    def sync_write(self, *args, **kwargs):
        raise RuntimeError("Motor register writes forbidden during inspection")


names = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")
if importlib.metadata.version("lerobot") != "0.6.1":
    raise RuntimeError("Review inspection code for this LeRobot version first")
report = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "arms": {}}
try:
    for role in ("leader", "follower"):
        print(f"Inspecting {role} arm; read-only register requests...", flush=True)
        bus = ReadOnlyBus(
            port=f"/dev/so101-{role}",
            motors={name: Motor(i, "sts3215", MotorNormMode.RANGE_0_100 if name == "gripper" else MotorNormMode.RANGE_M100_100) for i, name in enumerate(names, 1)},
        )
        result = report["arms"][role] = {"status": "started", "expected_ids_only": True}
        try:
            bus.connect(handshake=False)
            result["host_serial_baudrate"] = bus.get_baudrate()
            models = {}
            for name in names:
                model = bus.ping(name, raise_on_error=True)
                models[name] = model
                if model != bus.model_number_table["sts3215"]:
                    raise RuntimeError(f"Unexpected model for {role}/{name}: {model}; stop")
            result["model_numbers"] = models
            result["torque_enable"] = {name: bus.read("Torque_Enable", name, normalize=False) for name in names}
            result["voltage_registers_raw"] = {
                name: {
                    register: bus.read(register, name, normalize=False)
                    for register in ("Present_Voltage", "Min_Voltage_Limit", "Max_Voltage_Limit")
                }
                for name in names
            }
            result["phase"] = {name: bus.read("Phase", name, normalize=False) for name in names}
            result["operating_mode"] = {name: bus.read("Operating_Mode", name, normalize=False) for name in names}
            result["stored_calibration_registers"] = {name: dataclasses.asdict(value) for name, value in bus.read_calibration().items()}
            result["present_position_raw"] = {name: bus.read("Present_Position", name, normalize=False) for name in names}
            result["status"] = "read_complete"
        except Exception as error:
            result["status"] = "error"
            result["error"] = str(error)
            raise
        finally:
            # Default disconnect disables torque, which would be a motor write.
            # Close the serial handle directly, including after partial connection.
            bus.port_handler.closePort()
finally:
    directory = Path("/workspace/outputs/motor-inspection")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".json")
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2), flush=True)
    print(f"Saved inspection report: {path}", flush=True)
