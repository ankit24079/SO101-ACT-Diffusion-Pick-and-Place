# Gripper contact hold and release

The default `--gripper-hold-profile initial` restores the original behavior from
operator-confirmed unassisted trial `1792537604817735857`: contact holds at the
observed opening minus 0.5 percentage points, and releases when opening intent
reaches the hold goal plus 3 percentage points. It does not latch opening to
completion. All six targets use the same temporal ensemble by default.
Run `bash scripts/run_successful_act.sh` for that untimed configuration.

The remaining release details below describe the optional experimental
`--gripper-hold-profile revised`, not the default initial profile.

Contact hold is an optional deployment adapter, not part of LeRobot ACT and not
a force controller. It keeps a target 0.5 percentage points tighter than the
observed opening when the gripper is stalled while commanded to close.

Release compares the policy's opening request with the **observed jaw opening**:

- At least 0.5 percentage points more open, maintained for 0.15 seconds: release.
- At least 2 percentage points more open: release immediately.
- Smaller fluctuations or continued closing requests: retain contact hold.

The release transition never sends a target tighter than the currently observed
opening, even when the normal command rate limiter is still catching up. There
is no automatic drop based on elapsed holding time. Once accepted, an opening
request remains active until the observed opening reaches within 0.5 percentage
points of its target for 0.1 seconds, with at least 0.25 seconds since acceptance.
An intervening closing prediction does not cancel that opening; further opening
may increase its target. Opening commands retain the gripper rate limit. This
does not establish that an object has actually fallen or landed in the cup.

With custom asynchronous temporal ensembling, all six targets use the same
ensemble timing by default. An experimental `--gripper-source=latest` override
uses the newest chunk's aligned gripper target instead. A physical trial with
that override triggered openings 0.067s and 0.937s after contact, while the arm
was still following averaged plans. This can release ahead of arm alignment;
the default has been restored to the ensembled gripper target. Opening completion
still prevents a subsequent closing prediction from immediately reversing an
accepted release. Native policy mode uses its own ensembled gripper output.

If the model does not ask
to open, the adapter continues holding; it cannot identify cup alignment from
gripper positions alone.

Trial `control.jsonl` now records `latest_chunk_gripper` (latest unaveraged chunk
at the selected action index, asynchronous mode only), `policy_gripper` (after
ensemble/queue and gripper-source selection), `ensemble_gripper` (before gripper
source selection), `gripper_before_contact_hold`, `gripper_sent`,
`gripper_observed`, `gripper_hold_event`, the pending opening timestamp and
`gripper_release_target`.
Reports count both contact-hold and release events. This allows a missed release
to be distinguished from a policy that never generated an opening request.

This software change preserves calibration, motor torque/current/overload
settings, and fault handling. Physical performance remains to be verified.
