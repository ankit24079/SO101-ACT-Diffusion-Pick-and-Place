# Native LeRobot ACT inference

`act_robot_inference.py` now defaults to the installed LeRobot 0.6.1
`ACTPolicy.select_action()` implementation. With `--temporal-ensemble`, it sets
`temporal_ensemble_coeff=0.01` and `n_action_steps=1` before model construction.
This uses the installed `ACTTemporalEnsembler`; no timestamp-based chunk
selection, background predictions, custom averaging, or command slew limiting
is applied in native mode. Saved checkpoint pre/postprocessors remain in use.

Without `--temporal-ensemble`, the native action queue executes the 100 predicted
actions sequentially before another model prediction. Temporal ensembling is
off by default in LeRobot and in the trained checkpoint. Enabling it at inference
does not require retraining.

The native temporal loop runs observation → inference/ensemble → action
synchronously. A nominal 30 Hz request cannot overcome CPU inference latency;
measure achieved control rate. Unlike the previous asynchronous adapter, this
loop consumes one predicted timestep per actual policy call, so a slow CPU
changes real-world timing relative to the recorded 30 Hz demonstrations.

Gripper contact hold is disabled by default to preserve native policy actions.
`--contact-hold` explicitly enables that custom position-based heuristic; it is
not part of LeRobot ACT. The previous asynchronous adapter remains available
only with `--legacy-async` for comparison.

Hardware wrappers retain fault checks, valid-goal checks, a supported-arm torque
off preflight, at most four encoder counts of closed-gripper startup tolerance,
a first-target difference check, bounded trial duration and per-motor shutdown
verification. Calibration and stored voltage limits are not rewritten. Native
follower configure uses its existing default PID, mode and gripper limits.

No trial should be described as an unmodified LeRobot executable: the policy,
ensemble and action queue are native; observation collection, logging, preflight
and stop handling remain this project's wrappers.
