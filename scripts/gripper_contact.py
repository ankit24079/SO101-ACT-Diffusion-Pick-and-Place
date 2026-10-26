"""Position-only contact heuristic. Never changes torque/current protection."""
from dataclasses import dataclass
import math


@dataclass
class GripperContactHold:
    # Units: percentage points of the calibrated gripper opening, 0..100.
    lag_threshold: float = 1.5
    stationary_speed: float = 1.0
    confirmation_seconds: float = 0.3
    hold_error: float = 1.0
    release_margin: float = 2.0
    hold_target: float | None = None
    candidate_since: float | None = None
    previous_observed: float | None = None
    previous_time: float | None = None

    def update(self, requested, commanded, observed, now):
        if not all(math.isfinite(value) for value in (requested, commanded, observed, now)):
            raise ValueError('Invalid gripper contact input')
        if self.previous_time is not None and now <= self.previous_time:
            raise ValueError('Gripper contact timestamps must increase')
        speed = None
        if self.previous_time is not None:
            speed = abs(observed-self.previous_observed)/(now-self.previous_time)
        self.previous_observed, self.previous_time = observed, now
        event = None
        if self.hold_target is not None:
            # Keep absolute calibrated openness: the leader must ask for an
            # opening above the held target to release, rather than just jitter.
            if requested >= min(100.0, self.hold_target+self.release_margin):
                self.hold_target = None
                self.candidate_since = None
                event = 'release_requested'
            else:
                return self.hold_target, self.state('holding')

        closure_requested = requested <= commanded and requested < observed
        stalled_closing = (
            closure_requested and observed-commanded >= self.lag_threshold
            and speed is not None and speed <= self.stationary_speed
        )
        if stalled_closing:
            if self.candidate_since is None:
                self.candidate_since = now
            if now-self.candidate_since >= self.confirmation_seconds:
                # Never add squeeze at contact. Back off excess positional error
                # toward a smaller hold error, then freeze the target.
                self.hold_target = min(100.0, max(0.0, commanded, observed-self.hold_error))
                self.candidate_since = None
                return self.hold_target, self.state('contact_latched')
        else:
            self.candidate_since = None
        return requested, self.state(event or ('contact_pending' if stalled_closing else 'following'))

    def state(self, event):
        return {'event': event, 'holding': self.hold_target is not None,
                'hold_target': self.hold_target,
                'release_above': min(100.0, self.hold_target+self.release_margin) if self.hold_target is not None else None}
