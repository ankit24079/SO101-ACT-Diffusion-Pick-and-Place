# Reproducibility record

Stage 3 must fill in the environment record after actual verification. The proposed versions and remaining verification steps are in `docker.md`.
No image has been built.

| Field | Status |
| --- | --- |
| LeRobot release and source commit | 0.6.1 proposed from PyPI; source commit not recorded |
| Official documentation version / URL | Pending version match |
| Container base image and digest, if used | python:3.12-slim-bookworm proposed; digest pending build |
| Python and dependency versions / lock record | Pending |
| Feetech support and video encoding dependencies | Pending verification |
| Build and run commands | Pending review and approval |
| Required device mappings and permissions | Pending identification |
| Host dataset and output mounts | Pending |

Before collecting demonstrations, record the verified environment versions,
capture settings, camera names, robot IDs, task description, episode/reset
timing, initial layout, test episode validation, and dataset format version.
Keep serial mappings and calibration in ignored local storage. Preserve existing
calibration before any approved replacement; Git exclusions alone do not back
it up. Store a sanitized run record alongside the dataset for later MSI use.

Keep datasets, videos, checkpoints, environments, caches, calibration, logs, and
credentials outside version control. Use the intended ignored directories and
inspect `git status` and staged diffs before committing. A `.gitignore` cannot
prevent deliberate force-adds or recognize every possible secret filename.

## Host Docker verification — October 15, 2026

- Docker Engine/CLI: 29.9.1 (package 5:29.9.1-1~ubuntu.22.04~jammy).
- Compose: v5.6.0 (package 5.6.0-1~ubuntu.22.04~jammy).
- Buildx: 0.38.0-1~ubuntu.22.04~jammy.
- containerd.io: 2.4.2-2~ubuntu.22.04~jammy.
- Docker and containerd services: active.
- Checked packages, including curl and ca-certificates: fully installed.
- Approximately 27 GiB disk space remains available.
- Current account cannot access the Docker socket without sudo. No group
  membership changes were made. Server API verification remains pending
  authenticated sudo access; no image has been built.

## Successful image build — October 15, 2026

User-provided output from `sudo docker image inspect` confirms:

- Image tag: `so101-collector:lerobot-0.6.1`.
- Image ID: `sha256:f34f1ebc697dce3abbba99fbc1dc5875aa745caa69cbfb2c02348c2c92d754a1`.
- Created: `2026-10-15T16:52:50.250544816-05:00`.

Successful image export implies the Dockerfile's pip check, software imports,
CPU-only assertion, CLI presence checks, and synthetic H.264 encode/TorchCodec
decode test completed. This evidence was supplied by the user; direct daemon
inspection by the assistant remains blocked by sudo authentication. Non-root
container runtime, persistent mounts, camera access, and robot access have not
yet been verified. Package manifests remain inside `/opt/environment/` in the
image and have not yet been copied to the host.

## Runtime software check passed — October 15, 2026

User-provided Compose output confirms successful software imports and CPU video
round trip under the configured runtime UID after the Compose username/cache fix.
Versions reported: LeRobot 0.6.1; torch 2.10.0+cpu; torchvision 0.25.0+cpu;
TorchCodec 0.10.0; av 15.1.0; opencv-python-headless 4.13.0.92;
feetech-servo-sdk 1.0.0. No hardware was mapped or accessed.
Host bind-mount write/persistence verification and manifest export remain pending.

## Host persistence verified — October 15, 2026

Direct host inspection after the user ran the temporary export container found
`outputs/environment/pip-freeze.txt`, `debian-packages.txt`, and
`python-version.txt`, owned by the host user and readable after container removal.
Python is 3.12.15; exported key package versions match the runtime report above.
Git ignores the exported records. This verifies the outputs bind mount only;
recorded dataset persistence and other mount write paths still require their
respective later checks. Hardware access is not yet verified. Base image digest
and image archival remain outstanding reproducibility improvements.

## Calibration search and camera-only preparation — October 15, 2026

No robot calibration JSON found in standard host cache paths or broader home
search (credential directories, package trees, and datasets excluded). No custom
HF/LeRobot calibration path environment variable was set in this session. This
does not establish whether calibration exists on another computer or on motors.
No serial connection, calibration, or motor setting changes were performed.

`compose.cameras.yaml` and `scripts/check_cameras.py` prepare a two-camera
LeRobot API test without serial mappings. Runtime execution awaits local sudo.

## Docker camera test passed — October 15, 2026

Direct inspection of the persisted report confirms two simultaneous LeRobot
OpenCV camera streams at 640×480 RGB, MJPG capture, 150 frames each.
Workspace delivery: 29.97 FPS, maximum interval 40.87 ms. Wrist delivery:
30.14 FPS, maximum interval 40.35 ms. Neither stream had delivery intervals
over 50 ms. This is a short delivery test, not proof of sensor synchronization
or a complete dropped-frame analysis. Previews and report persist under ignored
`outputs/camera-check-docker/`. No serial devices were mapped or opened.
User reports the arms may have been calibrated on another laptop; obtain and
inspect those files before deciding whether calibration is necessary.

## Stored motor calibration inspection — October 15, 2026

Direct host report inspection confirms both arms responded at the SDK's
1,000,000-baud host setting for expected IDs 1–6, with STS3215 model number
777 and Torque_Enable=0 on all twelve motors. Stored offsets and ranges are
present. The follower gripper position 1039 is outside its stored range
2005–3541; other reported positions are inside their ranges. Existing
calibration is therefore not yet approved for reuse. No calibration files
were activated and no motor registers were written. The inspection script
now also reads Phase and Operating_Mode to investigate feedback semantics
without invoking configure_motors(), which would write Phase and other values.

## Manual follower gripper check — October 15, 2026

Direct inspection of `gripper-range-20261015T225529753992Z.json` shows status
complete, no errors: closed-before 1038 (19 samples), manual sweep 1027–1568
(143 samples), closed-after 1031 (20 samples). The script checked all follower
torque-enable registers were zero before every sample; no motor writes were
issued. The observed interval is entirely below the stored gripper range
2005–3541 (homing offset 860). The sweep does not establish the full physical
range or safe new limits; user confirmation of the actual opening is pending.
Existing follower gripper calibration remains unapproved for teleoperation.

## Repeated full-opening follower gripper check — October 15, 2026

Latest report `gripper-range-20261015T225843950292Z.json` completed without
errors: closed-before 1031, sweep 1031–2496 (142 samples), closed-after 1035.
This supersedes the earlier incomplete opening observation of 1568. The stored
range remains 2005–3541 with homing offset 860. Full physical opening is based
on the user's report; the read samples alone do not identify mechanical stops.
The closed endpoint remains outside the stored range. No calibration or torque
settings were changed; reuse and powered teleoperation remain unapproved.

## Approved follower gripper range correction — October 15, 2026

User explicitly requested setting the measured range and executed the reviewed
Compose command. Direct comparison of persisted before/after records for
20261015T230024730335Z confirms exactly two calibration changes: follower
gripper range_min 2005→1031 and range_max 3541→2496. Homing offset remains
860; all other follower calibration fields are unchanged. Readback verified
and all follower Torque_Enable registers are zero. Backup and readback remain
in ignored outputs/motor-inspection. This is not a powered validation of the
new range; teleoperation and torque enablement remain pending approval.

## Calibration recovery and teleoperation preparation — October 15, 2026

Recovered ignored calibration/teleoperators/so101_leader/cup_leader.json from
20261015T221030807968Z.json and calibration/robots/so101_follower/cup_follower.json
from verified after-gripper-range-20261015T230024730335Z.json. Existing files
are checked for equality rather than overwritten. Local IDs set accordingly.
Prepared bus-level read-only preflight and separate guarded 20-second motion
mode; see docs/teleoperation-check.md. Python syntax and Compose validation
passed. Runtime preflight and powered test have not run. No new motor writes
were issued during this preparation.

## Voltage inspection — October 15, 2026

Direct report inspection of 20261015T231321975083Z.json: leader voltage
registers 49 on all motors, configured limits 40–120 (shoulder_lift 40–80).
Follower values 118–119 except gripper 112, limits 40–140 on all motors.
All values within configured limits, no read errors, all torque registers zero.
These no-load observations do not prove supply rating or stability under load.
The guarded powered test now rechecks voltage before enabling torque and
monitors follower voltage during motion, aborting on register faults or
out-of-limit readings. No motor settings changed in this preparation.

## Initial powered teleoperation result — October 15, 2026

User provided normal terminal return from the 20-second guarded test after
CLEAR TO MOVE and confirmed follower tracking. No exception was reported.
That earlier version did not print completion or verify final torque readback;
the next version adds those diagnostics.

Prepared compose.teleop-cameras.yaml to run the same guarded motion test with
two LeRobot camera streams and persisted half-second JPEG previews plus timing
reports under outputs/teleop-cameras/<run>/. Camera capture initializes before
torque; stream failures/staleness abort the control loop. No camera/teleoperation
run or dataset recording was started during preparation. Syntax and merged
Compose checks passed (exactly two serial devices and two cameras).

## Powered teleoperation with cameras passed — October 15, 2026

User terminal output confirms the 20-second loop completed and follower torque
OFF was verified. Direct inspection of outputs/teleop-cameras/1792106329031171909/
report.json shows no camera errors: workspace 605 frames, 29.996 FPS, max interval
40.86 ms; wrist 608 frames, 30.138 FPS, max interval 40.39 ms. Both had zero
delivery intervals over 50 ms. Sensor synchronization is not established by this.
Contact sheets were generated and reviewed: workspace camera sees the cup and
moving gripper; wrist previews show gripper tips and surroundings but do not
establish visibility of the cup during an actual grasp. Fixed wrist placement
will be retained per user instruction. Task-view adequacy requires a short
pick-and-place test episode. No LeRobot dataset or final collection has started.

## One cube-to-box recording prepared — October 15, 2026

User authorized one test episode attempting to grab a cube and place it in a
box. Prepared compose.record-test.yaml and scripts/test_episode.py, using
LeRobot 0.6.1 create/add_frame/save_episode/finalize and CPU H.264 encoding.
Nominal robot/dataset rate is 10 FPS, camera capture 30 FPS; actual timing and
camera delivery times are extra dataset features. One episode only, up to 60
seconds, Enter to finish; no upload, final collection, or training approval.
The synthetic write/read/video check executes before any motor access.

Syntax and merged Compose checks passed. A mocked preflight test confirmed no
motor writes in default mode; an injected control-loop exception confirmed
follower torque disable and port cleanup while the leader received no writes.
These are software tests, not a new hardware run. Local sudo authentication
blocked execution by the assistant. Actual dataset API round-trip and episode
recording remain pending user execution and subsequent visual/timing review.

## Operator-ended recording update — October 15, 2026

User requested no recording duration limit, Enter to finish. Recording mode now
has no timer; the separate non-recording teleop check keeps its 20-second limit.
Voltage, tracking, camera, position, torque cleanup, and disk-space checks remain
active. Frames now spool to quality-95 JPEGs and a replayable JSONL journal on
host outputs storage rather than retaining full RGB frames in RAM.

Attached run output shows the prior episode stopped for excessive elbow_flex
tracking error after 324 frames (~32.39 s), not the 60-second limit. The prior
partial dataset remains at datasets/cube-box-test-1792106886148603337 and is
not a confirmed task success. The tracking-error diagnostic now includes target,
observed position, and difference; error reasons are written to episode sidecars.

## Relative-start teleoperation prepared — October 15, 2026

Latest attached run stopped before torque: wrist_flex difference changed from
-9.56 to -16.73 during camera startup. User requested alignment in code. The
recording overlay now explicitly selects --relative-start: fixed per-joint
offset = follower_start - leader_start, captured after camera warmup and
preflight checks. Follower goals seed current positions; subsequent desired
targets are leader readings plus offsets, bounded to normalized joint ranges
and slew-limited as before. This avoids a powered startup matching maneuver.
Calibration, voltage/position checks, tracking stop, and torque cleanup remain.
Absolute mode retains the 10-unit starting alignment restriction. Per-episode
offsets/start poses are persisted with the local dataset and sidecar.

Tests passed for neutral-pose preservation, transferred leader deltas, target
bounds, Python syntax, and merged Compose entry point. No powered execution
of this new mode has occurred; actual task success remains pending.

## Relative-start run interrupted by leader voltage fault — October 15, 2026

Attached terminal output and saved sidecar identify leader/gripper (ID 6),
Present_Position read, Input voltage error. The relative-start mapping passed
startup and powered operation began. Follower torque OFF was verified after
the exception. Partial local dataset cube-box-test-1792107499948908944 has
24 frames (~2.312 s), official-reader validation passed, but it is marked
unsuccessful/interrupted and not approved for training. No retry or motor
configuration change was performed. Investigate the leader gripper supply and
connections before another powered test; the no-load voltage check did not
rule out this recurring fault during operation.

## Post-power-cycle inspection — October 15, 2026

Direct report 20261015T234629975736Z.json shows all twelve motors torque off
and voltage reads within configured limits without errors. Follower gripper
range is again 2005–3541, homing offset 860; present position is 1033. The local
calibration file still contains the approved 1031–2496 range. The correction
read back successfully earlier but did not survive this power cycle (cause not
established). Do not silently rewrite it, recalibrate, or bypass equality checks.
Powered recording remains blocked pending investigation of persistence and the
recurring voltage fault. No motor changes were issued during this review.

## Follower-only gripper retest prepared — October 15, 2026

User requested reusing the same measured values and testing gripper performance.
Prepared the existing approved range restore (1031–2496, homing offset stays
860) and a separate follower-only powered gripper test. The test verifies
calibration equality, models, torque off, mode and voltage; seeds current goal;
powers only follower ID 6; slowly targets 25% then 10% opening with Enter
inspection pauses. It checks voltage/position during motion and pauses, and
attempts gripper torque off on exit. Other joints, leader and cameras are not
commanded. No recordings start. Syntax, write-scope and one-device Compose
checks passed. Sudo authentication blocked the restore attempt; no hardware
writes or powered test were performed by the assistant. This does not resolve
calibration persistence or the leader's recurring input-voltage fault.

## Torque-off manual leader-gripper voltage check — October 15, 2026

Direct inspection of outputs/gripper-voltage/1792108269949805562.json: user
finished normally, 200 samples over 22.361 s, no read errors. Leader gripper
voltage register 46–49 with configured limits 40–120; position 1842–3078.
Follower gripper voltage register steady at 118 (limits 40–140), position steady
at 1033. Both arms' torque-off registers were checked during sampling. This
manual torque-off diagnostic did not reproduce the recurring voltage fault;
it does not establish supply stability in powered teleoperation. No calibration,
voltage-limit, or motor settings changed and no powered grasp was tested.

## Torque-off manual follower-gripper voltage check — October 15, 2026

Direct report outputs/gripper-voltage/1792108397594003899.json: manual_arm
follower, operator_finished, no errors; 205 samples over 22.955 seconds.
Follower voltage registers 114–118 within limits 40–140; follower position
1033–2494. Leader voltage 48–49 within limits 40–120, position steady 1842.
All torque-off checks passed during sampling. Repeated manual travel agrees
closely with the earlier 1031–2496 measured follower gripper range, but does
not test powered grasping or resolve the power-cycle calibration mismatch.
No motor settings were changed.

## Cube-to-cup all-motor voltage test prepared — October 15, 2026

User requested grasp/place into a cup while checking every follower motor and
gripper voltage. Prepared all-six-motor voltage logging on BOTH arms each
control cycle, with incremental JSONL and min/max/fault summary, terminal updates,
and a dataset-context link. Task text and new dataset prefix now say cube-to-cup;
prior datasets are unchanged. No recording timer; Enter ends the run.

Tests confirmed twelve logged values, propagation of a simulated follower
gripper voltage fault, and preservation of partial reads and summary. Python
syntax and Compose checks passed. No powered execution or calibration changes
occurred. Known power-cycle calibration mismatch still blocks startup; do not
silently restore values or bypass checks.

## Follower wrist-roll packet error before torque — October 15, 2026

Attached run stopped while seeding follower Goal_Position for ID 5 (wrist_roll),
raw target 2145: Incorrect status packet. No torque-enable commands were issued;
no episode recorded. Earlier goal seeds may have been accepted while torque
was off; no assumption is made about the failed write's acceptance. The two
all-motor voltage samples were within configured limits (leader 48–49, follower
118–120). No voltage error was reported during this attempt. This is a serial
communication/status-packet fault, not the previous motor input-voltage error.
No automatic retry, torque enable, or motor configuration change was performed.

## Existing follower torque startup handling — October 15, 2026

Latest user run stopped at preflight because at least one follower torque
register was nonzero; no new torque-enable commands were issued by that run.
Cause and affected joints were not reported by the earlier error. Prepared
per-joint reporting and an explicit RELEASE TORQUE option in powered mode only.
It writes zero only to enabled follower Torque_Enable registers after a
supported-arm confirmation, records before/after values, and verifies all are
off before continuing. Read-only mode and declined confirmation remain free of
motor writes. Mock tests passed for those paths and confirmed single-joint
release/readback. No live torque release or powered run was started here.

## Gripper contact and startup mapping review — October 15, 2026

Latest run cube-cup-test-1792110073065890481 ended on follower gripper tracking
error: requested 11.19, observed 16.45, difference 5.26 points against limit 5.
User confirms cube was between jaws. This supports contact as the explanation
for this stop, not a reported voltage fault. User also reports inconsistent
gripper behavior with starting opening. Fixed relative-start mapping so only
arm joints get offsets; gripper always maps calibrated leader 0..100 openness
to follower 0..100. Initial goal seeding and slew limits remain, so the change
is not an instantaneous jump. No motor/calibration writes were executed.
Tests passed for startup-independent gripper mapping, endpoints, retained arm
offsets and absolute mode. Generic gripper tracking stop remains active pending
a reviewed contact-control design; no force/current tuning or powered retest
was performed. Earlier leader voltage faults remain unresolved.

## Empty-gripper opening/closing diagnosis prepared — October 15, 2026

Latest empty-gripper run 1792110649384280626 completed the 20-second loop
without a reported fault; user observed opening but not closure. Existing logs
contain voltage only, so a command/position cause cannot yet be determined.
Added --until-enter for non-recording tests and per-cycle control.jsonl with
mapped leader target, sent follower target, and measured follower positions.
Terminal prints requested/sent/observed gripper opening about once per second.
A full 0→100→0 target sweep requires at least ~40 s at the existing 5 pp/s
slew limit. No calibration, motor parameters, slew limits, or fault stops were
changed. Tests passed for control logging and the Enter-ended loop path; no
live powered run was performed.

## Contact-aware position hold implemented — October 19, 2026

User requested stopping additional squeeze after gripping and maintaining grip
until release. Added pure GripperContactHold policy and Compose mount. Detects
stationary closure lag >=1.5 pp for 0.3 s; holds max(previous command, measured
opening minus 1 pp), bounded to 0..100, under the existing slew limit. Further
closing requests are ignored; opening >=held target+2 pp releases the latch.
No torque/current-control mode or motor protection changes. Actual torque is
not constant, and voltage/overload/communication errors plus the original
tracking guards still abort. Control logs and dataset context record the policy.

Eight unit tests passed. Historical overloaded follower-gripper trace replay
detected contact at 60.562 s and proposed backing off from command 12.35 to
15.86 at measured 16.86. Syntax and both teleop/record Compose mounts validated.
No hardware access, calibration writes, torque changes, or powered test occurred
during this implementation. Hardware suitability, grip stability and release
require a supported-object bench test before lifting.

## Replacement leader calibration prepared — October 19, 2026

User requested proceeding after review of the 17:42:41 UTC inspection.
Backed up the old active local leader calibration and inspection under ignored
calibration/backups/leader-before-replacement-20261019/. Prepared a leader-only
manual calibration wrapper calling the official pinned-version calibrate method
without normal device.configure side effects. Live calibration backup is written
before the CALIBRATE LEADER prompt. New output has its own identity/directory;
old active calibration is untouched. Effects and manual movement instructions
are documented in replacement-leader-calibration.md. Python syntax and Compose
leader-only mapping checks passed. No calibration command or hardware writes
were executed during preparation.

## Replacement leader calibration completed — October 19, 2026

Direct comparison of replacement-20261019/cup_leader_replacement_20261019.json
and leader-after-calibration-1792432014661632533.json confirms exact motor/local
match and torque OFF on all leader motors. Nonzero spans for all joints, elbow
325–2093 and gripper 2043–3281. This does not prove manually exercised ranges
are mechanically complete, nor does it repair prior electrical faults.
Selected this new file using ignored LEADER_CALIBRATION_RELATIVE and updated
local leader ID. Teleoperation Compose passes the selected path; old calibration
was preserved. No additional motor writes were issued. Next read-only preflight
must check positions and follower calibration before any powered test.

## Leader controller replacement detected — October 19, 2026

User replaced the leader controller. Host enumeration shows the prior leader
USB serial absent and a new QinHeng controller present; original follower
controller is unchanged. Updated only ignored local LEADER_PORT settings to
the new persistent device path. Calibration selection remains unchanged, no
IDs/baud registers/firmware/calibration/motor settings modified. This change
is an isolation test; the previous voltage fault is not assumed resolved.
Next step is a read-only motor/voltage/torque inspection before any movement.

## Official LeRobot software audit — October 19, 2026

User requested checking actual LeRobot logic/values rather than assuming a
hardware cause. Compared tag v0.6.1 and PyPI feetech-servo-sdk 1.0.0 source.
Found skipped initialization (PID/gripper protection, delay/acceleration/Phase),
direct torque writes omitting upstream Lock handling, individual versus group
I/O/retries, and prototype-only tracking/range/contact/timing policies.
A pure mocked-source reproduction confirmed SDK group reads discard motor
error bytes while individual reads raise them; this may explain differences
in apparent behavior but does not establish or clear a physical fault.
Full findings and raw default values: docs/official-lerobot-audit.md.

Prepared read-only installed source + motor register audit to capture actual
values and full error bytes without configure/torque/goal/calibration writes.
Installed source export and current-register comparison remain pending local
sudo execution. No motor control or protective thresholds were changed.
