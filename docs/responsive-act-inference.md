# More responsive temporal averaging

Run `bash scripts/run_responsive_act.sh` for an attended trial, stopping with
Enter or Ctrl+C. It has no time limit.
The launcher now uses `opening-boost-close` to close the jaws after release.

The coefficient is -0.5, so each newer overlapping prediction receives about
1.65 times the weight of its predecessor. The previous +0.01 configuration
averaged predictions almost equally, with slightly greater weight on older ones.
All six joint targets use the same weights to keep arm and jaw commands coordinated.

The contact hold and measured-opening release rule are unchanged: while holding,
model requests >= measured opening + 0.5 percentage points are promoted to at
least 20% before checking the original hold+3 release threshold. Once accepted,
the target is max(30%, model request, measured opening+5); opening completes before closing again.
There is no fixed 16% release threshold or timed forced opening.

After accepted opening completes, the gripper closes toward 0% at no more than
60 percentage points/s. Position-stall contact hold interrupts closure if an
object remains between the jaws. Once measured opening stays <=1% for 0.1s,
the jaws stay closed even if the model is still requesting its release opening.
A subsequent model request <=5% followed by >=20% rearms normal control for
another pickup. These are explicit sequence rules, not visual drop detection.

Reason for this experiment: trial 1792541654122960125 at 11.45 seconds logged
latest-chunk opening 25.19%, ensemble opening 12.18%, and measured opening 16.86%.
That establishes a suppressed release request at that instant, not that the cube
was safely positioned for release or that a different weighting guarantees success.

More recent predictions can fluctuate. Existing target speed limits, calibration,
motor fault checks, camera checks and 1.5-second prediction-age limit remain active.
This does not fix the laptop's CPU inference delay or inconsistent model predictions.

The original and previous opening-boost launchers remain available for comparison.
The newer-weighted profile and 30% release have been physically exercised. The
post-release automatic closure is new and has not yet been physically tested.
Its sequence and obstruction behavior passed offline tests.
