# Gripper contact hold

Prepared October 19, 2026 for the pinned LeRobot 0.6.1 environment. Software
only; not yet validated on hardware. No current/torque limits or calibration
were changed, and overload/voltage errors still stop motion.

The gripper remains in position mode. Requested opening 0 means closed and
100 means open. A position target does not specify a constant torque; actual
force depends on motor settings, mechanics, object compliance and position error.
This controller cannot promise the motor will never report overload.

## Behavior

- During normal free motion, follow calibrated leader openness with the existing
  5 percentage-points/second command slew limit.
- Treat contact as suspected when closing is requested, measured jaws lag the
  last commanded opening by at least 1.5 percentage points, and jaw movement
  remains at most 1 percentage point/second for 0.3 seconds.
- On contact, choose a held opening no smaller than the previous command, and
  reduce position error toward at most 1 percentage point. Apply the existing
  slew limit to reach it. This backs off excess squeezing; it may reduce grip
  strength or allow an object to slip.
- Keep that target fixed even if the operator closes the leader further.
- Release the latch when the leader requests an opening at least 2 percentage
  points above the held opening (full opening can always release). Resume normal
  opening commands. The operator must open far enough, not just twitch the leader.
- Keep the existing 5-point tracking-error guard for every joint, including the
  gripper, and propagate motor overload, voltage and communication faults.

This is a position-based heuristic, not a contact/force sensor. A jam can look
like contact. Do not use it to push through an obstruction or assume an object
is safely held. No automatic re-squeezing is added after slipping.

Contact events and held/release targets appear in the terminal and in
outputs/task-voltage/<run>/control.jsonl. Recorded actions remain the actual
follower targets sent after contact handling and slew limiting. Dataset context
records the policy parameters, so earlier attempts remain distinguishable.

## Validation performed

Run `python3 -m unittest discover -s tests -p 'test_gripper_contact.py' -v`.
Eight pure software tests cover free motion, contact hold, ignored extra squeeze,
release/regrasp, brief lag, moving jaws, empty closure, invalid input and fully
open release. A replay of historical overload run 1792110922441914446 detects
contact at 60.562 seconds: measured opening 16.86, prior command 12.35, proposed
hold 15.86. This demonstrates detection on recorded data, not closed-loop
hardware performance or force safety.

Before lifting anything, inspect the existing gripper torque/current protection
with torque off and do a bench test with the object supported on the table,
arm joints stationary, fingers clear and motor-power cutoff accessible. Confirm
the workspace is clear before enabling torque. Observe contact hold and opening
release, then verify torque off. A failed grip, slip or overload is not a
successful demonstration. Do not begin final data collection from software tests.

No image rebuild is needed; Compose mounts the new pure controller module.
