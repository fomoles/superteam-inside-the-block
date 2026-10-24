"""Experimental design: which pairs to send into a given leader window.

Unit of observation = a PAIR of probe txs (first, second) sent dt ms apart.
Arms (first -> second):
  DISC      LOW  -> HIGH, same payer   fee rule and send order DISagree
  CONC      HIGH -> LOW,  same payer   both rules agree -> inversions = noise floor
  EQ        MID  -> MID,  same payer   equal priority  -> pure send-order (FIFO) test
  DISC_SEP  LOW  -> HIGH, two payers   like DISC but txs do not conflict
  EQ_SEP    MID  -> MID,  two payers   noise floor for non-conflicting txs
  RATIO_AB  RA   -> RB,   same payer   RA: higher fee per CU, RB: higher total fee
  RATIO_BA  RB   -> RA,   same payer
Factors randomised per pair: arm, dt in {0, 30, 150} ms, phase in {PRE, IN},
path in {TPU (direct to leader), RPC (public sendTransaction)}.
PRE  = first tx aimed to arrive ~250 ms before the window's first slot
       (both txs sit in the leader's buffer when the block starts).
IN   = first tx aimed 100-500 ms after the window starts (streaming block building).
The plan is a pure function of (seed, window slot), so it is reproducible and
the same in dry-run and live.
"""
from __future__ import annotations

import random
from dataclasses import asdict, dataclass

ARMS = {
    #            shared  first   second
    "DISC":     (True,  "LOW",  "HIGH"),
    "CONC":     (True,  "HIGH", "LOW"),
    "EQ":       (True,  "MID",  "MID"),
    "DISC_SEP": (False, "LOW",  "HIGH"),
    "EQ_SEP":   (False, "MID",  "MID"),
    "RATIO_AB": (True,  "RA",   "RB"),
    "RATIO_BA": (True,  "RB",   "RA"),
}
ARM_WEIGHTS = {"DISC": 25, "CONC": 15, "EQ": 15, "DISC_SEP": 15, "EQ_SEP": 10, "RATIO_AB": 10, "RATIO_BA": 10}
DTS_MS = [0, 30, 150]
PRE_OFFSET_MS = -250
IN_OFFSET_MS = (100, 500)
RPC_PATH_SHARE = 0.15
PAIRS_PER_WINDOW = 3


@dataclass
class PairPlan:
    pair_id: int
    window_slot: int
    target: str
    arm: str
    shared_payer: bool
    first_level: str
    second_level: str
    dt_ms: int
    phase: str
    offset_ms: float      # aimed arrival of FIRST tx relative to window start (ms)
    path: str
    payer_first: int      # sub-payer index
    payer_second: int

    def asdict(self) -> dict:
        return asdict(self)


def plan_window(seed: int, window_slot: int, target: str, next_pair_id: int, payer_base: int,
                pairs: int = PAIRS_PER_WINDOW) -> list[PairPlan]:
    rng = random.Random(f"{seed}:{window_slot}")
    arms = list(ARM_WEIGHTS)
    weights = [ARM_WEIGHTS[a] for a in arms]
    out = []
    # One path per window: a window is either all-TPU or all-RPC, so RPC
    # forwarding of one pair cannot interfere with TPU pairs in the same block.
    path = "RPC" if rng.random() < RPC_PATH_SHARE else "TPU"
    for i in range(pairs):
        arm = rng.choices(arms, weights)[0]
        shared, first, second = ARMS[arm]
        phase = rng.choice(["PRE", "IN"])
        offset = PRE_OFFSET_MS + 60 * i if phase == "PRE" else rng.uniform(*IN_OFFSET_MS)
        p1 = payer_base + 2 * i
        out.append(PairPlan(
            pair_id=next_pair_id + i, window_slot=window_slot, target=target, arm=arm, shared_payer=shared,
            first_level=first, second_level=second, dt_ms=rng.choice(DTS_MS), phase=phase,
            offset_ms=round(offset, 1), path=path, payer_first=p1, payer_second=p1 if shared else p1 + 1))
    return out
