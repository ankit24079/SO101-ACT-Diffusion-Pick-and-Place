# Initial teleoperation check

Prepared for LeRobot 0.6.1. Not yet runtime-validated. No recording or cameras
are included in this initial motion check. Camera view assessment follows a
successful controlled arm test.

Local calibration files were reconstructed from read-only register reports,
with the approved follower gripper correction. No existing files were replaced.
IDs are cup_leader and cup_follower, recorded in ignored local configuration.
These recovered values are not a guarantee of mechanical calibration quality.

## Read-only preflight

```bash
sudo docker compose --env-file config/docker.env -f compose.yaml -f compose.teleop-check.yaml run --rm collector
```

No motor writes in this mode. It verifies models, calibration equality, torque
off, position mode, feedback mode, and positions within calibrated ranges (up
to 8 encoder counts of endpoint jitter). It reports normalized leader/follower
pose differences. Review these before any physical alignment or powered test.
It does not invoke the standard robot configure/connect/calibrate routines.

## Stop procedure before any powered test

Both arms must be securely mounted; remove cups and loose objects from the
follower reach and keep cables clear of joints. Keep fingers out of grippers
and other pinch points. Know exactly which accessible power switch or connector
cuts FOLLOWER MOTOR POWER; a USB disconnect is not a reliable emergency stop.
Do not assume there is a physical emergency-stop button. Arrange support so the
arm cannot fall dangerously when torque is removed, without placing a hand in
its motion path. A helper at the power switch is useful.

For normal stop, Ctrl+C triggers best-effort torque disable. For unexpected
motion, contact, or a stalled terminal, immediately cut follower motor power.
Software target limits and signal handling do not replace physical power cutoff.
Disabling torque can let the arm fall. Review a reported communication failure
before restarting; do not blindly rerun.

## Separately approved powered test (do not run before approval)

```bash
sudo docker compose --env-file config/docker.env -f compose.yaml -f compose.teleop-check.yaml run --rm collector python /opt/teleop_check.py --run
```

This writes follower Goal_Position and Torque_Enable only. It preserves existing
PID, acceleration, mode, calibration, IDs, and motor baud registers; their
existing settings have not been mechanically validated. It seeds targets from
current positions before enabling torque, refuses initial differences above
10 normalized units, asks for CLEAR TO MOVE in the terminal, and runs for at
most 20 seconds at a requested 10 Hz. Target change is limited to 5 normalized
units per second (arm range -100..100, gripper 0..100). This is a command limit,
not a physical velocity guarantee. Excessive observed tracking error aborts.
Finally it attempts torque disable on every follower joint independently.
Leader torque is never enabled. Even the initial hold can cause movement.

Do not manually align arms until the preflight results have been reviewed and
torque-off manual handling has been agreed. Do not start recording yet.

## Approved follow-up: teleoperation with cameras

```bash
sudo docker compose --env-file config/docker.env -f compose.yaml -f compose.teleop-check.yaml -f compose.teleop-cameras.yaml run --rm collector
```

Same preflight, target limits, voltage checks, confirmation prompt, and 20-second
limit. Both 640×480/30 FPS MJPG streams start before torque. Preview JPEGs are
saved every half second with delivery timing reports under
outputs/teleop-cameras/<run>/. These are post-run previews, not a live display
or a dataset. Camera errors or delivery staleness over one second abort motion.
Follower torque disable is attempted before camera shutdown and read back.
No calibration, PID, acceleration, motor ID, or motor baud changes occur.
Review both camera views and timing before preparing the first test episode.
