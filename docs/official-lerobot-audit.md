# Official LeRobot comparison — October 19, 2026

Reviewed upstream tag v0.6.1 and the feetech-servo-sdk 1.0.0 PyPI source archive,
matching the versions reported by the earlier container smoke check. Export
installed source files to verify exact local provenance before applying changes.
No motor settings were changed or powered tests run during this audit.

## Material differences

| Area | Upstream reference | Custom prototype |
| --- | --- | --- |
| Follower PID defaults | P=16, I=0, D=32 | Preserves existing registers; skipped normal configure |
| Gripper protection | Max_Torque_Limit=500, Protection_Current=250, Overload_Torque=25 | Confirmed matching by October 19 register audit |
| Bus configuration | Return_Delay_Time=0, Maximum_Acceleration=254, Acceleration=254; clears Phase bit 0x10 when needed | Skipped configure_motors |
| Torque helpers | Disable also sets Lock=0; enable also sets Lock=1 | Direct Torque_Enable writes, preserving existing Lock |
| Position I/O | Group reads with num_read_retries=2; group goal writes | Individual reads/writes, no retries |
| Normalization | use_degrees=True default; gripper 0..100 | Arm range -100..100, gripper 0..100 |
| Startup mapping | Absolute joint commands by default | Session offsets for arm joints |
| Timing | CLI fps=60 default | Diagnostic 10 Hz |
| Additional policies | No prototype-specific checks below | 5-point tracking stop, 8-encoder-count range allowance, 5-unit/s slew limit, contact-hold heuristic |

The listed settings are raw upstream defaults, NOT measured local motor values
or universally safe current/force values. A default max_relative_target is None;
when configured, stock follower send_action clips targets relative to measured
positions. Our fixed tracking-error abort is a different policy. Skipping
initialization avoided unapproved register changes but also means this prototype
was not a verified reproduction of stock LeRobot behavior.

Primary sources:
- https://github.com/huggingface/lerobot/blob/v0.6.1/src/lerobot/robots/so_follower/so_follower.py
- https://github.com/huggingface/lerobot/blob/v0.6.1/src/lerobot/robots/so_follower/config_so_follower.py
- https://github.com/huggingface/lerobot/blob/v0.6.1/src/lerobot/teleoperators/so_leader/so_leader.py
- https://github.com/huggingface/lerobot/blob/v0.6.1/src/lerobot/motors/feetech/feetech.py
- https://github.com/huggingface/lerobot/blob/v0.6.1/src/lerobot/scripts/lerobot_teleoperate.py

## Voltage flags versus program behavior

The SDK 1.0.0 individual response handler obtains the motor error byte from the
received packet; getRxPacketError maps bit 0x01 to Input voltage error and 0x20
to Overload error. It reports only the first matching textual condition.
The LeRobot individual _read raises when the error byte indicates an error.

In contrast, SDK GroupSyncRead.rxPacket assigns the returned error byte to `_`
and only checks communication result. LeRobot's sync-read path does not recover
that discarded flag. A mocked-source test using data=49, communication success,
error byte=1 reproduced group-read success versus individual-read exception.
Proof and source hashes are in ignored outputs/official-source-review-20261019/.

Sources:
- https://pypi.org/project/feetech-servo-sdk/1.0.0/
- https://github.com/Adam-Software/Feetech-Servo-SDK/blob/main/scservo_sdk/group_sync_read.py
- https://github.com/Adam-Software/Feetech-Servo-SDK/blob/main/scservo_sdk/protocol_packet_handler.py
- https://github.com/huggingface/lerobot/blob/v0.6.1/src/lerobot/motors/motors_bus.py

Therefore stock teleoperation apparently continuing would not establish absence
of a motor-reported voltage flag. The prototype did not invent the flag, but it
surfaces conditions the group path may not surface. A checksum-accepted status
flag alone also does not identify an electrical root cause. Do not remove
checks merely to make the program continue. Hardware-only attribution was
premature without an equivalent software comparison and an electrical test.

## Calibration and persistence

Position calibration values are per arm, not universal SO-101 constants. Voltage
limits observed in prior logs are stored motor values, not values set by this
prototype or the upstream configure routines reviewed here. Wrong position
calibration can affect commanded travel; it does not itself demonstrate why a
packet reports a voltage flag.

The prototype's follower limit-restore routine did not reproduce the upstream
Lock=0 sequence. That omission is a persistence hypothesis, not proof of the
cause of reverted limits. Read the existing Lock and other protection/config
registers before designing a narrowly scoped correction. Do not silently unlock
or rewrite calibration now.

## Read-only installed-source/register audit

```bash
sudo docker compose --env-file config/docker.env -f compose.yaml -f compose.official-audit.yaml run --rm collector
```

No image rebuild. Exports installed LeRobot/SDK source with hashes and versions,
then sends SDK READ requests only. Records current P/I/D, protection, lock,
delay/acceleration, calibration, voltage, current/load/temperature and raw error
bytes on expected IDs 1–6. Faulted responses remain explicitly marked; their
values do not clear a fault. No configure, torque, goal, ID, baud-register or
calibration writes. It does not disable any torque already present, so do not
handle the arms if torque is already on. Source export without motor access:

```bash
sudo docker compose --env-file config/docker.env -f compose.yaml -f compose.official-audit.yaml run --rm collector python /opt/audit_lerobot_official.py
```

Outputs persist under outputs/official-audit/<run>/. Compare exported installed
files against the downloaded reference hashes and compare actual register
values before proposing any official-initialization baseline. Such a baseline
would change settings and may enable follower torque: it needs command review,
explicit approval, calibration validation and a clear supported workspace.
The stock calibration CLI can rewrite values; it must not be invoked as a
shortcut. ACT training is separate from this motor-control/teleoperation audit.

## Measured audit result, October 19

Completed report: `outputs/official-audit/1792433850499854440/report.json`.
The eight inspected installed LeRobot files and five SDK files match the
version-matched reference hashes. No motor writes occurred.

The follower already has P/I/D = 16/0/32. Its gripper already has
Max_Torque_Limit = 500, Protection_Current = 250 and Overload_Torque = 25,
matching the upstream follower configure routine. Do not attribute the failures
to missing or incorrect values for these settings, or rewrite them as a fix.
The current gripper limits are 1031–2496. All twelve motors reported torque off
and Lock = 1. Leader voltage readings were 49 raw; follower readings were
118–119 raw. No audited response had a motor error flag or communication error.
These idle measurements do not establish what happened during prior motion.

Two separate issues remain: the custom and upstream read paths handle status
errors differently, and the replacement leader's recorded calibration does not
cover previously observed manual travel. Neither source comparison nor this
idle audit establishes an electrical root cause. Previously attributing the
problem conclusively to hardware was unsupported.
