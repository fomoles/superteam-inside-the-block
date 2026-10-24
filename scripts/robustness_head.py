"""Round-3 robustness check (exploratory, not pre-registered).

For the first block of every panel leader window (slot % 4 == 0, >= 256 txs, Jito-tip and failed txs excluded):
- Spearman rank of µL/CU vs position in the head (first 64), a middle placebo (txs 128-191) and the tail (last 64);
- the same head rank with price-0 txs dropped;
- how over-represented the block's top-10 % fee txs are in the head (1 = no enrichment);
- the head rank per validator, to see whether both validators of a group agree.
Run: PYTHONPATH=. uv run python scripts/robustness_head.py
"""
import json
from pathlib import Path

import numpy as np
from scipy import stats

from itb.analyze import load_blocks

P = {v["identity"]: v["group"] for v in json.loads(Path("data/panel.json").read_text())["validators"]}


def rho(prices):
    if len(prices) < 20 or np.ptp(prices) == 0:
        return np.nan
    return stats.spearmanr(range(len(prices)), prices).statistic


R = {}
for b in load_blocks(Path("data/passive")):
    g = P.get(b.get("leader"))
    if g is None or b["slot"] % 4:
        continue
    tx = [t for t in b["txs"] if not t["jito_tip"] and not t["err"]]
    if len(tx) < 256:
        continue
    p = np.array([t["cu_price"] or 0 for t in tx], float)
    r = R.setdefault(g, {"head": [], "mid": [], "tail": [], "head_nz": [], "enrich": [], "v": {}})
    r["head"].append(rho(p[:64]))
    r["mid"].append(rho(p[128:192]))
    r["tail"].append(rho(p[-64:]))
    r["head_nz"].append(rho(p[:64][p[:64] > 0]))
    thr = np.quantile(p, 0.9)
    r["enrich"].append((p[:64] >= thr).mean() / max((p >= thr).mean(), 1e-9))
    r["v"].setdefault(b["leader"][:4], []).append(r["head"][-1])

print("group | blocks | head | middle | tail | head, price>0 | top-10% fee enrichment in head | head per validator")
for g, r in sorted(R.items()):
    m = lambda k: np.nanmean(r[k])
    v = " ".join(f"{k}…:{np.nanmean(x):+.2f}" for k, x in r["v"].items())
    print(f"{g} | {len(r['head'])} | {m('head'):+.2f} | {m('mid'):+.2f} | {m('tail'):+.2f} | {m('head_nz'):+.2f} | "
          f"x{np.mean(r['enrich']):.2f} | {v}")
