# Stage 1 inspection

Read-only host inspection on October 15, 2026. These are historical observations,
not assumptions for future setup. No software, files, permissions, or robot
settings were changed during inspection; serial devices were not opened.

| Item | Observed result |
| --- | --- |
| OS | Ubuntu 22.04.5 LTS (jammy) |
| Architecture | x86_64 |
| Python | /usr/bin/python3, Python 3.10.12; python3.10 also available |
| Package tools | pip and pip3 on PATH; uv and conda not found on PATH |
| Git | 2.50.1 |
| Docker / Compose | Docker command unavailable |
| RAM | 31 GiB total, approximately 26 GiB available |
| Storage | Approximately 27 GiB free on a 136 GiB filesystem, 80% used |
| Initial workspace | Empty host directory; no repository or Docker configuration |
| Python packages | LeRobot, torch, OpenCV, and pyserial absent from checked Python |
| Discovery tools | lerobot-find-port, lerobot-find-cameras, v4l2-ctl unavailable |
| Serial | Two QinHeng USB Single Serial devices; leader/follower roles unverified |
| Serial permissions | root:dialout, group read/write; host user belongs to dialout |
| Cameras | Integrated webcam plus USB Camera and Innomaker-U20CAM-720P |
| Camera permissions | root:video with additional ACLs; capture access unverified |

Persistent serial and camera links exist. Machine-specific ports and camera
indices are deliberately omitted from shared configuration. Identify roles by
disconnecting one device at a time in Stage 4 and save the mapping locally.
Multiple video nodes for a camera do not establish multiple usable image streams.

The sandbox initially hid USB devices and host group memberships. Successful
read-only checks outside the sandbox established the host findings above.
Python package findings apply only to the inspected interpreter, not every
possible environment on the laptop.

Official references consulted:

- https://huggingface.co/docs/lerobot/main/cheat-sheet
- https://huggingface.co/docs/lerobot/main/en/getting_started_real_world_robot

These pages can change. Recheck official documentation against the selected
installed version before generating installation or hardware commands.
