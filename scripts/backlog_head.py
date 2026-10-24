"""Backlog test (exploratory, round 4): is the head-of-block fee order a property of the window start or of every slot start?

- "Sorted backlog" (the leader buffers txs before its window and drains them by priority first) predicts a fee
  order at the head of the window's 1st block and a weaker one in blocks 2-4, which only see txs that arrived
  ~210 ms earlier.
- "High-fee senders aim at slot starts" predicts the same head order in all 4 blocks.
For every panel block (>= 256 txs, Jito-tip and failed txs excluded): Spearman rho of uL/CU vs position in the
first 64 txs, grouped by the block's index in its leader window (slot % 4). CIs: bootstrap by block.
diff = rho(block 1) - mean rho(blocks 2-4); diff < 0 means a stronger order at the window start.
Run: PYTHONPATH=. uv run python scripts/backlog_head.py
"""
import json
from pathlib import Path

import numpy as np
from scipy import stats

from itb.analyze import load_blocks

P = {v["identity"]: v["group"] for v in json.loads(Path("data/panel.json").read_text())["validators"]}
RNG = np.random.default_rng(20261024)


def rho(prices):
    if len(prices) < 20 or np.ptp(prices) == 0:
        return np.nan
    return stats.spearmanr(range(len(prices)), prices).statistic


def ci(x, n=2000):
    x = np.asarray([v for v in x if not np.isnan(v)])
    if len(x) < 3:
        return np.nan, np.nan, np.nan
    b = RNG.choice(x, (n, len(x))).mean(1)
    return x.mean(), *np.quantile(b, [0.025, 0.975])


def diff_ci(first, rest, n=2000):
    f = np.asarray([v for v in first if not np.isnan(v)])
    r = np.asarray([v for v in rest if not np.isnan(v)])
    if len(f) < 3 or len(r) < 3:
        return np.nan, np.nan, np.nan
    b = RNG.choice(f, (n, len(f))).mean(1) - RNG.choice(r, (n, len(r))).mean(1)
    return f.mean() - r.mean(), *np.quantile(b, [0.025, 0.975])


R = {}
for b in load_blocks(Path("data/passive")):
    g = P.get(b.get("leader"))
    if g is None:
        continue
    tx = [t for t in b["txs"] if not t["jito_tip"] and not t["err"]]
    if len(tx) < 256:
        continue
    p = np.array([t["cu_price"] or 0 for t in tx], float)
    R.setdefault(g, {i: [] for i in range(4)})[b["slot"] % 4].append(rho(p[:64]))

fmt = lambda m, lo, hi: f"{m:+.2f} [{lo:+.2f}, {hi:+.2f}]"
print("group | n blocks (1st/2-4th) | head rho, window's 1st block | head rho, blocks 2-4 | diff (1st - rest)")
for g, r in sorted(R.items()):
    rest = r[1] + r[2] + r[3]
    print(f"{g} | {len(r[0])}/{len(rest)} | {fmt(*ci(r[0]))} | {fmt(*ci(rest))} | {fmt(*diff_ci(r[0], rest))}")
