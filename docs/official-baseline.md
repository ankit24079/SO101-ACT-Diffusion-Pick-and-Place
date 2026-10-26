# Official LeRobot 0.6.1 baseline

The baseline uses the installed SO101Leader and SO101Follower classes, their
unaltered connect/configure methods, default processors, and the actual
lerobot_teleoperate.teleop_loop. The wrapper adds a read-only register backup,
calibration verification, an operator start prompt, Enter-to-stop, and torque-off
cleanup even if initialization fails. It does not implement its own control law.
The custom controller and existing datasets are preserved separately.

## Voltage limits

Neither the reviewed official configure routines nor the custom controller
writes Min_Voltage_Limit or Max_Voltage_Limit. Both use the existing motor
registers; there is no universal LeRobot SO-101 voltage setting to copy.
The latest stored-limit observations are raw register values:

| Motors | Minimum | Maximum |
| --- | --- | --- |
| Leader shoulder lift | 40 | 80 |
| Other leader joints, including gripper | 40 | 120 |
| All follower joints | 40 | 140 |

The motor variant and actual supply determine whether these limits are
appropriate. Do not widen them to hide a fault. The official SDK grouped read
path discards motor status-error bytes; continuing with that path does not prove
an underlying voltage flag has disappeared. The launcher's individual-read
preflight refuses reported faults before movement.

## Differences applied by the native baseline

The earlier audit found Acceleration=0 on all motors, while upstream configures
Acceleration=254, Maximum_Acceleration=254 and Return_Delay_Time=0. Current
follower PID=16/0/32 and gripper protection values 500/250/25 already match.
Upstream also sets position mode, clears Phase bit 0x10 when necessary and uses
the SDK torque/Lock helpers. These official initialization writes will occur
only after the movement prompt; follower configuration enables torque.

Default upstream behavior uses degrees for arm joints, gripper openness 0..100,
absolute leader commands, grouped reads with two extra attempts on communication
failure, grouped goal writes and requested control rate 60 Hz. Its native camera
path reads the latest frame with a default 500 ms maximum age. Our selected
camera resolution/format remain 640x480, MJPG, 30 FPS on both physical cameras.
The configured motor baud register, motor IDs, firmware and existing calibration
are not rewritten. The calibration mount is read-only.

The native baseline has no custom shoulder cap of 60 normalized units, relative
startup offsets, 5-unit tracking abort, 5-unit/second slew, custom raw-position
allowance or gripper contact-hold policy. A value from the old normalized arm
coordinate system must not be treated as the same numeric angle in degrees.
The first baseline is teleoperation with both cameras, not a dataset recording.

## Run

Read-only backup, configuration review and calibration verification:

```bash
sudo docker compose --env-file config/docker.env -f compose.yaml -f compose.official-teleop.yaml run --rm collector
```

Apply official initialization and use the actual official control loop:

```bash
sudo docker compose --env-file config/docker.env -f compose.yaml -f compose.official-teleop.yaml run --rm collector python /opt/official_teleop.py --run
```

Align the physical arm poses with torque off, clear the workspace, support the
arms and keep the follower power disconnect accessible before typing
`CLEAR TO MOVE`. Absolute commands can move the follower immediately. Enter or
Ctrl+C ends the session without a timer. No motor setup or calibration command
is part of this baseline. Reports/backups are under outputs/official-audit/.

## Recording with the smooth official controller

```bash
sudo docker compose --env-file config/docker.env -f compose.yaml -f compose.official-teleop.yaml run --rm collector python /opt/official_teleop.py --record
```

This first runs a three-frame synthetic dataset write/read/video check at 30 FPS
without hardware, then the normal audit and movement confirmation. Wait for
`RECORDING STARTED`, perform one cube-to-cup task, move clear and press Enter.
There is no episode timer. Wait for encoding and validation to finish.

The installed official loop and movement behavior remain unchanged. A passive
robot proxy records observations and the actual return value of send_action.
Control requests 60 Hz; recording samples up to 30 FPS. JPEG disk writes run on
a separate bounded worker queue. A full queue or worker failure ends the run
through the existing torque-off cleanup rather than blocking motor commands on
disk. Encoding starts after verified follower torque off. Actual sample times,
native camera timestamps, repeated frames and control timing are retained for
review. Camera timestamp/image pairs that cannot be matched are skipped and
counted. No additional motor reads are made by the recorder.

Datasets use the separate prefix `cube-cup-official-`, with arm joint positions
in degrees and gripper openness 0..100. Do not combine them directly with the
earlier custom normalized-arm datasets. Continuous motor voltage telemetry is
not added to the native loop; preflight voltage registers are in the session's
audit. Files remain local and training approval awaits visual/task review.

## Stop-boundary correction and offline recovery

The episode ending with `Port is in use!` preserved 1,381 frames but did not
verify follower torque off, so the original writer skipped final encoding.
The SDK 1.0.0 source reproduced a software busy latch after KeyboardInterrupt
inside txPacket (proof: outputs/official-source-review-20261019/interrupt_busy_reproduction.json).
This matches the shutdown symptoms; the historical report cannot prove the
precise interruption point. Support and disconnect follower power when shutdown
cannot verify torque off.

Enter now sets a stop request rather than sending SIGINT into serial I/O.
The native loop exits before its next observation read. SIGINT/SIGTERM likewise
request a boundary stop after the current synchronous call returns. Cleanup
also clears a stale SDK busy flag only after the sole motor-I/O thread has
unwound the control loop, before attempting each joint's torque-off and readback.
No native motor configuration or control law was changed. Regression checks
cover boundary stopping and busy-latch cleanup.

Recover the preserved episode with no camera/serial devices mapped:

```bash
sudo docker compose --env-file config/docker.env -f compose.yaml -f compose.recover-episode.yaml run --rm collector python /opt/recover_official_episode.py --episode cube-cup-official-1792438465435194188
```

The recovery checks journal count, state/action values and both image files per
frame, then calls the official dataset writer and reader validation. It refuses
to overwrite an existing dataset and preserves the original raw spool and
original torque-off-verification failure in metadata. Offline recovery does not
establish a new hardware torque state or approve the episode for training.

Sources:
- https://github.com/huggingface/lerobot/blob/v0.6.1/src/lerobot/robots/so_follower/so_follower.py
- https://github.com/huggingface/lerobot/blob/v0.6.1/src/lerobot/robots/so_follower/config_so_follower.py
- https://github.com/huggingface/lerobot/blob/v0.6.1/src/lerobot/teleoperators/so_leader/so_leader.py
- https://github.com/huggingface/lerobot/blob/v0.6.1/src/lerobot/motors/feetech/feetech.py
- https://github.com/huggingface/lerobot/blob/v0.6.1/src/lerobot/scripts/lerobot_teleoperate.py
- https://github.com/huggingface/lerobot/blob/v0.6.1/src/lerobot/cameras/opencv/camera_opencv.py
