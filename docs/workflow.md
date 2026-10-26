# Staged workflow

Complete and verify one stage before proceeding. User confirmation is required
before commands that install software, modify permissions, configure the robot,
calibrate, enable torque, or move hardware. Show the actual command and explain
its effect first. Existing assembled arms must not undergo motor setup, ID or
baud changes, firmware flashing, or calibration replacement without explicit
confirmation. Diagnose failures from their output before changing packages.

1. **Inspection — complete.** See `inspection.md`. Camera capture and hardware
   roles remain unverified.
2. **Repository — scaffold complete.** Local repository, documentation,
   configuration template, scripts directory, and Git exclusions. No remote.
3. **Environment — pending.** Compare Docker and native Python for the selected
   official LeRobot release. Prefer Docker if serial and camera access works.
   Prepare versioned Dockerfile/Compose configuration before requesting install
   or build approval. Map only identified required devices; avoid privileged
   mode. Persist datasets and outputs on the host. No GPU support is required.
4. **Identification — pending.** Disconnect one controller at a time to identify
   roles. Save persistent paths in ignored local configuration. Identify fixed
   and wrist cameras; test supported 640×480 at 30 FPS capture and previews.
5. **Calibration and teleoperation — pending.** Inspect existing calibration
   identities and compatibility first. Explain reuse or the need to calibrate;
   obtain confirmation before calibration. Before torque or motion, explain how
   to immediately cut arm power using an accessible hardware power disconnect,
   clear people and objects from the reachable area, and obtain workspace-clear
   confirmation. Validate the precise stop procedure for the selected software
   and hardware; do not rely solely on a keyboard interrupt. Begin with slow,
   conservative motion, using only verified supported controls.
6. **Test recording — pending.** Record one approved short episode. Verify
   camera images, follower joint observations, actions, timestamps, task text,
   feature shapes, FPS, dropped frames, duration, visual quality, and persistence
   outside the container before final collection.
7. **Collection preparation — pending.** Prepare a repeatable command with
   consistent camera names, resolution, FPS, robot IDs, task text, timing, and
   initial layout. Document failure marking/re-recording and demonstration
   quality criteria. Obtain approval before starting the final 50–60 successes.

Prepare MSI transfer and ACT training separately later. Do not upload a dataset
or create a remote GitHub repository without explicit authorization.
