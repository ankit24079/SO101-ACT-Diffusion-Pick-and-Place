"""Position-based contact heuristic; does not measure or regulate grip force."""
from collections import deque
import math


def startup_raw_goals(positions, calibration):
    """Allow at most four lower-end gripper counts; command valid goals only."""
    goals = dict(positions)
    for name, value in positions.items():
        low, high = calibration[name]['range_min'], calibration[name]['range_max']
        if low <= value <= high:
            continue
        if name == 'gripper' and low-4 <= value < low:
            goals[name] = low
        else:
            raise RuntimeError(f'{name}: raw position {value} outside calibration {low}..{high}')
    return goals


def native_gripper_goal(requested):
    """Match MotorNormMode.RANGE_0_100 unnormalization in LeRobot's bus."""
    if not math.isfinite(requested):
        raise ValueError('Nonfinite gripper goal')
    return min(100., max(0., requested))


class GripperContactHold:
    release_tolerance = .5

    def __init__(self):
        self.history = deque()
        self.hold = None
        self.contact_count = 0
        self.release_count = 0
        self.opening_since = None
        self.last_event = None
        self.release_target = None
        self.release_started = None
        self.release_reached_since = None

    def update(self, requested, observed, now, opening_request=None):
        self.last_event = None
        opening_request = requested if opening_request is None else opening_request
        if not all(math.isfinite(x) for x in (requested, observed, now, opening_request)):
            raise ValueError('Nonfinite gripper input')
        requested = min(100., max(0., requested))
        observed = min(100., max(0., observed))
        if self.release_target is not None:
            # Complete an accepted opening before honoring a contradictory
            # closing prediction. Reaching a jaw target is not proof that the
            # object landed in the cup.
            self.release_target = max(self.release_target,native_gripper_goal(opening_request))
            if observed >= self.release_target-self.release_tolerance:
                if self.release_reached_since is None:
                    self.release_reached_since = now
            else:
                self.release_reached_since = None
            reached = self.release_reached_since is not None and now-self.release_reached_since >= .1
            if reached and now-self.release_started >= .25:
                self.release_target = None
                self.release_started = None
                self.release_reached_since = None
                self.history.clear()
                self.last_event = 'opening_completed'
                return max(requested,observed)
            return self.release_target
        if self.hold is not None:
            # Compare opening intent with the ACTUAL jaw opening, not the
            # tighter hold goal. Small deliberate openings must also release.
            # Debounce small requests; strong opening requests release at once.
            opening_gap = opening_request-observed
            if opening_gap >= .5:
                if self.opening_since is None:
                    self.opening_since = now
            else:
                self.opening_since = None
            persistent_opening = self.opening_since is not None and now-self.opening_since >= .15
            if opening_gap >= 2 or persistent_opening:
                self.hold = None
                self.history.clear()
                self.opening_since = None
                self.release_count += 1
                self.last_event = 'release_on_opening_request'
                self.release_target = native_gripper_goal(opening_request)
                self.release_started = now
                self.release_reached_since = None
                # A rate-limited target may still be closing when the full
                # policy target turns to opening. Do not send more closure on
                # the transition out of contact hold.
                return max(requested, observed)
            else:
                return self.hold
        if observed-requested < 2:
            self.history.clear()
            return requested
        self.history.append((now, observed))
        while len(self.history) > 1 and self.history[1][0] <= now-.15:
            self.history.popleft()
        if now-self.history[0][0] >= .15:
            values = [p for _,p in self.history]
            if max(values)-min(values) <= .3:
                # Keep a small position offset at contact instead of chasing
                # the model's fully closed target against a blocked gripper.
                self.hold = max(0., observed-.5)
                self.contact_count += 1
                self.opening_since = None
                self.last_event = 'contact_hold_started'
                self.history.clear()
                return self.hold
        return requested


class InitialGripperContactHold(GripperContactHold):
    """Original contact/release behavior from confirmed successful trial 1792537604817735857."""

    def update(self, requested, observed, now, opening_request=None):
        self.last_event = None
        opening_request = requested if opening_request is None else opening_request
        if not all(math.isfinite(x) for x in (requested,observed,now,opening_request)):
            raise ValueError('Nonfinite gripper input')
        requested = native_gripper_goal(requested)
        observed = native_gripper_goal(observed)
        if self.hold is not None:
            if opening_request >= self.hold+3:
                self.hold = None
                self.history.clear()
                self.release_count += 1
                self.last_event = 'release_on_opening_request'
            else:
                return self.hold
        if observed-requested < 2:
            self.history.clear()
            return requested
        self.history.append((now,observed))
        while len(self.history)>1 and self.history[1][0]<=now-.15:
            self.history.popleft()
        if now-self.history[0][0]>=.15:
            values=[p for _,p in self.history]
            if max(values)-min(values)<=.3:
                self.hold=max(0.,observed-.5)
                self.contact_count+=1
                self.last_event='contact_hold_started'
                self.history.clear()
                return self.hold
        return requested


class OpeningBoostGripperContactHold(InitialGripperContactHold):
    """Promote model opening intent before release detection; finish the opening."""

    # The physical 30% command settled at 29.488% in trial 1792542066683956942.
    # Allow ordinary position tracking error without waiting for encoder jitter.
    release_tolerance = 1.

    def update(self, requested, observed, now, opening_request=None):
        if self.release_target is not None:
            # The base class completes an already accepted opening. Its release
            # detection is never used here; the original detector below decides.
            return GripperContactHold.update(self, requested, observed, now, opening_request)
        opening_request = requested if opening_request is None else opening_request
        if not all(math.isfinite(x) for x in (requested, observed, now, opening_request)):
            raise ValueError('Nonfinite gripper input')
        if self.hold is not None and opening_request >= observed+.5:
            # Boost opening intent, never a request that is still closing.
            opening_request = max(20., opening_request)
        result = super().update(requested, observed, now, opening_request)
        if self.last_event == 'release_on_opening_request':
            # The old ~21% target left the cube against the jaws on the first
            # attempt. Command clearance immediately instead of waiting for a
            # later model prediction to request a wider opening.
            self.release_target = native_gripper_goal(max(30., opening_request, observed+5.))
            self.release_started = now
            self.release_reached_since = None
            return max(native_gripper_goal(requested), native_gripper_goal(observed))
        return result


class CloseAfterReleaseGripperHold(OpeningBoostGripperContactHold):
    """Complete release, close gently, and keep closed until a new model cycle."""

    def __init__(self):
        super().__init__()
        self.post_release_phase = None
        self.close_reached_since = None
        self.next_pickup_armed = False

    def update(self, requested, observed, now, opening_request=None):
        opening_request = requested if opening_request is None else opening_request
        if not all(math.isfinite(x) for x in (requested, observed, now, opening_request)):
            raise ValueError('Nonfinite gripper input')
        if self.post_release_phase == 'closing':
            # Reuse the tested position-stall contact hold if something remains
            # between the jaws. The caller limits physical closure to 60 pp/s.
            result = InitialGripperContactHold.update(self, 0., observed, now, opening_request=0.)
            if self.hold is not None:
                self.post_release_phase = None
                self.last_event = 'post_release_close_obstructed'
                return result
            if observed <= 1.:
                if self.close_reached_since is None:
                    self.close_reached_since = now
                if now-self.close_reached_since >= .1:
                    self.post_release_phase = 'closed'
                    self.next_pickup_armed = False
                    self.history.clear()
                    self.last_event = 'post_release_close_completed'
            else:
                self.close_reached_since = None
            return result
        if self.post_release_phase == 'closed':
            self.last_event = None
            # Do not immediately reopen just because the model kept its release
            # target high. Require a fresh close-then-open sequence for pickup.
            if opening_request <= 5.:
                self.next_pickup_armed = True
            if self.next_pickup_armed and opening_request >= 20.:
                self.post_release_phase = None
                self.next_pickup_armed = False
                result = super().update(requested, observed, now, opening_request)
                self.last_event = 'next_pickup_opening'
                return result
            return 0.
        result = super().update(requested, observed, now, opening_request)
        if self.last_event == 'opening_completed':
            self.post_release_phase = 'closing'
            self.close_reached_since = None
            self.history.clear()
            self.last_event = 'post_release_close_started'
        return result
