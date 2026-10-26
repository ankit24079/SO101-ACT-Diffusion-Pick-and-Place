"""Separate brief loop overruns from a sustained stall; no action catch-up jumps."""
import math


def control_gap_status(seconds):
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError('Invalid control-loop interval')
    if seconds >= 1.0:
        return 'stop'
    return 'late' if seconds > .25 else 'normal'


def bounded_step_time(seconds):
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError('Invalid action-step interval')
    return min(max(seconds,1/30),.05)
