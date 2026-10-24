"""Hold-out replication of the head-of-window fee order (round 4).

The finding (REPORT 3.1) was written down from the blocks committed in 133c919. Blocks fetched later
(`itb passive --per-validator 20`) were never looked at when it was written, so they are a hold-out sample.
Same statistic as itb.analyze: Spearman rho of uL/CU vs position over the first 64 txs of the window's 1st
block (slot % 4 == 0), Jito-tip and failed txs excluded, blocks with >= 20 such txs. CIs: bootstrap by block.
Run: PYTHONPATH=. uv run python scripts/replication_head.py
"""
import json
import subprocess
from pathlib import Path

import numpy as np
from scipy import stats

from itb.analyze import HEAD, load_blocks

P = {v["identity"]: v["group"] for v in json.loads(Path("data/panel.json").read_text())["validators"]}
FOUND = set(subprocess.run(["git", "ls-tree", "--name-only", "133c919", "data/passive/blocks/"],
                           capture_output=True, text=True, check=True).stdout.split())
RNG = np.random.default_rng(20261024)


def ci(x, n=2000):
    x = np.asarray([v for v in x if not np.isnan(v)])
    if len(x) < 3:
        return len(x), np.nan, np.nan, np.nan
    b = RNG.choice(x, (n, len(x))).mean(1)
    return len(x), x.mean(), *np.quantile(b, [0.025, 0.975])


R = {}
for b in load_blocks(Path("data/passive")):
    g = P.get(b.get("leader"))
    if g is None or b["slot"] % 4:
        continue
    tx = sorted((t for t in b["txs"] if not t["jito_tip"] and not t["err"]), key=lambda t: t["i"])
    if len(tx) < 20:
        continue
    hp = np.array([t["cu_price"] or 0 for t in tx[:HEAD]], float)
    r = stats.spearmanr(np.arange(len(hp)), hp).statistic if np.ptp(hp) > 0 else np.nan
    key = "found" if f"data/passive/blocks/{b['slot']}.json.gz" in FOUND else "holdout"
    R.setdefault(g, {"found": [], "holdout": []})[key].append(r)

fmt = lambda n, m, lo, hi: f"{m:+.2f} [{lo:+.2f}, {hi:+.2f}] (n={n})"
print("group | head rho, window's 1st block: discovery sample | hold-out sample")
for g, r in sorted(R.items()):
    print(f"{g} | {fmt(*ci(r['found']))} | {fmt(*ci(r['holdout']))}")
