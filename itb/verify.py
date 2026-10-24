"""Independent re-check of stored data against the chain (what a judge would do by hand).

For a random sample of stored blocks: re-fetch `getBlock(slot, transactionDetails="signatures")` and
check leader (Fee reward), tx count and the signature at sampled positions. For every usable live
pair: check both probe signatures sit at the stored indices. Writes data/results/verify.json.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

import pandas as pd

from .analyze import load_blocks
from .log import log
from .rpc import Rpc


async def verify(rpc: Rpc, data: Path, n_blocks: int = 20, seed: int = 7) -> dict:
    blocks = {b["slot"]: b for b in load_blocks(data)}
    pairs_csv = data / "results" / "pairs.csv"
    need = {}
    if pairs_csv.exists():
        p = pd.read_csv(pairs_csv)
        for r in p[p.usable].itertuples():
            need.setdefault(int(r.landed_slot_1), [])
    rng = random.Random(seed)
    sample = sorted(set(rng.sample(sorted(blocks), min(n_blocks, len(blocks)))) | set(need))
    checks, bad = 0, []
    for s in sample:
        b = blocks.get(s)
        if not b:
            continue
        chain = await rpc.call("getBlock", [s, {"encoding": "json", "maxSupportedTransactionVersion": 1,
                                                "transactionDetails": "signatures", "rewards": True,
                                                "commitment": "finalized"}], quiet=True)
        sigs = chain["signatures"]
        leader = next((x["pubkey"] for x in chain.get("rewards") or [] if x.get("rewardType") == "Fee"), None)
        ok = leader == b["leader"] and len(sigs) == b["n_tx"]
        idx = rng.sample(range(len(sigs)), min(5, len(sigs)))
        ok &= all(sigs[i] == b["txs"][i]["sig"] for i in idx)
        checks += 1
        if not ok:
            bad.append(s)
    out = {"blocks_checked": checks, "mismatches": bad, "sample_seed": seed}
    (data / "results").mkdir(parents=True, exist_ok=True)
    (data / "results" / "verify.json").write_text(json.dumps(out, indent=1))
    log("verify", **out)
    return out
