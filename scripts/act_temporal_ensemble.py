"""Time-aligned ACT chunk averaging for asynchronous inference.

LeRobot's ACTTemporalEnsembler uses exp(-coefficient * rank), with rank zero
for the oldest contributing prediction. Here each chunk retains its observation
timestamp because prediction updates are slower than the 30 Hz motor clock.
"""
import math
import numpy as np


class TimeAlignedTemporalEnsembler:
    def __init__(self, coefficient=.01, fps=30):
        if not math.isfinite(coefficient) or not math.isfinite(fps) or fps <= 0:
            raise ValueError('Invalid temporal ensemble configuration')
        self.coefficient = coefficient
        self.fps = fps
        self.chunks = []

    def add(self, anchor, actions):
        actions = np.asarray(actions, dtype=float)
        if (not math.isfinite(anchor) or actions.ndim != 2 or actions.shape[1] != 6
                or not len(actions) or not np.isfinite(actions).all()):
            raise ValueError('Invalid temporal ensemble prediction')
        if self.chunks and anchor <= self.chunks[-1][0]:
            raise ValueError('Prediction timestamps must increase')
        self.chunks.append((anchor, actions.copy()))

    def action(self, now):
        if not math.isfinite(now):
            raise ValueError('Invalid control timestamp')
        self.chunks = [(t,a) for t,a in self.chunks if (now-t)*self.fps < len(a)]
        aligned = []
        for anchor, actions in self.chunks:
            offset = (now-anchor)*self.fps
            if offset >= 0:
                # Tiny tolerance avoids flooring exact frame boundaries one
                # frame early because of floating-point representation.
                index = int(math.floor(offset+1e-7))
                if index < len(actions):
                    aligned.append(actions[index])
        if not aligned:
            raise RuntimeError('No overlapping prediction covers this control time')
        ranks = np.arange(len(aligned), dtype=float)
        logits = -self.coefficient*ranks
        weights = np.exp(logits-logits.max())
        result = np.average(np.asarray(aligned), axis=0, weights=weights)
        return result, len(aligned)
