# Replacement leader manual calibration

Prepared October 19, 2026 for LeRobot 0.6.1. Backups of the previous local
leader calibration and latest inspection are under ignored
calibration/backups/leader-before-replacement-20261019/.

The new leader elbow/gripper positions are outside stored ranges; do not reuse
the old leader calibration. Calibration does not repair the recurring voltage
fault. Stop on any read/write/voltage error and inspect the saved reports before
retrying. An interrupted calibration may have partially changed motor registers.

Reviewed command (only after approving the writes below):

```bash
sudo docker compose --env-file config/docker.env -f compose.yaml -f compose.calibrate-leader.yaml run --rm collector
```

Only the leader controller is mapped. The wrapper checks the exact installed
version, motor models, torque off and voltage, and saves current register
calibration to outputs/motor-inspection/ before asking CALIBRATE LEADER. It
calls the official pinned leader calibrate method directly, avoiding the normal
connect/configure path and its acceleration/return-delay/feedback writes.

Approved effects of that method: disable leader torque (including Lock=0), set
position operating mode, reset/recompute homing offsets and position ranges,
and write the new calibration JSON. No follower, motor IDs, motor baud registers,
firmware, PID or acceleration changes. Torque is never enabled by the wrapper.
The host Docker daemon requires sudo; enter the password locally.

Support the leader so torque loss is harmless, clear its reachable workspace,
and keep fingers clear of jaws/pinch points. At the midpoint prompt, manually
place each joint approximately halfway through its comfortable travel, then
press Enter. During range recording, gently move the shoulder pan, shoulder
lift, elbow, wrist flex and gripper one at a time through their comfortable
full travel, without forcing resistance. Follow the wrist-roll exclusion printed
by LeRobot; it uses the upstream 0..4095 full-turn convention. Press Enter only
after all requested joints have been exercised.

Each run now saves to a fresh timestamped directory (old active file stays untouched):
calibration/teleoperators/so101_leader/replacement-<UTC timestamp>/cup_leader_replacement_20261019.json.
This permits a complete new calibration after the incomplete October 19 run
without overwriting its local file. The wrapper prints the exact new path.

The wrapper compares local data to motor readback and verifies torque remains
off. Review the saved result before activating this calibration or teleoperating.
Persistence across a later power cycle must be checked separately; a successful
immediate readback does not prove nonvolatile storage.

Primary version-matched sources:
- https://github.com/huggingface/lerobot/blob/v0.6.1/src/lerobot/teleoperators/so_leader/so_leader.py
- https://github.com/huggingface/lerobot/blob/v0.6.1/src/lerobot/scripts/lerobot_calibrate.py
