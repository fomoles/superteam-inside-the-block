import random
import struct

import base58
import numpy as np
import pandas as pd

from itb import analyze as A
from itb.collect import slim_block

CB = "ComputeBudget111111111111111111111111111111"
SYS = "11111111111111111111111111111111"


def _tx(sig, payer, limit, price, fee, other=None):
    keys = [payer] + ([other] if other else []) + [SYS, CB]
    n = len(keys)
    return {"version": "legacy", "transaction": {"signatures": [sig], "message": {
        "accountKeys": keys,
        "header": {"numRequiredSignatures": 1, "numReadonlySignedAccounts": 0, "numReadonlyUnsignedAccounts": 2},
        "instructions": [
            {"programIdIndex": n - 1, "accounts": [], "data": base58.b58encode(b"\x02" + struct.pack("<I", limit)).decode()},
            {"programIdIndex": n - 1, "accounts": [], "data": base58.b58encode(b"\x03" + struct.pack("<Q", price)).decode()},
        ]}},
        "meta": {"fee": fee, "err": None, "computeUnitsConsumed": 450, "costUnits": 1500, "loadedAddresses": {"writable": [], "readonly": []}}}


def test_slim_block_parses_budget_writable_and_leader():
    blk = {"blockhash": "h", "parentSlot": 9, "blockTime": 1, "rewards": [{"pubkey": "LEADER", "rewardType": "Fee", "lamports": 1}],
           "transactions": [_tx("s1", "P1", 600, 1000, 5001), _tx("s2", "P2", 6000, 10**6, 11000, other="ACC")]}
    s = slim_block(10, blk)
    assert s["leader"] == "LEADER" and s["n_tx"] == 2
    a, b = s["txs"]
    assert (a["cu_limit"], a["cu_price"], a["writable"]) == (600, 1000, ["P1"])
    assert (b["cu_limit"], b["cu_price"], sorted(b["writable"])) == (6000, 10**6, ["ACC", "P2"])


def _synthetic(rule: str, windows=60, seed=0):
    """Fake live data for one group. rule='fee': higher fee always first; 'fifo': arrival order with 10% noise."""
    rng = random.Random(seed)
    pairs, txs, landed = [], [], []
    pid = 0
    for w in range(windows):
        for arm in ("DISC", "EQ", "CONC", "DISC_SEP", "EQ_SEP", "RATIO_AB", "RATIO_BA"):
            from itb.plan import ARMS
            shared, l1, l2 = ARMS[arm]
            pairs.append({"run": "r", "pair_id": pid, "window_slot": 4 * w, "target": "V", "arm": arm, "dt_ms": 0,
                          "phase": "PRE", "group": "G", "live": True})
            from itb.probe import LEVELS
            f1, f2 = LEVELS[l1].cu_price, LEVELS[l2].cu_price
            if rule == "fee" and f1 != f2:
                second_first = f2 > f1
            else:
                second_first = rng.random() < 0.1
            i1, i2 = (5, 3) if second_first else (3, 5)
            for role, i in ((1, i1), (2, i2)):
                sig = f"{pid}-{role}"
                txs.append({"run": "r", "pair_id": pid, "role": role, "sig": sig, "live": True, "status": "sent_tpu",
                            "t_send_ns": 1, "est_leader_slot_at_send": 4 * w + 0.5, "window_slot": 4 * w})
                landed.append({"run": "r", "sig": sig, "pair_id": pid, "role": role, "landed_slot": 4 * w,
                               "err": None, "index": i, "block_leader": "V", "block_n_tx": 100})
            pid += 1
    return {"pairs": pd.DataFrame(pairs), "txs": pd.DataFrame(txs), "landed": pd.DataFrame(landed), "groups": {}}


def test_analysis_separates_fee_priority_from_fifo(monkeypatch):
    monkeypatch.setattr(A, "B", 400)
    fee = A.pair_table(_synthetic("fee"))
    fifo = A.pair_table(_synthetic("fifo", seed=1))
    fifo["group"] = "F"
    S, landing = A.active_summary(pd.concat([fee, fifo]))
    v = dict(zip(S.group, S.verdict))
    assert v == {"G": "fee-priority", "F": "arrival-order (FIFO)"}
    assert S.set_index("group").loc["G", "P_RA_first"] == 1.0  # RA has the higher per-CU price
    assert (landing.usable_share == 1).all()


def test_holm():
    adj = A.holm({"a": 0.01, "b": 0.04, "c": 0.03})
    assert adj["a"] == 0.03 and np.isclose(adj["c"], 0.06) and np.isclose(adj["b"], 0.06)
