"""Cross-section test of the head-of-window fee order (pre-registered in notes/preregistration-frontend.md).

Many validators per client group instead of one: does the head order belong to the client / the shared front-end,
or to the one operator on the panel? No money; public RPC only.
Run:  PYTHONPATH=. uv run python scripts/frontend_sample.py fetch     # ~120 getLeaderSchedule + ~240 getBlock
      PYTHONPATH=. uv run python scripts/frontend_sample.py analyze   # -> data/results/frontend_sample.txt
Blocks go to data/frontend/fblocks/ (not a `blocks/` dir, so the panel analyses never pick them up).
"""
import asyncio
import collections
import gzip
import json
import sys
from pathlib import Path

import numpy as np
from scipy import stats

from itb.analyze import HEAD
from itb.collect import fetch_block
from itb.rpc import Rpc, endpoints_for
from itb.schedule import WINDOW
from itb.survey import validators_table

SNAP = Path("data/survey/cluster-2026-10-24T003342Z.json.gz")
OUT = Path("data/frontend")
QUOTA = {"AgaveBam 4.3.2": 24, "JitoLabs 4.3.2": 20, "HarmonicAgave 4.3.2": 16, "HarmonicFiredancer 26.10.4": 16,
         "Firedancer 26.10.4": 16, "FireBAM 26.10.4": 12, "Agave 4.3.2": 10, "Rakurai 4.3.2": 8}
PER_IP = 3  # AgaveBam only: spread the sample over BAM nodes
WINDOWS = 2
# panel validators' hold-out estimates (data/results/replication_head.txt, committed before this test)
PANEL = {"AgaveBam 4.3.2": -0.57, "FireBAM 26.10.4": -0.40, "JitoLabs 4.3.2": -0.13, "Agave 4.3.2": -0.17,
         "Rakurai 4.3.2": -0.14, "Firedancer 26.10.4": -0.07, "HarmonicAgave 4.3.2": -0.08,
         "HarmonicFiredancer 26.10.4": -0.05}
ip = lambda r: (r["tpuQuic"] or "").rsplit(":", 1)[0] or None


async def fetch() -> None:
    rows = validators_table(json.load(gzip.open(SNAP)))
    panel = {v["identity"] for v in json.loads(Path("data/panel.json").read_text())["validators"]}
    rng = np.random.default_rng(20261024)
    rpc = Rpc(endpoints_for("mainnet"))
    plan = []
    try:
        now = await rpc.call("getSlot", [{"commitment": "confirmed"}])
        ep = await rpc.call("getEpochInfo", [{"commitment": "confirmed"}])
        first = ep["absoluteSlot"] - ep["slotIndex"]
        for g, quota in QUOTA.items():
            cand = [r for r in rows if f"{r['client']} {r['version']}" == g and r["identity"] not in panel]
            per_ip, taken = collections.Counter(), 0
            for k in rng.permutation(len(cand)):
                r = cand[k]
                if taken >= quota:
                    break
                if g.startswith("AgaveBam") and per_ip[ip(r)] >= PER_IP:
                    continue
                sched = await rpc.call("getLeaderSchedule", [now, {"identity": r["identity"]}], quiet=True)
                starts = sorted(first + i for i in (sched or {}).get(r["identity"], [])
                                if (first + i) % WINDOW == 0 and first + i + WINDOW < now - 64)
                if not starts:
                    continue
                per_ip[ip(r)] += 1
                taken += 1
                plan += [{"group": g, "identity": r["identity"], "ip": ip(r), "slot": s} for s in starts[-WINDOWS:]]
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "plan.json").write_text(json.dumps({"now": now, "snapshot": SNAP.name, "plan": plan}, indent=1))
        print(f"plan: {len({p['identity'] for p in plan})} validators, {len(plan)} blocks")
        sem = asyncio.Semaphore(3)

        async def one(s):
            async with sem:
                await fetch_block(rpc, s, OUT / "fblocks")

        await asyncio.gather(*(one(p["slot"]) for p in plan))
    finally:
        await rpc.close()


def head_rho(b: dict) -> float:
    tx = sorted((t for t in b["txs"] if not t["jito_tip"] and not t["err"]), key=lambda t: t["i"])
    if len(tx) < 20:
        return np.nan
    hp = np.array([t["cu_price"] or 0 for t in tx[:HEAD]], float)
    return stats.spearmanr(np.arange(len(hp)), hp).statistic if np.ptp(hp) > 0 else np.nan


def analyze() -> None:
    rng = np.random.default_rng(20261024)
    plan = json.loads((OUT / "plan.json").read_text())["plan"]
    per_v = collections.defaultdict(list)
    meta = {}
    for p in plan:
        f = OUT / "fblocks" / f"{p['slot']}.json.gz"
        if not f.exists():
            continue
        b = json.load(gzip.open(f))
        if b.get("skipped") or b.get("leader") not in (None, p["identity"]):
            continue
        per_v[p["identity"]].append(head_rho(b))
        meta[p["identity"]] = (p["group"], p["ip"])
    v_mean = {v: np.nanmean(x) for v, x in per_v.items() if not np.all(np.isnan(x))}

    def boot(xs):
        xs = np.asarray(xs)
        d = rng.choice(xs, (2000, len(xs))).mean(1)
        return xs.mean(), *np.quantile(d, [0.025, 0.975]), d

    print(f"# Cross-section of the head-of-window fee order ({len(v_mean)} non-panel validators)\n")
    print("Pre-registered in notes/preregistration-frontend.md. Statistic: Spearman rho of fee/CU vs position over the"
          " first 64 txs of the window's 1st block, mean per validator, then mean over validators; 95 % CI: bootstrap"
          " over validators.\n")
    print("| group | validators | blocks | cross-section mean [95 % CI] | panel validator (hold-out) | H1 within ±0.15 |"
          "\n|---|---|---|---|---|---|")
    G, H1 = {}, []
    for g in QUOTA:
        xs = [m for v, m in v_mean.items() if meta[v][0] == g]
        if len(xs) < 3:
            print(f"| {g} | {len(xs)} | – | – | {PANEL[g]:+.2f} | too few |")
            continue
        m, lo, hi, d = boot(xs)
        G[g] = d
        nb = sum(len(per_v[v]) for v in v_mean if meta[v][0] == g)
        ok = abs(m - PANEL[g]) <= 0.15
        if len(xs) >= 8:
            H1.append(ok)
        print(f"| {g} | {len(xs)} | {nb} | {m:+.2f} [{lo:+.2f}, {hi:+.2f}] | {PANEL[g]:+.2f} | "
              f"{('yes' if ok else 'NO') if len(xs) >= 8 else 'n < 8'} |")
    print(f"\n- **H1** (group mean within ±0.15 of the panel validator): {sum(H1)} of {len(H1)} groups with >= 8 validators.")
    if "AgaveBam 4.3.2" in G and "JitoLabs 4.3.2" in G:
        d = G["AgaveBam 4.3.2"] - G["JitoLabs 4.3.2"]
        est = d.mean()
        lo, hi = np.quantile(d, [0.025, 0.975])
        print(f"- **H2** (AgaveBam − JitoLabs < −0.2, CI excludes 0): {est:+.2f} [{lo:+.2f}, {hi:+.2f}] -> "
              f"{'holds' if est < -0.2 and hi < 0 else 'FAILS'}.")
    h3 = {g: G[g].mean() for g in ("HarmonicAgave 4.3.2", "HarmonicFiredancer 26.10.4") if g in G}
    print(f"- **H3** (both Harmonic groups > −0.15): " + ", ".join(f"{g} {m:+.2f}" for g, m in h3.items())
          + f" -> {'holds' if h3 and all(m > -0.15 for m in h3.values()) else 'FAILS'}.")
    by_ip = collections.defaultdict(list)
    for v, m in v_mean.items():
        if meta[v][0] == "AgaveBam 4.3.2":
            by_ip[meta[v][1]].append(m)
    big = {k: x for k, x in by_ip.items() if len(x) >= 3}
    print(f"- **H4** (every BAM IP with >= 3 sampled validators has mean <= −0.3, descriptive): "
          + ", ".join(f"{k} {np.mean(x):+.2f} (n={len(x)})" for k, x in sorted(big.items()))
          + f" -> {'holds' if big and all(np.mean(x) <= -0.3 for x in big.values()) else 'FAILS' if big else 'no IP with n >= 3'}.")
    print("\nPer validator (identity, group, tpuQuic IP, mean head rho over its blocks):\n")
    for v, m in sorted(v_mean.items(), key=lambda kv: (meta[kv[0]][0], kv[1])):
        print(f"- {meta[v][0]} {v[:8]} {meta[v][1]} {m:+.2f} (blocks={len(per_v[v])})")


if __name__ == "__main__":
    {"fetch": lambda: asyncio.run(fetch()), "analyze": analyze}[sys.argv[1]]()
