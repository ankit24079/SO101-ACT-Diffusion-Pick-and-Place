# One cube-to-cup test recording

Task: **Pick up the cube and place it in the cup.** This is a single diagnostic
episode, not the approved start of final collection. Original cup-task planning
is retained; decide the final training task after reviewing this trial.

Prepare the cube and cup within the follower's reachable area, with the fixed
workspace camera seeing both. Keep both arm mounts secure and wires clear.
The wrist camera stays fixed per the user instruction. Keep the follower motor
power cutoff accessible; Ctrl+C attempts torque off, but unexpected motion
requires immediate physical motor-power cutoff. The arm may settle when torque
turns off. Do not reach into the powered follower workspace.

From the project directory:

```bash
sudo docker compose --env-file config/docker.env \
  -f compose.yaml -f compose.teleop-check.yaml \
  -f compose.teleop-cameras.yaml -f compose.record-test.yaml run --rm collector
```

No rebuild. This first performs a three-frame synthetic dataset write, video
encode/decode, and official LeRobot reader check before opening motor ports.
A failure stops before torque. Then the existing calibration, model, mode,
voltage and position checks run. Relative-start mode captures a per-joint
offset after camera startup, so matching physical starting angles is not
required. The follower initially holds its own pose; leader changes then drive
follower changes, clipped to calibrated bounds and the existing slew limit.
Hold the leader still until recording starts. No calibration values change.
The offsets and starting poses are saved in recording_context.json inside the
dataset and in its sidecar. Actions remain the actual absolute normalized
follower targets, suitable for interpreting this recorded episode. At the prompt, type CLEAR TO MOVE
only with the workspace clear. Cameras initialize before follower torque.

Try one gentle pick-and-place. Press Enter to end the episode when finished. There is no recording time limit. Ctrl+C attempts to stop too. Existing target slew
limits remain at 5 normalized units per second, so move the leader slowly and
avoid getting far ahead of the follower. Do not force a blocked gripper.

The nominal episode rate is 10 FPS to match the validated control loop;
cameras deliver at requested 30 FPS, and the latest frames are sampled for
each robot timestep. This does not establish hardware synchronization.
Observations are follower positions in normalized -100..100 arm ranges and
0..100 gripper range. Actions are the clipped targets actually sent to the
follower, not unbounded leader requests. Additional elapsed and camera-delivery
timing features preserve actual timing for validation; standard LeRobot
`timestamp` is frame_index/10. This is an initial diagnostic rate; do not mix
it with a later dataset using a different agreed recording rate.

Camera frames are spooled as quality-95 JPEGs to disk during motion, with a
replayable frames.jsonl journal under outputs/test-recordings/<run>-frames/.
Only lightweight frame metadata remains in memory. LeRobot dataset writing and
video encoding occur after follower torque OFF is verified. Spool files are
retained for recovery; they are not a second successful demonstration.
A disk-space check stops capture below 2 GiB free to preserve space for saving.
Voltage, camera, position, and tracking-error stops remain active.
If torque-off verification fails, use the physical power cutoff and review
before retrying; encoding is skipped. No datasets are overwritten or uploaded.

Dataset: `datasets/cube-cup-test-<unique-id>/` on the host. Each run creates a
new local dataset with one episode. H.264 videos, joint data, sent actions,
timestamps, task, and metadata are written using LeRobot 0.6.1 APIs. Synthetic
samples stay separately under ignored `outputs/recording-smoke/`.

After encoding, the script checks episode/frame counts, state/action shapes,
nominal timestamps, actual sample spacing, repeated camera frames, camera ages,
video counts and dimensions, task text, and official reader decoding. Preview
frames and validation JSON are saved beside the dataset in
`datasets/cube-cup-test-<unique-id>-review/`. The episode sidecar under
`outputs/test-recordings/` records why the run ended and leaves task success
pending review. An interrupted/error episode is diagnostic data, not an
approved successful demonstration.

Review all saved images, actual FPS/gaps, and cube-in-box success before any
further recording. Timestamp checks alone do not prove sensor synchronization
or count every dropped frame. This script does not start the 50–60 episode run.

## All-motor voltage logging

Every powered control cycle reads voltage from all six motors on each arm
(including both grippers), checks configured limits, and flushes a partial-safe
JSONL record under outputs/task-voltage/<run>/. A summary reports min/max raw
values and any fault. Read faults retain arm/joint context and stop powered
control; no fault masking, voltage-limit changes, or automatic calibration writes
are added. Terminal voltage updates print about once a second. Readings are
sequential telemetry, not a high-speed transient measurement. Dataset context
links to this persistent log. Inspect actual achieved loop timing afterward.

Latest post-power-cycle calibration inspection differs from local gripper
calibration (2005–3541 on motor versus 1031–2496 locally). Preflight must refuse
powered operation until this is resolved with explicit calibration authorization.

## Existing follower torque at startup

Startup now names joints whose torque is already on. Read-only mode still
refuses without writes. Powered mode offers a separate RELEASE TORQUE prompt:
stop other robot programs, support/secure the arm for torque loss, and keep
fingers clear. Confirming writes Torque_Enable=0 only to affected follower
joints and verifies all six are off before continuing. The arm can sag. No
position or calibration writes occur during this reset. CLEAR TO MOVE remains
the separate confirmation for starting motion. Existing leader torque or
unexpected register values still block startup.

## Gripper mapping correction

Relative startup offsets now apply only to arm joints. Gripper targets use
calibrated absolute openness (0 closed, 100 open) independent of starting
opening. Goal seeding and slew limits still prevent an instantaneous startup
target jump. Existing generic tracking error stops can also trigger when an
object prevents full closure; they are not proof of electrical faults. Do not
raise thresholds or command additional squeezing without a reviewed
contact-control/current-limit approach.

## Contact hold update (October 19, 2026)

See [gripper-contact.md](gripper-contact.md). The gripper now latches a position
hold on suspected stationary closing contact and ignores further squeeze
requests until the leader opens above the held opening. This is not constant
torque control, and motor overload/voltage faults remain fatal. An object may
slip when excess positional error is backed off. Bench-test a supported object
before lifting or recording another full task.
