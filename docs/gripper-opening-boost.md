# Opening boost after release

Run `bash scripts/run_opening_boost_act.sh` for the attended, untimed trial.

The fixed 16% threshold was removed at the user's request. While holding, model
requests at least 0.5 percentage points above the measured opening are promoted
to at least 20% before checking release (hold goal + 3 percentage points).
A 17% request while measuring 16% can release; a 17% request while measuring
18% remains a closing command.
Once release is accepted, the opening target is
the largest of **30%**, the promoted model request and measured opening + 5 percentage points,
clamped to 100%. Existing opening speed limits remain active. The jaws must
reach the opening target before a later closing prediction is honored.
Completion allows a 1 percentage point position tolerance, held for 0.1 seconds,
and at least 0.25 seconds since release. This accepts the measured 29.49% plateau
for a 30% command; it does not accept the old 20.55% partial opening.

Holding grip, arm targets, calibration, motor torque settings and fault checks
are unchanged. This threshold does not detect whether the gripper is over the cup.

34 gripper tests passed. Fixed-observation replay of saved trials is in
`outputs/inference/opening-boost-replay.json`; it validates command behavior,
not physical placement success. The fixed 16% threshold was never physically tested.
The 30% minimum addresses the first-attempt 20.55% measured plateau in trial
1792541844471539026. It has not yet been physically tested.
The original launcher still uses the original profile.
